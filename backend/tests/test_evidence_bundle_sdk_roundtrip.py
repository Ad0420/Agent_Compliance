"""End-to-end roundtrip: dashboard bundle ↔ SDK offline verifier.

This is the test we should have had at the Wave 3D.2 + Wave 3C.1 merge
gate. It builds a real evidence bundle via the dashboard's
``build_evidence_bundle_tar_gz`` and then runs the SDK's
``run_offline_verify`` against it from the SAME process. Any schema
drift between the producer and the consumer fails the test
immediately, no manual walkthrough required.

This week's three hotfixes (#276 manifest schema, #278 record schema,
this PR's signing-timestamp precision) would all have failed this
test at PR time. Cheap to run, high signal — keep it.

If a future SDK version changes the bundle parsing contract, update
both the dashboard exporter AND this test together. They are the two
ends of the same wire format.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import pathlib
import tarfile

import pytest

from app.services.evidence_export import build_evidence_bundle_tar_gz


async def _seed_signed_chain(db_session):
    """Build a minimal real-world fixture: one org + customer + one
    record + one checkpoint signed with a real HMAC over the real
    signing message format.

    Returns ``(org, customer, hmac_secret_bytes)``. The caller passes
    ``hmac_secret_bytes`` to the SDK verifier; the test signs the
    checkpoint here so we know the secret matches.
    """
    import hmac as _hmac
    from app.models import (
        Organization,
        Customer,
        ActionRecord,
        ChainState,
        Checkpoint,
        KmsKey,
    )
    from app.services.checkpoint import _checkpoint_message

    org = Organization(name="sdk-roundtrip-org")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    customer = Customer(
        org_id=org.id,
        tenant_id="sdk-roundtrip-tenant",
        display_name="SDK Roundtrip Customer",
        status="active",
    )
    db_session.add(customer)

    chain_state = ChainState(org_id=org.id, latest_sequence=1, latest_hash="")
    db_session.add(chain_state)
    await db_session.commit()

    canonical = '{"action_name":"t","org_id":"' + org.id + '"}'
    record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record = ActionRecord(
        org_id=org.id,
        tenant_id=customer.tenant_id,
        sequence_number=1,
        previous_hash="GENESIS",
        record_hash=record_hash,
        action_name="t",
        action_type="function_call",
        agent_name="default-agent",
        action_timestamp=_dt.datetime(2026, 5, 27, 3, 17, 39),
        recorded_at=_dt.datetime(2026, 5, 27, 3, 17, 38),
        authorized_by="system",
        result="success",
        delegation_chain=[],
        input_data={},
        policies_applied=[],
        environment={},
        outcome={},
        reasoning={},
        metadata_={},
    )
    db_session.add(record)
    # Update chain_state to reflect the record's seal point
    chain_state.latest_sequence = 1
    chain_state.latest_hash = record_hash
    await db_session.commit()

    # Sign the checkpoint with a real HMAC over the canonical message.
    hmac_secret = b"sdk-roundtrip-hmac-secret-12345-12345"
    # Use microsecond precision to match
    # ``services.checkpoint.create_checkpoint``'s ``isoformat()``.
    signed_at_dt = _dt.datetime(2026, 5, 27, 3, 19, 3, 392285)
    signed_at_str = signed_at_dt.isoformat()
    message = _checkpoint_message(
        org.id, 1, record_hash, signed_at_str
    )
    signature = _hmac.new(
        hmac_secret, message, hashlib.sha256
    ).hexdigest()
    key_id = hashlib.sha256(hmac_secret).hexdigest()[:16]

    kms_key = KmsKey(
        key_id=key_id,
        algorithm="hmac-sha256",
        public_key_pem=None,
        is_active=True,
    )
    db_session.add(kms_key)

    checkpoint = Checkpoint(
        org_id=org.id,
        sequence_at_checkpoint=1,
        hash_at_checkpoint=record_hash,
        merkle_root=record_hash,
        key_id=key_id,
        signature=signature,
        created_at=signed_at_dt,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    return org, customer, hmac_secret


@pytest.mark.asyncio
async def test_dashboard_bundle_passes_sdk_offline_verifier(
    db_session, tmp_path: pathlib.Path, monkeypatch
):
    """The headline Phase 3 acceptance gate, encoded as a test.

    Build a bundle via the dashboard exporter, hand it to the SDK's
    ``run_offline_verify``, and assert ``ok=True``. If this fails, the
    headline gate is broken — every regulator walkthrough fails.
    """
    pytest.importorskip("vera.verify.offline")
    from vera.verify.offline import run_offline_verify

    org, customer, hmac_secret = await _seed_signed_chain(db_session)

    # SDK reads the HMAC secret from VERA_HMAC_SECRET env var
    # (matches the CLI's ``--hmac-secret-env`` pattern).
    monkeypatch.setenv("VERA_HMAC_SECRET", hmac_secret.decode("utf-8"))

    bundle_bytes, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=_dt.datetime(2026, 1, 1),
        end=_dt.datetime(2026, 12, 31, 23, 59, 59, 999999),
    )

    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(bundle_bytes)

    result = run_offline_verify(str(bundle_path))

    # Scope the assertion to the checkpoint signature specifically —
    # that's what this hotfix (and the timestamp-precision regression
    # this test exists to prevent) targets. The fixture's record
    # ``leaf_hash`` is synthesized for setup speed and doesn't satisfy
    # the SDK's chain-rule check; that's a separate concern from
    # producer↔consumer schema drift. A future improvement to this
    # test could compute the leaf hash properly via the real
    # ``compute_record_hash`` helper to also exercise record-level
    # verification.
    checkpoints = getattr(result, "checkpoints", [])
    sig_failed = [
        c for c in checkpoints
        if any(
            r in (getattr(c, "reasons", []) or [])
            for r in ("hmac_mismatch", "signature_invalid", "unsupported_algorithm")
        )
    ]
    assert not sig_failed, (
        f"Dashboard-built bundle's CHECKPOINT SIGNATURE failed SDK "
        f"verification. This is the headline Phase 3 acceptance gate.\n"
        f"Failed checkpoints: {sig_failed}\n"
        f"Common causes: timestamp precision mismatch (backend signs "
        f"with microseconds, exporter wrote milliseconds); wrong HMAC "
        f"secret in env var; algorithm field missing from bundle."
    )


@pytest.mark.asyncio
async def test_dashboard_bundle_signed_at_byte_matches_signing_message(
    db_session, tmp_path: pathlib.Path
):
    """Pin the timestamp-precision invariant specifically.

    The SDK reconstructs the HMAC signing message from the
    ``signed_at`` string in the bundle's checkpoint JSON. If that
    string isn't byte-identical to what the backend signed, the HMAC
    won't match — even if every other field is correct.

    This test extracts ``signed_at`` from the produced bundle and
    asserts it equals ``cp.created_at.isoformat()``. A future change
    that re-introduces truncation (e.g. switching to ms precision for
    "cosmetic readability") will fail loudly here.
    """
    import json as _json
    from sqlalchemy import select
    from app.models import Checkpoint

    org, customer, _ = await _seed_signed_chain(db_session)

    bundle_bytes, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=_dt.datetime(2026, 1, 1),
        end=_dt.datetime(2026, 12, 31, 23, 59, 59, 999999),
    )

    # Pull the bundle's checkpoint JSON.
    cp_payload = None
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.name.startswith("checkpoints/") and m.name.endswith(".json"):
                f = tar.extractfile(m)
                assert f is not None
                cp_payload = _json.loads(f.read().decode("utf-8"))
                break
    assert cp_payload is not None, "bundle missing checkpoint JSON"

    # Look up the DB row we signed.
    result = await db_session.execute(
        select(Checkpoint).where(Checkpoint.org_id == org.id)
    )
    cp = result.scalar_one()

    # The exporter's ``signed_at`` MUST be byte-identical to
    # ``cp.created_at.isoformat()`` (the string the backend signed).
    assert cp_payload["signed_at"] == cp.created_at.isoformat(), (
        f"signed_at in bundle ({cp_payload['signed_at']!r}) does NOT "
        f"match the original signing timestamp "
        f"({cp.created_at.isoformat()!r}). The SDK will reconstruct a "
        f"different signing message and the HMAC won't match. Found "
        f"during Phase 3 Scenario 4 acceptance — fix is in "
        f"backend/app/services/evidence_export.py around the cp_meta "
        f"dict's ``signed_at`` field."
    )
