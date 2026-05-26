"""Tests for GET /v1/checkpoints/{date} — Wave 3B.1.

Covers the brief's required surface:

  * Happy path returns the checkpoint sealed end-of-day (UTC) with the
    documented field set.
  * 404 when no checkpoint exists for that day.
  * 409 ``checkpoint_pending`` with ``Retry-After: 60`` when today's
    date is requested and no checkpoint has sealed yet today.
  * 400 ``invalid_date`` when the path parameter is not ISO-8601.
  * Byte-stability: same checkpoint, two calls → byte-identical body.
  * Customer tier reads only their own org's checkpoints.
  * Staff tier reads any org via ``X-Org-Id`` header AND writes a
    ``staff_audit_log`` row.
  * Cross-org isolation: customer requesting another org's data → 404.

We exercise the route through the FastAPI ``async_client`` fixture in
conftest.py. Staff-tier tests stub Clerk JWT verification the way
``test_iam_staff_tier.py`` does — we lean on that module's helper
shape so the patterns stay consistent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import ActionRecord, ChainState, Checkpoint, Organization, StaffAuditLog
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint


def _make_action(name: str = "test_action") -> ActionRecordCreate:
    return ActionRecordCreate(
        action_name=name,
        action_type="function_call",
        agent_name="test-agent",
        result="success",
    )


async def _seed_org(db_session, name: str) -> Organization:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _record_and_seal(
    db_session, org_id: str, *, action_count: int = 2
) -> Checkpoint:
    for i in range(action_count):
        await build_and_insert_record(
            db_session, org_id, _make_action(f"act_{i}")
        )
    return await create_checkpoint(db_session, org_id)


async def _backdate_checkpoint(
    db_session, checkpoint_id: str, when: datetime
) -> None:
    cp = await db_session.get(Checkpoint, checkpoint_id)
    cp.created_at = when
    await db_session.commit()


# ── Happy path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_happy_path(
    async_client, db_session, org_and_key
):
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id, action_count=3)
    # Backdate to a definitely-past day so the 'today' branch can't fire.
    target_day = (datetime.now(timezone.utc) - timedelta(days=3)).date()
    target_dt = datetime.combine(target_day, datetime.min.time()) + timedelta(
        hours=23, minutes=30
    )
    await _backdate_checkpoint(db_session, cp.id, target_dt)

    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checkpoint_id"] == cp.id
    assert body["org_id"] == org.id
    assert body["merkle_root"] == cp.merkle_root
    assert body["kms_key_id"] == cp.key_id
    assert body["signature"] == cp.signature
    assert body["sequence_at_checkpoint"] == cp.sequence_at_checkpoint
    assert body["hash_at_checkpoint"] == cp.hash_at_checkpoint
    assert body["record_count"] == 3
    assert body["prior_checkpoint_id"] is None  # first checkpoint for org
    assert body["head_action_id"] is not None
    # signed_at is ms-precision ISO without TZ
    assert "T" in body["signed_at"]


# ── Byte-stability ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_byte_stable(
    async_client, db_session, org_and_key
):
    """Two GETs for the same checkpoint → byte-identical response bodies."""
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id)
    target_day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    await _backdate_checkpoint(
        db_session,
        cp.id,
        datetime.combine(target_day, datetime.min.time()) + timedelta(hours=12),
    )

    resp1 = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp2 = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.content == resp2.content


# ── 404 path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_404_no_checkpoint(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    far_past = (datetime.now(timezone.utc) - timedelta(days=400)).date()
    resp = await async_client.get(
        f"/v1/checkpoints/{far_past.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "checkpoint_not_found"


# ── 409 pending ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_409_today_pending(
    async_client, org_and_key
):
    """Today's date with no checkpoint yet → 409 + Retry-After: 60."""
    _, raw_key, _ = org_and_key
    today = datetime.now(timezone.utc).date()
    resp = await async_client.get(
        f"/v1/checkpoints/{today.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "checkpoint_pending"
    assert resp.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_today_with_sealed_returns_200(
    async_client, db_session, org_and_key
):
    """If today's checkpoint HAS sealed already, return 200 (not 409)."""
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id)
    # Already lands today by default — no backdating needed.
    today = datetime.now(timezone.utc).date()
    resp = await async_client.get(
        f"/v1/checkpoints/{today.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkpoint_id"] == cp.id


# ── 400 invalid date ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_400_invalid_date(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    # Note: "2026/05/25" can't be tested via path — slashes change the
    # URL routing. The validator still rejects it if called directly.
    for bad in ("not-a-date", "2026-13-01", "yesterday"):
        resp = await async_client.get(
            f"/v1/checkpoints/{bad}",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 400, (bad, resp.text)
        assert resp.json()["code"] == "invalid_date"


# ── Cross-org isolation (customer tier) ──────────────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_cross_org_isolated(
    async_client, db_session, org_and_key
):
    """Customer for org A cannot read org B's checkpoint."""
    other_org = await _seed_org(db_session, "other-org")
    cp_other = await _record_and_seal(db_session, other_org.id)
    target_day = (datetime.now(timezone.utc) - timedelta(days=5)).date()
    await _backdate_checkpoint(
        db_session,
        cp_other.id,
        datetime.combine(target_day, datetime.min.time()),
    )

    _, raw_key, _ = org_and_key  # different org
    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # No checkpoint exists for the requesting org on this day.
    assert resp.status_code == 404


# ── Staff tier ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def staff_headers(monkeypatch):
    """Patch ``verify_clerk_jwt`` to return a staff-shaped claims dict.

    Mirrors the pattern in test_iam_staff_tier.py.
    """
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "clerk_staff_org_id", "staff-org-clerk")

    async def fake_verify(token: str, **kwargs):
        return {
            "sub": "staff-user-1",
            "org_id": "staff-org-clerk",
            "iss": "clerk",
        }

    monkeypatch.setattr(
        "app.services.auth.verify_clerk_jwt", fake_verify
    )
    return {
        "Authorization": "Bearer fake-staff-jwt",
    }


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_staff_reads_other_org(
    async_client, db_session, staff_headers
):
    """Staff with ``X-Org-Id`` header reads a customer org's checkpoint."""
    org = await _seed_org(db_session, "customer-org-a")
    cp = await _record_and_seal(db_session, org.id)
    target_day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    await _backdate_checkpoint(
        db_session,
        cp.id,
        datetime.combine(target_day, datetime.min.time()) + timedelta(hours=8),
    )

    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={**staff_headers, "X-Org-Id": org.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["org_id"] == org.id


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_staff_audit_row_written(
    async_client, db_session, staff_headers
):
    """A staff read writes a ``staff_audit_log`` row (chain-integrity scope)."""
    org = await _seed_org(db_session, "customer-org-b")
    cp = await _record_and_seal(db_session, org.id)
    target_day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    await _backdate_checkpoint(
        db_session,
        cp.id,
        datetime.combine(target_day, datetime.min.time()) + timedelta(hours=8),
    )

    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={**staff_headers, "X-Org-Id": org.id},
    )
    assert resp.status_code == 200

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == org.id,
                StaffAuditLog.resource_type == "checkpoint",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    row = rows[0]
    assert row.staff_id == "staff-user-1"
    assert row.endpoint == "/v1/checkpoints/{checkpoint_date}"
    assert row.resource_id == cp.id


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_staff_audits_on_404(
    async_client, db_session, staff_headers
):
    """Even 404s by staff get audited — the access attempt is itself
    privacy-relevant (staff probed for a date)."""
    org = await _seed_org(db_session, "customer-org-c")
    target_day = (datetime.now(timezone.utc) - timedelta(days=400)).date()

    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={**staff_headers, "X-Org-Id": org.id},
    )
    assert resp.status_code == 404

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == org.id,
                StaffAuditLog.resource_type == "checkpoint",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_staff_without_org_id_400(
    async_client, staff_headers
):
    """Staff without ``X-Org-Id`` header → 400 staff_org_id_required."""
    today = datetime.now(timezone.utc).date()
    resp = await async_client.get(
        f"/v1/checkpoints/{today.isoformat()}",
        headers=staff_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "staff_org_id_required"


# ── Multiple checkpoints same day → latest wins ──────────────────


@pytest.mark.asyncio
async def test_get_checkpoint_by_date_returns_latest_in_day(
    async_client, db_session, org_and_key
):
    """When multiple checkpoints exist for the same UTC day, return the
    latest (largest sequence_at_checkpoint)."""
    org, raw_key, _ = org_and_key
    cp_early = await _record_and_seal(db_session, org.id, action_count=1)
    cp_late = await _record_and_seal(db_session, org.id, action_count=1)
    target_day = (datetime.now(timezone.utc) - timedelta(days=4)).date()
    await _backdate_checkpoint(
        db_session,
        cp_early.id,
        datetime.combine(target_day, datetime.min.time()) + timedelta(hours=3),
    )
    await _backdate_checkpoint(
        db_session,
        cp_late.id,
        datetime.combine(target_day, datetime.min.time()) + timedelta(hours=20),
    )

    resp = await async_client.get(
        f"/v1/checkpoints/{target_day.isoformat()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["checkpoint_id"] == cp_late.id
    assert body["prior_checkpoint_id"] == cp_early.id
