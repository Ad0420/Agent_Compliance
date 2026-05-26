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

from vera.async_client import AsyncVeraClient
from vera.client import VeraClient
from vera.gate import (
    _GATE_RESULT_TO_WIRE_RESULT,
    _WIRE_RESULT_VALUES,
    _normalize_result_for_wire,
    normalize_record_for_wire,
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


def test_caller_supplied_gate_result_is_overwritten_when_sdk_rewrites():
    """If a caller passes a gate-vocabulary ``result`` AND a contradictory
    ``metadata.gate_result``, the SDK's own rewrite MUST overwrite the
    caller's claim. We are the authoritative source for ``gate_result``
    whenever we performed the ``result`` rewrite — otherwise the audit
    trail would lie about which gate verdict the SDK saw.

    Codex /review (PR #250) caught the original setdefault behaviour: a
    caller could send ``result="blocked", metadata={"gate_result":
    "success"}`` and persist a ``failure`` row whose metadata claimed
    the gate said ``success``. That's a silent data-integrity hole in
    the audit trail.
    """
    raw = _sdk_record(
        result="pending_review",
        metadata={"gate_result": "caller_supplied_lie"},
    )
    stripped = VeraClient._strip_internal_fields(raw)
    assert stripped["result"] == "pending"
    # The SDK overwrote ``gate_result`` with the actual original value
    # it rewrote, NOT the caller's claim.
    assert stripped["metadata"]["gate_result"] == "pending_review"


def test_caller_supplied_gate_result_is_kept_when_sdk_does_not_rewrite():
    """If ``result`` was already wire-acceptable and the SDK did NOT
    rewrite it, a caller-supplied ``metadata.gate_result`` is preserved
    untouched — we only claim authority over the field when we actually
    rewrote ``result``."""
    raw = _sdk_record(
        result="success",
        metadata={"gate_result": "ALLOW"},
    )
    stripped = VeraClient._strip_internal_fields(raw)
    assert stripped["result"] == "success"
    assert stripped["metadata"]["gate_result"] == "ALLOW"


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


# ---------------------------------------------------------------------------
# Cross-client coverage — async client must apply the same normalisation
# as the sync client. Codex /review (PR #250) caught that pre-fix the async
# spool replay would 422-and-drop indefinitely because async had its own
# duplicate ``_strip_internal_fields``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_result,expected_wire,expected_gate_result",
    [
        ("pending_review", "pending", "pending_review"),
        ("blocked", "failure", "blocked"),
        ("success", "success", None),  # no rewrite
    ],
)
def test_async_strip_internal_fields_applies_same_normalisation(
    raw_result, expected_wire, expected_gate_result,
):
    """Async ``_strip_internal_fields`` MUST match sync exactly so the
    background spool/queue flush on async deployments doesn't 422 the
    way it did pre-fix.
    """
    raw = _sdk_record(result=raw_result)
    sync_out = VeraClient._strip_internal_fields(raw)
    async_out = AsyncVeraClient._strip_internal_fields(raw)
    assert sync_out["result"] == expected_wire
    assert async_out["result"] == expected_wire
    assert sync_out["result"] == async_out["result"]
    if expected_gate_result is None:
        assert "gate_result" not in async_out.get("metadata", {})
    else:
        assert async_out["metadata"]["gate_result"] == expected_gate_result


# ---------------------------------------------------------------------------
# Shared helper invariants (the function both clients call).
# ---------------------------------------------------------------------------


def test_normalize_record_for_wire_overwrites_caller_gate_result():
    """When the helper rewrites ``result`` it OWNS ``gate_result``.

    A caller passing ``metadata={"gate_result": "X"}`` alongside a
    gate-vocabulary ``result`` cannot make the audit trail claim a
    different verdict than what the SDK rewrote.
    """
    out = normalize_record_for_wire({
        "result": "blocked",
        "metadata": {"gate_result": "lying_value"},
    })
    assert out["result"] == "failure"
    assert out["metadata"]["gate_result"] == "blocked"


def test_normalize_record_for_wire_is_noop_for_wire_accepted_values():
    """Already-acceptable values must not touch ``metadata`` at all."""
    inp = {"result": "success", "metadata": {"foo": "bar"}}
    out = normalize_record_for_wire(inp)
    assert out["result"] == "success"
    assert out["metadata"] == {"foo": "bar"}
    assert "gate_result" not in out["metadata"]


def test_normalize_record_for_wire_handles_missing_metadata():
    """Records without a ``metadata`` key get one created on rewrite."""
    out = normalize_record_for_wire({"result": "pending_review"})
    assert out["result"] == "pending"
    assert out["metadata"] == {"gate_result": "pending_review"}


def test_normalize_record_for_wire_handles_non_string_result():
    """``result`` of unexpected type passes through unchanged so the
    backend's validator surfaces it cleanly instead of crashing here."""
    inp = {"result": None}
    out = normalize_record_for_wire(inp)
    assert out is inp  # short-circuit; no rewrite, no copy


# ---------------------------------------------------------------------------
# Public ``record_action_batch`` path — bypasses the background queue and
# the spool, hits the wire directly. MUST normalise too (caught by Codex).
# ---------------------------------------------------------------------------


def test_record_action_batch_normalises_gate_vocab_results():
    """Callers using the synchronous ``record_action_batch`` API with SDK
    gate vocabulary MUST NOT 422 — the explicit-batch path runs the
    same wire-boundary normaliser as the background flush.

    We stub the HTTP layer via ``MockTransport`` to capture exactly what
    bytes go on the wire, then validate them with the backend schema.
    """
    import httpx
    from vera.client import VeraClient

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/actions/batch":
            import json as _json
            captured.append(_json.loads(request.content))
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    client = VeraClient(
        api_url="http://example.test",
        api_key="al_test_xxx",
        agent_name="test",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )
    client._client._transport = httpx.MockTransport(handler)
    try:
        client.record_action_batch([
            {
                "agent_name": "a",
                "action_name": "x",
                "action_type": "y",
                "result": "pending_review",  # gate vocab — pre-fix would 422
            },
            {
                "agent_name": "a",
                "action_name": "x",
                "action_type": "y",
                "result": "blocked",  # gate vocab — pre-fix would 422
            },
        ])
    finally:
        client.close()

    assert len(captured) == 1
    wire_records = captured[0]["records"]
    assert wire_records[0]["result"] == "pending"
    assert wire_records[0]["metadata"]["gate_result"] == "pending_review"
    assert wire_records[1]["result"] == "failure"
    assert wire_records[1]["metadata"]["gate_result"] == "blocked"
    # Backend validator agrees.
    ActionRecordBatchCreate.model_validate({"records": wire_records})
