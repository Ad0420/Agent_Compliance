"""Tests for ``GET /v1/customers/{tenant_id}/chain-summary`` and
``POST /v1/customers/{tenant_id}/evidence-export`` — Wave 3D.2.

Coverage matrix
---------------

GET /v1/customers/{tenant_id}/chain-summary:
  * happy path returns latest_checkpoint + 30-day timeline with the
    documented field set
  * customer with no actions yet → counts==0, timeline tiles all 'none'
    (cadence=disabled) or 'pending' for today (cadence=daily/hourly)
  * cross-org isolation: customer in org B requested by org A → 404
  * staff tier via ``X-Org-Id`` + audit row written
  * customer_record_count filters by tenant_id (other-customer records
    contribute to total_record_count but not customer_record_count)
  * verification_supported flips to false on HMAC key history; true on
    a synthetic RSA-PEM key history row

POST /v1/customers/{tenant_id}/evidence-export:
  * preview=true returns counts + warnings without bytes
  * preview=false returns a real tar.gz; manifest.json + checkpoints/
    + records/ all present; record paths verify against checkpoint roots
  * selective disclosure: bundle contains ONLY this customer's records;
    other customers' record IDs do not appear in the manifest
  * invalid_date_range → 400
"""
from __future__ import annotations

import gzip
import io
import json
import tarfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import (
    ActionRecord,
    ChainState,
    Checkpoint,
    Customer,
    KmsKey,
    Organization,
    StaffAuditLog,
)
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint
from app.services.evidence_export import verify_bundle_record_path
from app.services.kms import ALGO_HMAC_SHA256
from sqlalchemy import select


# ── Helpers ────────────────────────────────────────────────────────


async def _seed_org(db_session, name: str) -> Organization:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _seed_customer(
    db_session, *, org_id: str, tenant_id: str, display_name: str | None = None
) -> Customer:
    c = Customer(
        org_id=org_id, tenant_id=tenant_id, display_name=display_name or tenant_id
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


def _make_action(name: str, tenant_id: str | None = None) -> ActionRecordCreate:
    return ActionRecordCreate(
        action_name=name,
        action_type="function_call",
        agent_name="scribe-agent",
        result="success",
        tenant_id=tenant_id,
    )


async def _record_and_seal(
    db_session,
    org_id: str,
    *,
    per_customer: list[tuple[str, int]],
) -> Checkpoint:
    """Build N records per tenant_id, then seal a checkpoint.

    ``per_customer`` is ``[(tenant_id, count), ...]``.
    """
    counter = 0
    for tenant_id, count in per_customer:
        for _ in range(count):
            counter += 1
            await build_and_insert_record(
                db_session,
                org_id,
                _make_action(f"act_{counter}", tenant_id=tenant_id),
            )
    return await create_checkpoint(db_session, org_id)


async def _backdate_checkpoint(db_session, checkpoint_id: str, when: datetime) -> None:
    cp = await db_session.get(Checkpoint, checkpoint_id)
    cp.created_at = when
    await db_session.commit()


# ── Chain summary — happy path ─────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_summary_happy_path(async_client, db_session, org_and_key):
    org, raw_key, _ = org_and_key
    await _seed_customer(
        db_session, org_id=org.id, tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    # Two customers in the same checkpoint window
    cp = await _record_and_seal(
        db_session,
        org.id,
        per_customer=[("cleveland_clinic", 3), ("acme_health", 2)],
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/chain-summary",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["tenant_id"] == "cleveland_clinic"
    assert body["customer_display_name"] == "Cleveland Clinic"
    lc = body["latest_checkpoint"]
    assert lc is not None
    assert lc["checkpoint_id"] == cp.id
    assert lc["merkle_root"] == cp.merkle_root
    assert lc["customer_record_count"] == 3
    assert lc["total_record_count"] == 5
    assert lc["sequence_at_checkpoint"] == cp.sequence_at_checkpoint
    # 30 days inclusive of today
    assert len(body["timeline"]) == 30
    # The day this checkpoint was sealed should be 'sealed' with count=3
    today = datetime.now(timezone.utc).date().isoformat()
    today_tile = next(t for t in body["timeline"] if t["date"] == today)
    assert today_tile["status"] == "sealed"
    assert today_tile["checkpoint_id"] == cp.id
    assert today_tile["customer_record_count"] == 3
    # HMAC default in tests → verification_supported is False
    assert body["verification_supported"] is False
    assert (
        body["verification_unsupported_reason"]
        == "hmac_symmetric_no_shared_secret"
    )


# ── Empty state ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_summary_no_actions_yet(async_client, db_session, org_and_key):
    org, raw_key, _ = org_and_key
    await _seed_customer(
        db_session, org_id=org.id, tenant_id="cleveland_clinic"
    )
    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/chain-summary",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["latest_checkpoint"] is None
    # 30 tiles, none sealed
    assert len(body["timeline"]) == 30
    assert all(t["status"] in ("none", "pending") for t in body["timeline"])


# ── Selective counts ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_summary_filters_customer_counts(
    async_client, db_session, org_and_key
):
    """Other customers' records contribute to total_record_count but NOT
    to customer_record_count."""
    org, raw_key, _ = org_and_key
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    await _seed_customer(db_session, org_id=org.id, tenant_id="acme_health")
    await _record_and_seal(
        db_session,
        org.id,
        per_customer=[("cleveland_clinic", 1), ("acme_health", 7)],
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/chain-summary",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = resp.json()
    assert body["latest_checkpoint"]["customer_record_count"] == 1
    assert body["latest_checkpoint"]["total_record_count"] == 8


# ── Cross-org isolation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_summary_cross_org_returns_404(
    async_client, db_session, org_and_key
):
    """Customer in another org → 404 (not 403)."""
    org_a, raw_key_a, _ = org_and_key
    org_b = await _seed_org(db_session, "other-org")
    await _seed_customer(
        db_session, org_id=org_b.id, tenant_id="secret_customer"
    )
    resp = await async_client.get(
        "/v1/customers/secret_customer/chain-summary",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 404


# ── Verification-supported flips on asymmetric key ─────────────────


@pytest.mark.asyncio
async def test_chain_summary_verification_supported_with_asymmetric_key(
    async_client, db_session, org_and_key
):
    """Synthetic key-history row with a non-HMAC algorithm + a public-key
    PEM → ``verification_supported=True``.

    Mimics the future RSA-PSS / ECDSA key path. We don't actually verify
    a signature here (that's a frontend concern via Web Crypto API); we
    just assert the panel would offer the Verify button.
    """
    org, raw_key, _ = org_and_key
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    cp = await _record_and_seal(
        db_session, org.id, per_customer=[("cleveland_clinic", 1)]
    )
    # Insert an asymmetric key history row matching the checkpoint's
    # key_id. The seal-time HMAC row exists already; we re-bind the
    # checkpoint to an asymmetric one for this test.
    asym = KmsKey(
        key_id="rsa-test-key",
        algorithm="rsa-pss-sha256",
        public_key_pem="-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----",
        is_active=True,
    )
    db_session.add(asym)
    cp_row = await db_session.get(Checkpoint, cp.id)
    cp_row.key_id = "rsa-test-key"
    await db_session.commit()

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/chain-summary",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = resp.json()
    assert body["verification_supported"] is True
    assert body["verification_unsupported_reason"] is None
    assert body["latest_checkpoint"]["kms_algorithm"] == "rsa-pss-sha256"
    assert "BEGIN PUBLIC KEY" in body["latest_checkpoint"]["kms_public_key_pem"]


# ── Evidence export: preview ───────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_export_preview_returns_counts(
    async_client, db_session, org_and_key
):
    org, raw_key, _ = org_and_key
    await _seed_customer(
        db_session, org_id=org.id, tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_customer(db_session, org_id=org.id, tenant_id="acme_health")
    await _record_and_seal(
        db_session,
        org.id,
        per_customer=[("cleveland_clinic", 3), ("acme_health", 2)],
    )

    resp = await async_client.post(
        "/v1/customers/cleveland_clinic/evidence-export",
        json={"preview": True},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == "cleveland_clinic"
    assert body["customer_display_name"] == "Cleveland Clinic"
    assert body["customer_record_count"] == 3
    assert body["checkpoint_count"] == 1
    # HMAC chain default → bundle warns offline signature verify isn't
    # supported.
    assert "hmac_chain_no_offline_signature_verify" in body["warnings"]


# ── Evidence export: archive + selective disclosure ────────────────


@pytest.mark.asyncio
async def test_evidence_export_archive_contains_only_customer_records(
    async_client, db_session, org_and_key
):
    org, raw_key, _ = org_and_key
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    await _seed_customer(db_session, org_id=org.id, tenant_id="acme_health")
    await _record_and_seal(
        db_session,
        org.id,
        per_customer=[("cleveland_clinic", 3), ("acme_health", 2)],
    )

    # Pull the foreign customer's record IDs so we can assert they don't
    # appear anywhere in the bundle.
    foreign_ids = [
        r.id
        for r in (
            await db_session.execute(
                select(ActionRecord).where(
                    ActionRecord.org_id == org.id,
                    ActionRecord.tenant_id == "acme_health",
                )
            )
        )
        .scalars()
        .all()
    ]

    resp = await async_client.post(
        "/v1/customers/cleveland_clinic/evidence-export",
        json={"preview": False},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/gzip"
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.headers.get("X-Vera-Customer-Record-Count") == "3"
    assert resp.headers.get("X-Vera-Checkpoint-Count") == "1"

    body = resp.content
    # Untar in-memory and inspect.
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
        for info in tf.getmembers():
            f = tf.extractfile(info)
            members[info.name] = f.read() if f else b""

    assert "manifest.json" in members
    manifest = json.loads(members["manifest.json"])
    assert manifest["tenant_id"] == "cleveland_clinic"
    assert manifest["schema_version"] == 1
    assert len(manifest["records"]) == 3
    assert len(manifest["checkpoints"]) == 1

    # Selective disclosure — no foreign IDs leak.
    bundle_text = b"".join(members.values()).decode("utf-8", errors="ignore")
    for fid in foreign_ids:
        assert fid not in bundle_text, (
            f"Foreign customer record id {fid} leaked into selective "
            "disclosure bundle"
        )

    # Phase 3 follow-up: each record carries its ``previous_hash`` so
    # an offline verifier can enforce
    # ``sha256(previous_hash + canonical) == leaf_hash``. Without this
    # the verifier soft-fails with ``previous_hash_unavailable`` and
    # can only check Merkle path inclusion, not the canonical bytes.
    db_previous_hashes = {
        r.id: (r.previous_hash or "")
        for r in (
            await db_session.execute(
                select(ActionRecord).where(
                    ActionRecord.org_id == org.id,
                    ActionRecord.tenant_id == "cleveland_clinic",
                )
            )
        )
        .scalars()
        .all()
    }

    # Per-record verification.
    for record_meta in manifest["records"]:
        rec_bytes = members[f"records/{record_meta['id']}.json"]
        rec = json.loads(rec_bytes)
        assert verify_bundle_record_path(rec) is True
        # Per-checkpoint file present
        cp_file = f"checkpoints/{rec['checkpoint_id']}.json"
        assert cp_file in members
        cp_json = json.loads(members[cp_file])
        assert cp_json["merkle_root"] == rec["merkle_root"]
        # ``previous_hash`` per record, matching the DB row.
        assert "previous_hash" in rec, (
            f"record {record_meta['id']} bundle JSON missing previous_hash"
        )
        expected_prev = db_previous_hashes[record_meta["id"]]
        assert rec["previous_hash"] == expected_prev, (
            f"record {record_meta['id']}: previous_hash in bundle "
            f"({rec['previous_hash']!r}) does not match DB "
            f"({expected_prev!r})"
        )


# ── Evidence export: invalid range ─────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_export_invalid_date_range_400(
    async_client, db_session, org_and_key
):
    org, raw_key, _ = org_and_key
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    resp = await async_client.post(
        "/v1/customers/cleveland_clinic/evidence-export",
        json={
            "start_date": "2026-05-20",
            "end_date": "2026-05-10",
            "preview": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # The app's HTTPException handler flattens dict-typed ``detail`` to
    # the top level (see ``main._flatten_dict_detail``) — same envelope
    # the rest of the routes return.
    assert body["code"] == "invalid_date_range"


# ── Cross-org isolation on the export endpoint ─────────────────────


@pytest.mark.asyncio
async def test_evidence_export_cross_org_returns_404(
    async_client, db_session, org_and_key
):
    """Customer in another org → 404 even on the export endpoint."""
    _, raw_key_a, _ = org_and_key
    org_b = await _seed_org(db_session, "other-org")
    await _seed_customer(
        db_session, org_id=org_b.id, tenant_id="secret_customer"
    )
    resp = await async_client.post(
        "/v1/customers/secret_customer/evidence-export",
        json={"preview": True},
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 404


# ── Staff tier audit ───────────────────────────────────────────────


import pytest_asyncio  # noqa: E402 — fixture below


@pytest_asyncio.fixture
async def staff_headers(monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "clerk_staff_org_id", "staff-org-clerk")

    async def fake_verify(token: str, **kwargs):
        return {
            "sub": "staff-user-1",
            "org_id": "staff-org-clerk",
            "iss": "clerk",
        }

    monkeypatch.setattr("app.services.auth.verify_clerk_jwt", fake_verify)
    return {"Authorization": "Bearer fake-staff-jwt"}


@pytest.mark.asyncio
async def test_chain_summary_staff_audit_row_written(
    async_client, db_session, staff_headers
):
    """Staff session via ``X-Org-Id`` writes a staff_audit_log row."""
    org = await _seed_org(db_session, "customer-org-x")
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    await _record_and_seal(
        db_session, org.id, per_customer=[("cleveland_clinic", 1)]
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/chain-summary",
        headers={**staff_headers, "X-Org-Id": org.id},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == org.id,
                StaffAuditLog.resource_type == "customer_chain_summary",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    row = rows[0]
    assert row.staff_id == "staff-user-1"
    assert row.endpoint == "/v1/customers/{tenant_id}/chain-summary"
    assert row.resource_id == "cleveland_clinic"
    assert row.redacted is False


@pytest.mark.asyncio
async def test_evidence_export_staff_audit_row_written(
    async_client, db_session, staff_headers
):
    """Bundle download writes a staff_audit_log row with the record count."""
    org = await _seed_org(db_session, "customer-org-y")
    await _seed_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    await _record_and_seal(
        db_session, org.id, per_customer=[("cleveland_clinic", 2)]
    )

    resp = await async_client.post(
        "/v1/customers/cleveland_clinic/evidence-export",
        json={"preview": False},
        headers={**staff_headers, "X-Org-Id": org.id},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == org.id,
                StaffAuditLog.resource_type == "customer_evidence_bundle",
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    row = rows[0]
    assert row.staff_id == "staff-user-1"
    assert row.resource_count == 2
    assert row.redacted is False
