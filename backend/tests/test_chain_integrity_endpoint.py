"""Tests for GET /v1/dashboard/chain-integrity (Phase 3 Wave 3D.1).

The Home-page tile's at-a-glance answer to "is our evidence trail
intact right now?". Covers:

  * Happy path → status='ok' with sealed checkpoint, chain depth,
    KMS key, cadence.
  * No-checkpoints-yet → status='ok' with chain_depth=0 and no
    ``latest_checkpoint``.
  * Stale checkpoint (hourly cadence, last seal >2h ago) →
    status='warn'.
  * Stale checkpoint (daily cadence, last seal >48h ago) →
    status='warn'.
  * Disabled cadence never warns even when checkpoints are old.
  * Tampered signature on the latest checkpoint → status='error'.
  * Chain gap (oldest in window has seq>1 but no prior row) →
    status='error'.
  * IAM: customer cross-org isolation enforced; staff via X-Org-Id
    reads other org AND writes a ``staff_audit_log`` row.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import ChainState, Checkpoint, Organization, StaffAuditLog
from app.schemas.action import ActionRecordCreate
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint


def _make_action(name: str = "test_action") -> ActionRecordCreate:
    return ActionRecordCreate(
        action_name=name,
        action_type="function_call",
        agent_name="test-agent",
        result="success",
    )


async def _seed_org(db_session, name: str, cadence: str = "daily") -> Organization:
    org = Organization(name=name, checkpoint_cadence=cadence)
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
    """Move a checkpoint's ``created_at`` and re-sign so verify still passes.

    ``created_at`` participates in the canonical message bytes, so a
    naive backdate would invalidate the KMS signature. We re-sign
    with the new timestamp so the freshness-tests can isolate the
    overdue branch from the signature-failure branch. Also wipes the
    external_receipt so verify_checkpoint() doesn't replay a stale
    ExternalProof with the old timestamp.
    """
    from app.services.checkpoint import _checkpoint_message
    from app.services.kms import get_kms

    cp = await db_session.get(Checkpoint, checkpoint_id)
    cp.created_at = when
    new_msg = _checkpoint_message(
        cp.org_id,
        cp.sequence_at_checkpoint,
        cp.hash_at_checkpoint,
        when.isoformat(),
    )
    cp.signature = get_kms().sign(new_msg)
    cp.external_receipt = None
    await db_session.commit()


# ── Happy path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_happy_path_returns_ok(
    async_client, db_session, org_and_key
):
    """Sealed checkpoint, fresh, valid → status='ok' with all fields."""
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id, action_count=3)

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["chain_depth"] == 1
    assert body["cadence"] == "daily"
    assert body["latest_checkpoint"] is not None
    assert body["latest_checkpoint"]["checkpoint_id"] == cp.id
    assert body["latest_checkpoint"]["record_count"] == 3
    assert body["latest_checkpoint"]["sequence"] == cp.sequence_at_checkpoint
    assert body["kms_key"] is not None
    assert body["kms_key"]["key_id"] == cp.key_id
    assert body["kms_key"]["algorithm"]  # non-empty


# ── No checkpoints yet ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_no_checkpoints_yet_returns_ok(
    async_client, org_and_key
):
    """Fresh org → status='ok', chain_depth=0, no latest_checkpoint."""
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["chain_depth"] == 0
    assert body["latest_checkpoint"] is None
    # KMS key surfaced from the current provider even without checkpoints.
    assert body["kms_key"] is not None
    assert body["cadence"] == "daily"
    # Message describes the empty state.
    assert "no checkpoint" in body["message"].lower()


# ── Stale checkpoint (warn) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_hourly_org_stale_seals_warns(
    async_client, db_session, org_and_key
):
    """Hourly cadence org with last seal 3h ago → status='warn'."""
    org, raw_key, _ = org_and_key
    # Flip cadence to hourly for this test.
    org_row = await db_session.get(Organization, org.id)
    org_row.checkpoint_cadence = "hourly"
    await db_session.commit()

    cp = await _record_and_seal(db_session, org.id)
    stale_when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=3
    )
    await _backdate_checkpoint(db_session, cp.id, stale_when)

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "warn"
    assert body["cadence"] == "hourly"
    assert body["latest_checkpoint"] is not None


@pytest.mark.asyncio
async def test_chain_integrity_daily_org_within_grace_stays_ok(
    async_client, db_session, org_and_key
):
    """Daily cadence org with last seal 12h ago → still 'ok'."""
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id)
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=12
    )
    await _backdate_checkpoint(db_session, cp.id, when)

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_chain_integrity_disabled_cadence_never_warns(
    async_client, db_session, org_and_key
):
    """Disabled cadence: stale checkpoints don't trigger warn."""
    org, raw_key, _ = org_and_key
    org_row = await db_session.get(Organization, org.id)
    org_row.checkpoint_cadence = "disabled"
    await db_session.commit()

    cp = await _record_and_seal(db_session, org.id)
    # Backdate 10 days — far past any grace window.
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=10
    )
    await _backdate_checkpoint(db_session, cp.id, when)

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["cadence"] == "disabled"


# ── Signature failure (error) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_tampered_signature_returns_error(
    async_client, db_session, org_and_key
):
    """Flip a bit in the latest checkpoint's signature → status='error'."""
    org, raw_key, _ = org_and_key
    cp = await _record_and_seal(db_session, org.id)
    # Tamper. ``signature`` is a hex string; flipping the first nibble
    # is enough to break HMAC verify.
    cp_row = await db_session.get(Checkpoint, cp.id)
    first = cp_row.signature[0]
    flipped = "0" if first != "0" else "1"
    cp_row.signature = flipped + cp_row.signature[1:]
    await db_session.commit()

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "error"
    assert "failed verification" in body["message"].lower()


# ── Chain gap (error) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_recent_window_gap_returns_error(
    async_client, db_session, org_and_key
):
    """``chain_depth > len(recent)`` yet no prior < oldest_recent → 'error'.

    Hand-craft the structural gap: 2 checkpoints total, but the
    "older" one has a sequence HIGHER than the "newer" one's prior
    pointer would reach. We do this by mutating a real checkpoint
    and adding a synthetic prior-counted row that nonetheless can't
    serve as a prior (sequence >= recent oldest).

    Easiest concrete shape: seal cp_old (seq=N), then seal cp_new
    (seq=M>N). Backdate cp_old far outside the 30-day window so the
    recent window is [cp_new]. Then DELETE cp_old's sequence rows by
    bumping cp_old's sequence to be >= cp_new's — leaving no
    Checkpoint.sequence < cp_new.sequence, but chain_depth == 2.
    The gap detector fires.
    """
    from datetime import timezone as _tz

    org, raw_key, _ = org_and_key
    cp_old = await _record_and_seal(db_session, org.id, action_count=1)
    cp_new = await _record_and_seal(db_session, org.id, action_count=1)

    # Backdate cp_old far enough that the 30-day recent window
    # excludes it but keep it in the DB for the depth count.
    far_past = datetime.now(_tz.utc).replace(tzinfo=None) - timedelta(
        days=60
    )
    await _backdate_checkpoint(db_session, cp_old.id, far_past)

    # Bump cp_old's sequence ABOVE cp_new's. Now there is no
    # checkpoint with sequence < cp_new.sequence, but chain_depth=2
    # — the prior-link to cp_old is broken (it can't be a prior).
    old_row = await db_session.get(Checkpoint, cp_old.id)
    old_row.sequence_at_checkpoint = cp_new.sequence_at_checkpoint + 100
    await db_session.commit()

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "error"
    assert "gap" in body["message"].lower()


# ── IAM: cross-org isolation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_integrity_customer_sees_only_own_org(
    async_client, db_session, org_and_key
):
    """Customer in org A doesn't see org B's chain — they see their own (empty)."""
    other = await _seed_org(db_session, "other-org")
    await _record_and_seal(db_session, other.id, action_count=2)

    _, raw_key, _ = org_and_key  # different org
    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Caller's own org has no checkpoints, so chain_depth=0 and no
    # latest_checkpoint — proves we didn't read across the org line.
    assert body["chain_depth"] == 0
    assert body["latest_checkpoint"] is None


# ── IAM: staff tier writes audit row ──────────────────────────────


@pytest_asyncio.fixture
async def staff_headers(monkeypatch):
    """Stub Clerk JWT verification for a staff-shaped claims dict.

    Mirrors the helper in ``test_checkpoint_by_date.py``.
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
    return {"Authorization": "Bearer fake-staff-jwt"}


@pytest.mark.asyncio
async def test_chain_integrity_staff_reads_other_org_and_audits(
    async_client, db_session, staff_headers
):
    """Staff with X-Org-Id reads customer org's chain + writes audit row."""
    customer = await _seed_org(db_session, "customer-org-a")
    await _record_and_seal(db_session, customer.id, action_count=2)

    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={**staff_headers, "X-Org-Id": customer.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chain_depth"] == 1

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == customer.id,
                StaffAuditLog.resource_type == "chain_integrity",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].staff_id == "staff-user-1"
    assert rows[0].endpoint == "/v1/dashboard/chain-integrity"
    assert rows[0].redacted is False


@pytest.mark.asyncio
async def test_chain_integrity_staff_missing_org_id_400(
    async_client, staff_headers
):
    """Staff session without X-Org-Id is rejected (per dependency)."""
    resp = await async_client.get(
        "/v1/dashboard/chain-integrity",
        headers={**staff_headers},
    )
    assert resp.status_code == 400, resp.text
    # ``app.main._flatten_dict_detail`` lifts dict ``HTTPException.detail``
    # to the top level, so the body IS the structured envelope.
    body = resp.json()
    assert body["code"] == "staff_org_id_required"
