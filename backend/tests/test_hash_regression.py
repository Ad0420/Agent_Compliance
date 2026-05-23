"""Hash regression tests for Phase 1 PR 1 — HASHABLE_FIELDS extension.

The Phase 1 PR 1 schema change promotes ``tenant_id``, ``domain``,
``action_class`` from metadata blob to first-class columns and appends
them to ``HASHABLE_FIELDS``. The contract is:

  1. Records written BEFORE this PR (no values for the three new fields)
     must hash IDENTICALLY before vs. after the extension. The
     ``None``-excluded canonicalizer in ``canonicalize()`` guarantees
     this: missing attributes resolve to ``None`` via the ``getattr``
     default in ``extract_hashable_fields``.

  2. Records WITH a non-None ``tenant_id`` must produce a DIFFERENT
     hash from the same record without one — proves the new field
     actually participates.

  3. ``extract_hashable_fields`` must return the right shape for both
     legacy SimpleNamespace fixtures (no new attrs) and new-shape ORM
     rows (with all three attrs).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.hashing import (
    HASHABLE_FIELDS,
    canonicalize,
    compute_record_hash,
    extract_hashable_fields,
)


def _legacy_record(**overrides) -> SimpleNamespace:
    """A SimpleNamespace shaped like an ActionRecord from BEFORE Phase 1 PR 1
    (no tenant_id / domain / action_class attributes at all)."""
    defaults = {
        "action_name": "test_action",
        "action_type": "function_call",
        "agent_name": "test-agent",
        "data_subject_id": None,
        "agent_version": None,
        "model_id": None,
        "model_version": None,
        "action_description": None,
        "action_timestamp": datetime(2024, 1, 15, 12, 0, 0),
        "target_system": None,
        "target_resource": None,
        "authorized_by": "system",
        "authorization_scope": None,
        "delegation_chain": [],
        "result": "success",
        "error_message": None,
        "duration_ms": 100,
        "input_data": {},
        "policies_applied": [],
        "environment": {},
        "outcome": {},
        "reasoning": {},
        "metadata_": {},
        "org_id": "test-org-id",
        "sequence_number": 1,
        "framework": None,
        "framework_version": None,
        "previous_hash": "GENESIS",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _new_record(**overrides) -> SimpleNamespace:
    """A SimpleNamespace shaped like an ActionRecord AFTER Phase 1 PR 1
    (includes the three new attrs, defaulted to None)."""
    base = _legacy_record()
    for f in ("tenant_id", "domain", "action_class"):
        setattr(base, f, None)
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


# ── HASHABLE_FIELDS structure ─────────────────────────────────


def test_hashable_fields_includes_phase1_pr1_additions():
    """Explicitly assert the new fields are part of the hash contract."""
    for f in ("tenant_id", "domain", "action_class"):
        assert f in HASHABLE_FIELDS, f"{f} must be in HASHABLE_FIELDS"


def test_hashable_fields_appends_new_at_end():
    """Phase 1 PR 1 spec: append at the end. Order matters for downstream
    diff-aware tooling that pretty-prints the canonical form."""
    last_three = HASHABLE_FIELDS[-3:]
    assert set(last_three) == {"tenant_id", "domain", "action_class"}


# ── Extraction shape ──────────────────────────────────────────


def test_extract_hashable_fields_handles_legacy_record():
    """Legacy SimpleNamespace fixture (no new attrs) must extract cleanly
    with the new fields defaulting to None."""
    record = _legacy_record()
    fields = extract_hashable_fields(record)
    for f in ("tenant_id", "domain", "action_class"):
        assert f in fields
        assert fields[f] is None


def test_extract_hashable_fields_handles_new_record():
    """New-shape fixture populates the three new attrs."""
    record = _new_record(
        tenant_id="cleveland_clinic",
        domain="clinical_decision",
        action_class="chart_entry",
    )
    fields = extract_hashable_fields(record)
    assert fields["tenant_id"] == "cleveland_clinic"
    assert fields["domain"] == "clinical_decision"
    assert fields["action_class"] == "chart_entry"


# ── Backwards-compatibility of pre-Phase-1 hashes ─────────────


def test_legacy_record_hash_unchanged_after_field_addition():
    """A record with no tenant_id/domain/action_class must hash to the
    same value as before the fields were added to HASHABLE_FIELDS.

    Implementation strategy: build the canonical form two ways — once
    from the legacy field set (manually constructed without the new
    keys), once from the new HASHABLE_FIELDS pipeline. Both must
    canonicalize to the same string (None-excluded), and therefore
    produce the same hash.
    """
    record = _legacy_record()

    # Path 1: simulate the OLD canonical by extracting only the pre-PR-1
    # subset of fields.
    pre_pr1_fields = [
        f for f in HASHABLE_FIELDS
        if f not in ("tenant_id", "domain", "action_class")
    ]
    old_payload = {f: getattr(record, f, None) for f in pre_pr1_fields}
    old_canonical = canonicalize(old_payload)
    old_hash = compute_record_hash(old_canonical, record.previous_hash)

    # Path 2: the new HASHABLE_FIELDS pipeline.
    new_canonical = canonicalize(extract_hashable_fields(record))
    new_hash = compute_record_hash(new_canonical, record.previous_hash)

    assert old_canonical == new_canonical, (
        "None-excluded canonicalization should produce identical "
        "output when the new fields are NULL."
    )
    assert old_hash == new_hash


# ── Forward-compatibility: new fields participate in the hash ──


def test_tenant_id_changes_record_hash():
    """A record WITH tenant_id must hash differently from the same
    record WITHOUT tenant_id."""
    base = _new_record()
    base_hash = compute_record_hash(
        canonicalize(extract_hashable_fields(base)), base.previous_hash
    )

    with_tenant = _new_record(tenant_id="cleveland_clinic")
    tenant_hash = compute_record_hash(
        canonicalize(extract_hashable_fields(with_tenant)),
        with_tenant.previous_hash,
    )

    assert base_hash != tenant_hash


def test_domain_and_action_class_change_record_hash():
    """Each of the three new fields must independently influence the hash."""
    base = _new_record()
    base_hash = compute_record_hash(
        canonicalize(extract_hashable_fields(base)), base.previous_hash
    )

    for field, value in (
        ("domain", "clinical_decision"),
        ("action_class", "controlled_substance_order"),
    ):
        variant = _new_record(**{field: value})
        variant_hash = compute_record_hash(
            canonicalize(extract_hashable_fields(variant)),
            variant.previous_hash,
        )
        assert base_hash != variant_hash, (
            f"changing {field} from None to {value} did not change the hash"
        )
