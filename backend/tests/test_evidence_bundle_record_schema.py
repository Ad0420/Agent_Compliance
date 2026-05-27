"""Regression test for the Phase 3 evidence-bundle per-record schema hotfix.

Companion to ``test_evidence_bundle_manifest_schema.py`` — that one
pins the top-level manifest contract; this one pins the per-record
contract.

The SDK's offline verifier (``sdk/vera/verify/offline.py``) reads each
``records/<id>.json`` file expecting the field names from the
``GET /v1/records/{id}/merkle-proof`` endpoint shape:

  * ``action_record_canonical`` — canonical JSON of the record bytes
  * ``leaf_hash``, ``merkle_path``, ``merkle_root`` — Merkle proof
  * ``previous_hash`` — chain-rule predecessor
  * ``kms_algorithm`` + ``kms_public_key_pem`` — DENORMALIZED checkpoint
    KMS metadata so the SDK can verify a single proof in isolation

The Wave 3D.2 dashboard exporter originally wrote ``canonical`` (no
``action_`` prefix) and put KMS metadata only on
``checkpoints/<id>.json``. The SDK couldn't pull the algorithm off a
record and bailed with ``unsupported_algorithm`` + every record failed
with ``missing_canonical_or_leaf``. Found during Phase 3 Scenario 4.

This test pins the SDK-required record-level keys so future schema
drift fails fast in CI.
"""
from __future__ import annotations

import io
import json
import tarfile

import pytest

from app.services.evidence_export import build_evidence_bundle_tar_gz


# Keys the SDK's offline verifier reads from each record JSON. Source
# of truth: ``sdk/vera/verify/offline.py`` lines ~310-330 (record
# parsing) and ~419-449 (checkpoint sig assembly). If the SDK adds or
# renames a required key, mirror it here.
SDK_REQUIRED_RECORD_KEYS = frozenset(
    {
        "action_record_canonical",
        "leaf_hash",
        "merkle_path",
        "merkle_root",
        "previous_hash",
        "kms_algorithm",
        # ``kms_public_key_pem`` can be None on HMAC chains — present
        # but null — so we check the KEY exists, not its value.
        "kms_public_key_pem",
    }
)


def _open_bundle_member(buf: bytes, name: str) -> dict:
    with tarfile.open(fileobj=io.BytesIO(buf), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name == name:
                file = tar.extractfile(member)
                assert file is not None
                return json.loads(file.read().decode("utf-8"))
    raise AssertionError(f"bundle did not contain {name}")


def _list_record_filenames(buf: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(buf), mode="r:gz") as tar:
        return sorted(
            m.name
            for m in tar.getmembers()
            if m.name.startswith("records/") and m.name.endswith(".json")
        )


async def _seed_org_with_one_sealed_record(db_session):
    """Build the minimum DB state for an evidence bundle to be non-empty.

    Returns ``(org, customer)`` for the test to feed into
    ``build_evidence_bundle_tar_gz``.
    """
    import datetime as _dt
    import hashlib
    from app.models import (
        Organization,
        Customer,
        APIKey,
        ActionRecord,
        ChainState,
        Checkpoint,
        KmsKey,
    )

    org = Organization(name="test-org-record-schema")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    customer = Customer(
        org_id=org.id,
        tenant_id="test-tenant-record-schema",
        display_name="Test Customer",
        status="active",
    )
    db_session.add(customer)

    chain_state = ChainState(org_id=org.id, latest_sequence=0, latest_hash="GENESIS")
    db_session.add(chain_state)
    await db_session.commit()

    # One real action record, sealed into one real checkpoint.
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
    await db_session.commit()
    await db_session.refresh(record)

    # Register the HMAC key in kms_keys so the exporter can look up the
    # algorithm + public_key_pem when building each record's KMS
    # metadata. In production this row is upserted on first ``sign()``;
    # in the test we seed it manually.
    kms_key = KmsKey(
        key_id="test-hmac-key",
        algorithm="hmac-sha256",
        public_key_pem=None,
        is_active=True,
    )
    db_session.add(kms_key)
    await db_session.commit()

    checkpoint = Checkpoint(
        org_id=org.id,
        sequence_at_checkpoint=1,
        hash_at_checkpoint=record_hash,
        merkle_root=record_hash,  # single-leaf tree
        key_id="test-hmac-key",
        signature="00" * 32,
        created_at=_dt.datetime(2026, 5, 27, 3, 19, 3),
    )
    db_session.add(checkpoint)
    await db_session.commit()

    return org, customer


@pytest.mark.asyncio
async def test_per_record_json_has_sdk_required_keys(db_session):
    """Build a real bundle with one record. Open ``records/<id>.json``.
    Assert every SDK-required key is present and structurally sane.
    """
    org, customer = await _seed_org_with_one_sealed_record(db_session)

    import datetime as _dt
    start = _dt.datetime(2026, 1, 1)
    end = _dt.datetime(2026, 12, 31, 23, 59, 59, 999999)

    bundle_bytes, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=start,
        end=end,
    )

    record_filenames = _list_record_filenames(bundle_bytes)
    assert len(record_filenames) == 1, (
        f"expected exactly 1 record file, got {len(record_filenames)}: {record_filenames}"
    )
    record_payload = _open_bundle_member(bundle_bytes, record_filenames[0])

    missing = SDK_REQUIRED_RECORD_KEYS - set(record_payload.keys())
    assert not missing, (
        f"per-record JSON is missing SDK-required keys: {missing}. "
        f"The SDK offline verifier (sdk/vera/verify/offline.py) reads "
        f"these to verify the Merkle path + signature. Without them, "
        f"every record fails with ``missing_canonical_or_leaf`` or "
        f"``unsupported_algorithm``. Edit "
        f"backend/app/services/evidence_export.py per-record dict and "
        f"re-add the missing key(s)."
    )

    # Type sanity — the SDK doesn't just check presence, it parses.
    assert isinstance(record_payload["action_record_canonical"], str)
    assert isinstance(record_payload["leaf_hash"], str)
    assert isinstance(record_payload["merkle_path"], list)
    assert isinstance(record_payload["merkle_root"], str)
    assert isinstance(record_payload["previous_hash"], str)
    assert isinstance(record_payload["kms_algorithm"], str)
    # HMAC chains have public_key_pem=None — the KEY must be present
    # but the value can be null. The presence check above already
    # covered "key in dict"; this asserts the value type is what the
    # SDK expects (str or None, never a sentinel like "" or "null").
    assert record_payload["kms_public_key_pem"] is None or isinstance(
        record_payload["kms_public_key_pem"], str
    )


@pytest.mark.asyncio
async def test_per_record_canonical_alias_for_backwards_compat(db_session):
    """The hotfix kept ``canonical`` as an alias of
    ``action_record_canonical`` so any downstream consumer that already
    reads the original dashboard field doesn't break. Pin both names
    so a future "cleanup" doesn't drop the alias.
    """
    org, customer = await _seed_org_with_one_sealed_record(db_session)

    import datetime as _dt
    start = _dt.datetime(2026, 1, 1)
    end = _dt.datetime(2026, 12, 31, 23, 59, 59, 999999)

    bundle_bytes, _summary = await build_evidence_bundle_tar_gz(
        db_session,
        customer=customer,
        org=org,
        start=start,
        end=end,
    )

    record_filenames = _list_record_filenames(bundle_bytes)
    record_payload = _open_bundle_member(bundle_bytes, record_filenames[0])

    assert "canonical" in record_payload
    assert "action_record_canonical" in record_payload
    assert (
        record_payload["canonical"]
        == record_payload["action_record_canonical"]
    ), "the two canonical aliases must always be byte-identical"
