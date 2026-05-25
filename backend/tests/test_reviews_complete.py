"""Phase 2 Wave 2C PR A4 — endpoint behaviour tests for
``POST /v1/reviews/{review_id}/complete``.

Coverage:
* 200 happy path (single approver, sufficient role) → status=approved,
  A5 columns populated, chain resolution record written.
* 403 insufficient role → reviewed_below_threshold=True, chain
  ``reviewer_credentials_insufficient`` record present, approval stays
  pending so a higher-role reviewer can still resolve.
* 404 unknown review_id (and cross-org isolation).
* 409 already-resolved review.
* 410 expired review (lazy-expiry — sweeper hasn't run yet).
* 422 validation errors (missing fields, decision typo, oversize note).
* Webhook emission verified via ``WebhookDelivery`` row.
* Multi-approver (approvers_required=2) → first sufficient-role
  callback stays pending and does NOT prematurely set ``decided_at``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    ActionRecord,
    Approval,
    ChainState,
    Organization,
    WebhookDelivery,
    WebhookSubscription,
)
from app.schemas.approval import ApprovalCreate
from app.services.approvals import request_approval
from app.services.auth import generate_api_key


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_hitl_approval(
    db_session,
    org_id: str,
    *,
    required_role: str | None = "attending_physician",
    expires_in_seconds: int | None = None,
    approvers_required: int = 1,
) -> Approval:
    """Materialise an Approval shaped like one A2 would create."""
    create = ApprovalCreate(
        agent_name="scribemd",
        action_name="add_diagnosis",
        action_summary="Add diagnosis E11.9 for patient_42",
        data_subject_id="patient_42",
        context={
            "gate_name": "new_diagnosis_requires_attending",
            "required_role": required_role,
            "citation": "42 CFR 482.24(c)(4)(viii)",
            "reason": "new_diagnosis_proposed",
            "original_input_data": {"icd10": "E11.9"},
        },
        risk_tier="high",
        approvers_required=approvers_required,
        expires_in_seconds=expires_in_seconds,
    )
    return await request_approval(db_session, org_id, create)


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_sufficient_role_resolves_approval(
    async_client, org_and_key, db_session
):
    """200: sufficient role → status=approved, A5 columns set, chain
    resolution record written, ``review.completed`` event dispatched."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "note": "Patient history confirms diagnosis.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["resolution_record_id"]
    assert body["reviewed_below_threshold"] is False
    assert body["decided_at"] is not None
    assert body["callback_received_at"] is not None

    # Decision recorded with the composite approver string.
    assert len(body["decisions"]) == 1
    assert "dr_smith@hospital.example" in body["decisions"][0]["approver"]
    assert "attending_physician" in body["decisions"][0]["approver"]
    assert body["decisions"][0]["signature"]

    # Chain resolution record exists with the right shape.
    record = await db_session.get(ActionRecord, body["resolution_record_id"])
    assert record is not None
    assert record.action_type == "human_approval_resolved"
    assert record.result == "success"
    assert record.reasoning["final_status"] == "approved"


@pytest.mark.asyncio
async def test_complete_review_higher_role_satisfies_lower(
    async_client, org_and_key, db_session
):
    """200: medical_director (level 50) satisfies attending_physician (30)."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "medical_director",
            "reviewer_id": "mdir_jones",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_complete_review_reject_path(async_client, org_and_key, db_session):
    """200: reject with sufficient role terminates as rejected."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
            "note": "Diagnosis not supported by chart.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "rejected"
    record = await db_session.get(ActionRecord, body["resolution_record_id"])
    assert record.result == "failure"
    assert record.reasoning["final_status"] == "rejected"


@pytest.mark.asyncio
async def test_complete_review_required_role_none_accepts_any_known_role(
    async_client, org_and_key, db_session
):
    """200: gate didn't pin a required_role → any recognised role passes."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id, required_role=None)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "nurse",
            "reviewer_id": "nurse_ratched",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


# ── 403: reviewer-credentials-insufficient ──────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_insufficient_role_returns_403_flat_envelope(
    async_client, org_and_key, db_session
):
    """403: nurse (10) cannot satisfy attending_physician (30).

    Verifies the load-bearing requirement from Wave 2B's forward-looking
    review: chain record written + ``reviewed_below_threshold=True`` flag
    flipped, approval stays pending, flat error envelope returned.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "nurse",
            "reviewer_id": "nurse_ratched",
            "note": "I'm just helping",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "reviewer_credentials_insufficient"
    assert body["required_role"] == "attending_physician"
    assert body["reviewer_role"] == "nurse"
    assert body["review_id"] == approval.id

    # ── The load-bearing flag MUST be flipped. ──
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.reviewed_below_threshold is True
    # Approval stays pending so a higher-role reviewer can still
    # resolve it.
    assert refreshed.status == "pending"
    assert refreshed.resolution_record_id is None

    # ── Chain record written for the audit trail. ──
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "reviewer_credentials_insufficient",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    rec = rows[0]
    assert rec.result == "failure"
    assert rec.reasoning["required_role"] == "attending_physician"
    assert rec.reasoning["reviewer_role"] == "nurse"
    assert rec.reasoning["reviewer_id"] == "nurse_ratched"
    assert rec.reasoning["gate_name"] == "new_diagnosis_requires_attending"


@pytest.mark.asyncio
async def test_complete_review_unknown_reviewer_role_fails_closed(
    async_client, org_and_key, db_session
):
    """403: unrecognised role string MUST NOT pass (fail-closed).

    Defends against typos like ``attendng_physician`` silently clearing
    a gate."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attendng_physician",  # typo
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403, response.text
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.reviewed_below_threshold is True


@pytest.mark.asyncio
async def test_complete_review_unknown_reviewer_role_with_no_required_fails_closed(
    async_client, org_and_key, db_session
):
    """403: even with ``required_role=None`` an unknown reviewer role fails."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id, required_role=None)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "i_made_this_up",
            "reviewer_id": "rando",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_complete_review_higher_reviewer_after_below_threshold(
    async_client, org_and_key, db_session
):
    """403 then 200: after a nurse triggers below_threshold, an attending
    can still resolve. ``reviewed_below_threshold`` stays True (auditors
    care that someone WAS below threshold)."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    r1 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "nurse",
            "reviewer_id": "nurse_a",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r1.status_code == 403

    r2 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "approved"
    # Flag persists — the historical below-threshold attempt is part of
    # the audit story.
    assert body["reviewed_below_threshold"] is True


# ── 404: review not found / cross-org ──────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_unknown_id_returns_404(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/reviews/00000000-0000-0000-0000-000000000000/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_complete_review_cross_org_returns_404(
    async_client, org_and_key, db_session
):
    """Org A's reviewer cannot resolve Org B's review."""
    org_a, _raw_a, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org_a.id)

    # Org B with its own API key.
    org_b = Organization(name="other-org")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(ChainState(org_id=org_b.id))
    await db_session.commit()
    raw_b, _ = await generate_api_key(
        db_session, org_b.id, "key-b", ["read", "write", "admin"]
    )

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "mallory",
        },
        headers={"Authorization": f"Bearer {raw_b}"},
    )
    assert response.status_code == 404


# ── 409: already resolved ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_already_resolved_conflicting_decision_returns_409(
    async_client, org_and_key, db_session
):
    """Wave 2D PR A6 changed the second-callback semantics: a callback
    on an already-resolved review now MATCH-OR-CONFLICTS against the
    canonical decision. This test covers the conflict branch (different
    decisions → 409 ``attestation_conflict``). The matching-decision
    branch is covered by
    ``tests/test_attestation_conflict.py::test_second_callback_same_decision_is_idempotent``.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    r1 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r1.status_code == 200

    r2 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_other",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r2.status_code == 409
    body = r2.json()
    assert body["code"] == "attestation_conflict"
    assert body["canonical_decision"] == "approve"
    assert body["conflicting_decision"] == "reject"


# ── 410: expired ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_expired_returns_410(
    async_client, org_and_key, db_session
):
    """Lazy-expiry: the sweeper hasn't run yet but the deadline passed.

    Mirrors the contract from ``services.approvals.decide_approval`` —
    the row transitions to ``expired`` (resolution record + webhook)
    BEFORE we raise 410. Skipping the transition would silently drop
    the ``review.expired`` event customers depend on for cleanup.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(
        db_session, org.id, expires_in_seconds=60
    )
    # Force expiry by backdating the row.
    approval.expires_at = _now_naive_utc() - timedelta(seconds=1)
    await db_session.commit()

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 410
    assert "expired" in response.json()["detail"].lower()

    # Row was transitioned, not just rejected — resolution record exists.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "expired"
    assert refreshed.resolution_record_id is not None


@pytest.mark.asyncio
async def test_complete_review_already_expired_returns_410_without_re_resolve(
    async_client, org_and_key, db_session
):
    """410 when the row already terminal-state expired: don't try to
    re-resolve, just raise."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(
        db_session, org.id, expires_in_seconds=60
    )
    # Pre-resolve as expired (sweeper path).
    from app.services.approvals import _resolve_and_record

    await _resolve_and_record(db_session, approval, "expired")
    original_resolution_id = approval.resolution_record_id

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 410
    # Resolution record wasn't overwritten with a second one.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.resolution_record_id == original_resolution_id


# ── 422: validation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_validation_errors(async_client, org_and_key, db_session):
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Missing decision.
    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={"reviewer_role": "attending_physician", "reviewer_id": "dr_smith"},
        headers=headers,
    )
    assert r.status_code == 422

    # Decision typo.
    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "maybe",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers=headers,
    )
    assert r.status_code == 422

    # Empty reviewer_role (min_length=1).
    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "",
            "reviewer_id": "dr_smith",
        },
        headers=headers,
    )
    assert r.status_code == 422

    # Oversize note.
    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
            "note": "x" * 3000,
        },
        headers=headers,
    )
    assert r.status_code == 422


# ── Multi-approver: A5 column wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_pending_after_first_of_two_does_not_set_decided_at(
    async_client, org_and_key, db_session
):
    """approvers_required=2 + first sufficient vote → approval still
    pending. ``callback_received_at`` IS set (the callback arrived) but
    ``decided_at`` is NOT (the row hasn't reached a terminal state)."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(
        db_session, org.id, approvers_required=2
    )

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_first",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["callback_received_at"] is not None
    assert body["decided_at"] is None  # not terminal yet
    assert body["reviewed_below_threshold"] is False


# ── Webhook emission ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_emits_review_completed_webhook(
    async_client, org_and_key, db_session, monkeypatch
):
    """Sufficient-role completion triggers ``review.completed`` (and the
    legacy ``approval.resolved``) — verify a WebhookDelivery row was
    created for each event the org is subscribed to.

    The actual HTTP POST is patched to a no-op so we don't depend on a
    network reachable httpbin.
    """
    org, raw_key, _ = org_and_key

    # Subscribe to review.completed.
    sub = WebhookSubscription(
        org_id=org.id,
        url="http://test.example/webhook",
        event_types=["review.completed", "approval.resolved"],
        secret="whsec_test",
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()

    # Stub the network attempt so we don't make a real outbound call.
    import app.services.webhooks as webhooks_mod

    async def _noop_attempt(*args, **kwargs):
        return None

    monkeypatch.setattr(webhooks_mod, "_attempt_delivery", _noop_attempt)

    approval = await _seed_hitl_approval(db_session, org.id)
    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text

    rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.org_id == org.id,
                WebhookDelivery.event_type.in_(
                    ["review.completed", "approval.resolved"]
                ),
            )
        )
    ).scalars().all()
    event_types = {r.event_type for r in rows}
    assert "review.completed" in event_types
    assert "approval.resolved" in event_types
