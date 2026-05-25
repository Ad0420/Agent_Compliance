"""Phase 2 Wave 2C PR A4 — full HITL round-trip integration test.

Drives the customer-visible loop end-to-end:

  1. ``POST /v1/gates/evaluate`` triggers the diagnosis HITL gate
     (Wave 2B PR A2) which materialises an ``Approval`` and returns a
     ``Ruling`` carrying ``review_id`` + ``required_role``.
  2. The dashboard / reviewer tool calls
     ``POST /v1/reviews/{review_id}/complete`` (this PR) with a
     sufficient role.
  3. The review resolves to ``approved``, the chain anchors a
     resolution record, and the SDK sees ``status='approved'`` if it
     polls ``GET /v1/approvals/{id}``.

The point of this file (vs. ``test_gates_evaluate_integration`` and
``test_reviews_complete``) is to *cross the seam* — same DB session,
same FastAPI app instance, same auth token. Real protection against
gate-vs-A4 metadata drift (e.g. if A2 stops writing ``required_role``
into context, this test fails before the dashboard does).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Approval, BAAAgreement, BAAScope, Customer
from app.services import baa as baa_service


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _reset_baa_cache():
    baa_service._reset_baa_freshness_cache_for_tests()
    yield
    baa_service._reset_baa_freshness_cache_for_tests()


async def _seed_active_baa(db_session, org_id: str) -> None:
    customer = Customer(org_id=org_id, tenant_id="integration_customer")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_evaluate_then_complete_full_hitl_round_trip(
    async_client, org_and_key, db_session
):
    """Evaluate → REQUIRE_HITL → complete → approved."""
    org, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}
    await _seed_active_baa(db_session, org.id)

    # 1. Agent calls evaluate; gate triggers HITL.
    evaluate_r = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "diagnosis_create",
            "action_name": "add_diagnosis",
            "authorized_by": "dr_smith",
            "data_subject_id": "patient_42",
            "input_data": {"icd10": "E11.9", "note": "starting metformin"},
        },
        headers=headers,
    )
    assert evaluate_r.status_code == 200, evaluate_r.text
    ruling = evaluate_r.json()
    assert ruling["effect"] == "require_hitl"
    assert ruling["required_role"] == "attending_physician"
    review_id = ruling["review_id"]
    assert review_id

    # The approval row carries the A2 context fields A4 reads.
    approval_pre = await db_session.get(Approval, review_id)
    await db_session.refresh(approval_pre)
    assert approval_pre.status == "pending"
    assert approval_pre.reviewed_below_threshold is False
    assert approval_pre.context["required_role"] == "attending_physician"

    # 2. Dashboard reviewer completes the review with a sufficient role.
    complete_r = await async_client.post(
        f"/v1/reviews/{review_id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "note": "Diagnosis matches chart history.",
        },
        headers=headers,
    )
    assert complete_r.status_code == 200, complete_r.text
    body = complete_r.json()
    assert body["status"] == "approved"
    assert body["resolution_record_id"]
    assert body["decided_at"] is not None
    assert body["callback_received_at"] is not None
    assert body["reviewed_below_threshold"] is False

    # 3. SDK-side poll: GET /v1/approvals/{id} now reflects the
    #    terminal state without re-fetching the gate ruling.
    poll_r = await async_client.get(
        f"/v1/approvals/{review_id}", headers=headers
    )
    assert poll_r.status_code == 200
    assert poll_r.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_evaluate_then_complete_with_insufficient_role_keeps_pending(
    async_client, org_and_key, db_session
):
    """Full loop with the below-threshold path:

    Evaluate → REQUIRE_HITL → complete(nurse) → 403 +
    reviewed_below_threshold=True; the approval stays pending so an
    attending can resolve it on the next call."""
    org, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}
    await _seed_active_baa(db_session, org.id)

    evaluate_r = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "diagnosis_create",
            "action_name": "add_diagnosis",
            "authorized_by": "dr_smith",
            "input_data": {"icd10": "E11.9"},
        },
        headers=headers,
    )
    assert evaluate_r.status_code == 200
    review_id = evaluate_r.json()["review_id"]

    # Below-threshold callback.
    r403 = await async_client.post(
        f"/v1/reviews/{review_id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "nurse",
            "reviewer_id": "nurse_ratched",
        },
        headers=headers,
    )
    assert r403.status_code == 403
    assert r403.json()["code"] == "reviewer_credentials_insufficient"

    # The approval is still pending and the flag is flipped.
    poll_r = await async_client.get(
        f"/v1/approvals/{review_id}", headers=headers
    )
    assert poll_r.status_code == 200
    pending = poll_r.json()
    assert pending["status"] == "pending"
    assert pending["reviewed_below_threshold"] is True

    # An attending can still resolve it; the flag stays True (the
    # audit-trail story that a below-threshold attempt happened earlier
    # is preserved).
    r200 = await async_client.post(
        f"/v1/reviews/{review_id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_attending",
        },
        headers=headers,
    )
    assert r200.status_code == 200
    body = r200.json()
    assert body["status"] == "approved"
    assert body["reviewed_below_threshold"] is True
