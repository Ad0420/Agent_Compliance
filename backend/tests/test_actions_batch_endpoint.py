"""End-to-end tests for ``POST /v1/actions/batch`` against the exact
payload shape the SDK builds.

Companion to ``sdk/tests/test_batch_flush_roundtrip.py`` — that file
asserts the SDK's pre-wire shape passes the backend's pydantic
validator in isolation. THIS file asserts the same shape passes the
full route handler (including the chain insert, the policy engine,
the idempotency layer) when posted as an HTTP request.

Together they cover the W1.3 (audit-batch-422) regression: pre-fix,
every gated action's audit row 422'd at the batch endpoint and the
SDK dropped it. The two tests defend the boundary from both sides so
the next drift surfaces fast.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.models import ActionRecord


# ---------------------------------------------------------------------------
# Helpers — build the exact shape the SDK's gate decorator + spool produce.
# Mirrors ``sdk/vera/client.VeraClient._strip_internal_fields`` output.
# ---------------------------------------------------------------------------


def _sdk_record(
    *,
    action_name: str = "commit_clinical_note",
    result: str = "success",
    gate_result: str | None = None,
    ruling_effect: str = "ALLOW",
    review_id: str | None = None,
    error_message: str | None = None,
    tenant_id: str = "test_tenant",
    **overrides: Any,
) -> dict:
    """Build one batch record in the post-strip shape.

    Mirrors the gate decorator's ``_capture_action`` + the SDK's
    ``_strip_internal_fields`` exactly: ``result`` is wire-normalised,
    the original gate verdict lives in ``metadata.gate_result``, and
    ``metadata.ruling_effect`` carries the gate's machine-readable
    decision so the audit trail can distinguish HITL/BLOCK captures
    from organic ``pending`` / ``failure`` records.
    """
    metadata: dict[str, Any] = {
        "agent_type": "scribe",
        "ruling_effect": ruling_effect,
        "tenant_source": "context_var",
        "record_idempotency_key": uuid.uuid4().hex,
    }
    if gate_result is not None:
        metadata["gate_result"] = gate_result
    if review_id is not None:
        metadata["review_id"] = review_id
    record: dict[str, Any] = {
        "agent_name": "test-scribe",
        "agent_version": "v1.2.3",
        "model_id": "gpt-5",
        "framework": "langchain",
        "action_name": action_name,
        "action_type": "diagnosis_create",
        "result": result,
        "input_data": {"note_id": "n-1"},
        "outcome": {"return_value": "ok"},
        "duration_ms": 42,
        "error_message": error_message,
        "metadata": metadata,
        "tenant_id": tenant_id,
    }
    record.update(overrides)
    return record


async def _count_records(db_session, org_id: str) -> int:
    result = await db_session.execute(
        select(func.count(ActionRecord.id)).where(ActionRecord.org_id == org_id)
    )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Core acceptance: the exact SDK shape posts to /v1/actions/batch and
# returns 200, with rows persisted to the chain.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sdk_shaped_batch_posts_successfully(
    async_client, org_and_key, db_session
):
    """W1.3 (audit-batch-422) — the gate decorator's batch shape MUST 200.

    Pre-fix, this exact payload returned 422 because the SDK sent
    ``result="pending_review"`` which wasn't in the backend's accepted
    enum. The fix normalises at the SDK boundary; this test guards the
    contract from the backend side so a drift either way is caught.
    """
    _, raw_key, _ = org_and_key
    payload = {
        "records": [
            _sdk_record(action_name="allow_call"),
            _sdk_record(
                action_name="hitl_call",
                result="pending",
                gate_result="pending_review",
                ruling_effect="REQUIRE_HITL",
                review_id="rev-abc",
            ),
            _sdk_record(
                action_name="block_call",
                result="failure",
                gate_result="blocked",
                ruling_effect="BLOCK",
                error_message="Stale BAA",
            ),
            _sdk_record(
                action_name="deferred_call",
                result="pending",
                gate_result="pending_review",
                ruling_effect="REQUIRE_DEFERRED_REVIEW",
                review_id="rev-def",
            ),
        ]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 4
    # Chain sequence numbers are contiguous within the batch.
    seqs = [r["sequence_number"] for r in body]
    assert seqs == list(range(seqs[0], seqs[0] + 4))


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 10, 100])
async def test_batch_size_boundaries(count, async_client, org_and_key, db_session):
    """The backend's batch endpoint caps records at 100 (matches the SDK's
    ``_API_MAX_BATCH``). Verify the cap inclusively + the lower bound."""
    org, raw_key, _ = org_and_key
    payload = {
        "records": [
            _sdk_record(action_name=f"a_{i}") for i in range(count)
        ]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert await _count_records(db_session, org.id) == count


@pytest.mark.asyncio
async def test_batch_over_100_is_rejected(async_client, org_and_key):
    """101 records MUST be rejected — exceeds the backend's ``max_length``
    on ``ActionRecordBatchCreate.records``. The SDK's worker caps at
    100 to stay under this; the test guards against a future widening."""
    _, raw_key, _ = org_and_key
    payload = {
        "records": [_sdk_record(action_name=f"too_many_{i}") for i in range(101)]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_with_phi_adjacent_fields_validates(
    async_client, org_and_key, db_session
):
    """PHI-adjacent fields (data_subject_id, target_system, input_data
    with clinical content) are accepted — the backend's PHI-shape
    heuristic only inspects ``tenant_id``, not these fields."""
    org, raw_key, _ = org_and_key
    payload = {
        "records": [
            _sdk_record(
                data_subject_id="patient-001",
                target_system="ehr",
                target_resource="encounter/enc_001",
                action_description="commit diagnosis",
                input_data={"diagnoses": ["acute pancreatitis"]},
            )
        ]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()[0]
    assert body["data_subject_id"] == "patient-001"
    assert body["input_data"] == {"diagnoses": ["acute pancreatitis"]}


@pytest.mark.asyncio
async def test_client_supplied_blocked_still_rejected(async_client, org_and_key):
    """Defense in depth — a client trying to self-attest ``blocked`` MUST
    still 422 even after the SDK fix lands. The backend reserves that
    value for its own policy engine; allowing client claims would let
    callers fabricate "policy fired" records without one actually firing.
    """
    _, raw_key, _ = org_and_key
    payload = {
        "records": [
            _sdk_record(result="blocked"),  # raw, not normalised
        ]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_client_supplied_pending_review_still_rejected(
    async_client, org_and_key
):
    """Same invariant for ``pending_review`` — only the SDK normaliser
    rewrites it to ``pending`` on the wire. The raw value MUST still
    reject so the next drift becomes visible instead of silent.
    """
    _, raw_key, _ = org_and_key
    payload = {
        "records": [
            _sdk_record(result="pending_review"),  # raw, not normalised
        ]
    }
    resp = await async_client.post(
        "/v1/actions/batch",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422
