"""Roundtrip test for SDK → backend batch payload shape (W1.3 — audit-batch-422).

The Phase 2 acceptance gate caught a schema drift: every gate evaluation
emitted a ``vera.client: dropping N records due to VeraValidationError:
HTTP 422`` warning and the SDK quietly lost the audit record. Root cause
was the gate decorator passing ``result="blocked"`` / ``result="pending_review"``
directly to ``enqueue_action`` — neither value is in the backend's
``ActionRecordCreate._CLIENT_RESULT_VALUES`` enum.

These tests assert the exact wire shape the SDK builds (via
``VeraClient._strip_internal_fields``, which is the last code path before
``POST /v1/actions/batch``) passes the backend's pydantic validator. The
import path reaches into the backend tree directly — we don't want a
mock or a duplicate schema definition, because the whole point is to
catch the next drift.

The tests are skipped if the backend tree isn't importable from the
SDK test environment (e.g. on a published-SDK wheel install). In CI
they run because both trees are on the same ``PYTHONPATH``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the backend importable when the test is invoked from
# ``sdk/tests``. The repo layout puts ``backend/`` at the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if _BACKEND_DIR.is_dir() and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from app.schemas.action import (  # type: ignore[import-not-found]
        ActionRecordBatchCreate,
        ActionRecordCreate,
        _CLIENT_RESULT_VALUES,
    )
    _BACKEND_AVAILABLE = True
except Exception:  # pragma: no cover — wheel install path
    _BACKEND_AVAILABLE = False
    _CLIENT_RESULT_VALUES = ()
    ActionRecordCreate = None  # type: ignore[assignment]
    ActionRecordBatchCreate = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    not _BACKEND_AVAILABLE,
    reason="backend tree not importable from this environment",
)

from vera.client import VeraClient
from vera.gate import (
    _GATE_RESULT_TO_WIRE_RESULT,
    _WIRE_RESULT_VALUES,
    _normalize_result_for_wire,
)


# ---------------------------------------------------------------------------
# Sanity: SDK and backend agree on the wire enum.
# ---------------------------------------------------------------------------


def test_sdk_wire_enum_matches_backend_enum():
    """The SDK's ``_WIRE_RESULT_VALUES`` MUST stay in sync with the backend.

    If you're adding a new accepted value to the backend, update
    ``vera.gate._WIRE_RESULT_VALUES`` in the same PR. The wire-boundary
    normaliser in ``VeraClient._strip_internal_fields`` uses this set
    to decide whether a ``result`` needs rewriting.
    """
    assert _WIRE_RESULT_VALUES == set(_CLIENT_RESULT_VALUES), (
        f"SDK wire enum {_WIRE_RESULT_VALUES!r} != backend enum "
        f"{set(_CLIENT_RESULT_VALUES)!r}. The W1.3 (audit-batch-422) "
        f"fix relies on these being identical."
    )


def test_gate_result_mapping_targets_are_wire_acceptable():
    """Every mapped gate result MUST land on a wire-acceptable value.

    Defends against a future edit that adds a mapping ``"x" -> "y"`` where
    ``y`` isn't in the backend's accepted enum — that would re-introduce
    the 422 drift in a sneakier way.
    """
    for original, mapped in _GATE_RESULT_TO_WIRE_RESULT.items():
        assert mapped in _WIRE_RESULT_VALUES, (
            f"gate result {original!r} maps to {mapped!r}, which is not "
            f"in the backend's accepted enum {_WIRE_RESULT_VALUES!r}"
        )


# ---------------------------------------------------------------------------
# Helpers — build an SDK-shaped payload exactly the way the gate decorator
# does. We bypass the gate path so the test stays focused on the wire
# contract rather than the routing logic (which has its own test file).
# ---------------------------------------------------------------------------


def _sdk_record(result: str, **overrides) -> dict:
    """Build the in-queue payload the gate decorator would produce.

    Mirrors ``client.enqueue_action`` + ``gate._capture_action`` in
    structure: every field the SDK actually puts on a record. Internal
    bookkeeping fields prefixed with ``_`` are kept — they're stripped
    on the wire by ``_strip_internal_fields``.
    """
    base = {
        "agent_name": "test-scribe",
        "agent_version": "v1.2.3",
        "model_id": "gpt-5",
        "framework": "langchain",
        "action_name": "commit_clinical_note",
        "action_type": "diagnosis_create",
        "result": result,
        "input_data": {"note_id": "n-1"},
        "outcome": {"return_value": "ok"},
        "duration_ms": 42,
        "error_message": None,
        "metadata": {
            "agent_type": "scribe",
            "ruling_effect": "ALLOW",
            "tenant_source": "context_var",
        },
        "tenant_id": "cleveland_clinic",
        "_idempotency_key": "abc123",
        "_requeue_count": 0,
    }
    base.update(overrides)
    return base


def _validate_batch(records: list[dict]) -> ActionRecordBatchCreate:
    """Send a built batch through the backend's pydantic validator.

    Returns the validated model if it parsed; raises ``ValidationError``
    (which propagates as a test failure) otherwise.
    """
    return ActionRecordBatchCreate.model_validate({"records": records})


# ---------------------------------------------------------------------------
# Core roundtrip — N records of each gate-emitted result variant survive
# the SDK's _strip_internal_fields and the backend validator round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 10, 100])
def test_batch_of_N_allow_records_validates(count):
    """Plain ALLOW records (the most common case) roundtrip cleanly."""
    raw = [_sdk_record(result="success") for _ in range(count)]
    stripped = [VeraClient._strip_internal_fields(r) for r in raw]
    batch = _validate_batch(stripped)
    assert len(batch.records) == count
    assert all(r.result == "success" for r in batch.records)


def test_hitl_pending_review_records_normalised_to_pending():
    """HITL captures (``result="pending_review"`` at the gate) MUST land on
    ``pending`` on the wire and preserve the original in ``metadata.gate_result``.

    This is the exact bug audit-batch-422 fixed: the pre-fix gate sent
    ``"pending_review"`` and the backend rejected with 422.
    """
    raw = _sdk_record(
        result="pending_review",
        metadata={"ruling_effect": "REQUIRE_HITL", "review_id": "rev-1"},
    )
    stripped = VeraClient._strip_internal_fields(raw)
    # Wire-boundary normalisation happened: result mapped, original kept.
    assert stripped["result"] == "pending"
    assert stripped["metadata"]["gate_result"] == "pending_review"
    # The backend now accepts it.
    batch = _validate_batch([stripped])
    record = batch.records[0]
    assert record.result == "pending"
    assert record.metadata["gate_result"] == "pending_review"
    assert record.metadata["ruling_effect"] == "REQUIRE_HITL"


def test_block_records_normalised_to_failure():
    """BLOCK captures (``result="blocked"``) MUST land on ``failure`` on the
    wire — the backend explicitly reserves ``blocked`` for the policy
    engine and rejects client-supplied ``blocked`` with 422.
    """
    raw = _sdk_record(
        result="blocked",
        metadata={"ruling_effect": "BLOCK"},
        error_message="BAA required",
    )
    stripped = VeraClient._strip_internal_fields(raw)
    assert stripped["result"] == "failure"
    assert stripped["metadata"]["gate_result"] == "blocked"
    record = _validate_batch([stripped]).records[0]
    assert record.result == "failure"
    assert record.metadata["gate_result"] == "blocked"
    assert record.metadata["ruling_effect"] == "BLOCK"


def test_mixed_batch_allow_hitl_block_validates():
    """A realistic mixed batch (ALLOW + HITL + BLOCK) roundtrips cleanly.

    This is what the spool will produce in practice: a flush draining
    multiple gate captures across all three routing branches.
    """
    raw = [
        _sdk_record(result="success"),
        _sdk_record(
            result="pending_review",
            metadata={"ruling_effect": "REQUIRE_HITL", "review_id": "rev-a"},
        ),
        _sdk_record(
            result="blocked",
            metadata={"ruling_effect": "BLOCK"},
            error_message="Stale BAA",
        ),
        _sdk_record(
            result="pending_review",
            metadata={"ruling_effect": "REQUIRE_DEFERRED_REVIEW", "review_id": "rev-b"},
        ),
        _sdk_record(result="failure", error_message="downstream error"),
    ]
    stripped = [VeraClient._strip_internal_fields(r) for r in raw]
    batch = _validate_batch(stripped)
    results = [r.result for r in batch.records]
    assert results == ["success", "pending", "failure", "pending", "failure"]


# ---------------------------------------------------------------------------
# Edge cases — fields the backend cares about that the SDK might shape oddly.
# ---------------------------------------------------------------------------


def test_record_without_phi_optional_fields_validates():
    """Minimal records (no data_subject_id, no target_*, no description)
    are the common shape for metadata-only gates and MUST validate."""
    raw = _sdk_record(result="success")
    raw.pop("metadata", None)
    stripped = VeraClient._strip_internal_fields(raw)
    record = _validate_batch([stripped]).records[0]
    assert record.action_name == "commit_clinical_note"


def test_record_with_phi_fields_validates():
    """PHI-adjacent fields (data_subject_id, target_system, target_resource,
    populated input_data) are accepted — the backend's PHI-shape heuristic
    runs on ``tenant_id`` only, not on these fields."""
    raw = _sdk_record(
        result="success",
        data_subject_id="patient-abc-123",
        target_system="ehr",
        target_resource="encounter/enc_001",
        action_description="commit pancreatitis diagnosis to chart",
        input_data={"diagnoses": ["acute pancreatitis"]},
    )
    record = _validate_batch([VeraClient._strip_internal_fields(raw)]).records[0]
    assert record.data_subject_id == "patient-abc-123"
    assert record.target_system == "ehr"
    assert record.input_data == {"diagnoses": ["acute pancreatitis"]}


def test_idempotency_key_promoted_to_metadata():
    """Per-record ``_idempotency_key`` is promoted into
    ``metadata.record_idempotency_key`` before the strip — required so the
    backend can dedupe per-record across batch composition shifts."""
    raw = _sdk_record(result="success", _idempotency_key="key-xyz")
    stripped = VeraClient._strip_internal_fields(raw)
    record = _validate_batch([stripped]).records[0]
    assert record.metadata["record_idempotency_key"] == "key-xyz"
    # Internal field stripped from the wire.
    assert "_idempotency_key" not in stripped


def test_caller_provided_gate_result_metadata_is_preserved():
    """If a caller already set ``metadata.gate_result`` themselves (e.g. a
    user calling ``enqueue_action`` directly), the wire-boundary
    normaliser MUST NOT clobber it. We use ``setdefault`` for this.
    """
    raw = _sdk_record(
        result="pending_review",
        metadata={"gate_result": "caller_supplied_value"},
    )
    stripped = VeraClient._strip_internal_fields(raw)
    assert stripped["result"] == "pending"
    assert stripped["metadata"]["gate_result"] == "caller_supplied_value"


# ---------------------------------------------------------------------------
# Defensive — values that should still 422 (we don't silently swallow
# arbitrary bad input).
# ---------------------------------------------------------------------------


def test_unknown_result_value_still_rejected_by_backend():
    """The normaliser only rewrites values it explicitly knows about.
    A typo / new ruling vocab the SDK doesn't yet know MUST surface as
    a backend 422 so the drift becomes visible instead of silently
    masked.
    """
    raw = _sdk_record(result="some_made_up_value")
    stripped = VeraClient._strip_internal_fields(raw)
    assert stripped["result"] == "some_made_up_value"
    with pytest.raises(Exception):  # pydantic ValidationError
        _validate_batch([stripped])


def test_normaliser_passthrough_for_wire_accepted_values():
    """Values already in the wire enum MUST NOT pollute metadata with a
    ``gate_result`` key — that would lie about the original semantic."""
    for ok in _WIRE_RESULT_VALUES:
        wire, original = _normalize_result_for_wire(ok)
        assert wire == ok
        assert original is None
