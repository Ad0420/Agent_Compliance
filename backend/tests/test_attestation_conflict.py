"""Phase 2 Wave 2D PR A6 — attestation-conflict + concurrent-callback safety.

Closes the ``v1-test-plan.md`` Phase 2 "Attestation conflict (second
callback different decision)" and "Concurrent callbacks race" gap rows.

Coverage:
* Idempotent second callback (same decision) — no new chain record, no
  new webhook event, original row returned untouched.
* Conflicting second callback (approved → reject) — 409
  ``attestation_conflict`` envelope, chain ``ActionRecord``,
  ``attestation_conflict`` webhook delivery row, canonical status
  preserved.
* Reverse conflict (rejected → approve) — same wiring, opposite arrow.
* Conflict payload captures BOTH attestations (canonical + conflicting)
  with reviewer_id, decision, decided_at.
* Conflict carries ``conflict_detected_at`` timestamp.
* Multiple consecutive conflicts log multiple chain records (auditors
  see the full series).
* Expired-then-callback stays a 410 (not a conflict — PR A6 should NOT
  regress PR A4's expiry semantics).
* Cancelled-then-callback stays a 409 ``cancelled`` (not a conflict).
* Concurrent same-decision race via ``asyncio.gather`` → both return
  200, exactly one chain resolution record exists.
* Concurrent different-decision race via ``asyncio.gather`` → exactly
  one 200 + exactly one 409, chain captures the loser.
* Conflicting callback does NOT flip the canonical Approval status.
* Conflicting callback does NOT consume / overwrite the canonical
  ``resolution_record_id``.

Implementation reference: ``backend/app/services/reviews.py``
``_handle_second_callback`` / ``_log_attestation_conflict``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import (
    ActionRecord,
    Approval,
    WebhookDelivery,
    WebhookSubscription,
)
from app.schemas.approval import ApprovalCreate
from app.services.approvals import (
    _resolve_and_record,
    cancel_approval,
    request_approval,
)


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
    """Materialise an Approval shaped like A2's gate materializer would."""
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


async def _resolve_via_callback(
    async_client,
    raw_key: str,
    review_id: str,
    *,
    decision: str = "approve",
    reviewer_id: str = "dr_first",
    reviewer_role: str = "attending_physician",
    note: str | None = None,
) -> None:
    """Helper: drive the first attestation through the callback endpoint."""
    body: dict = {
        "decision": decision,
        "reviewer_role": reviewer_role,
        "reviewer_id": reviewer_id,
    }
    if note is not None:
        body["note"] = note
    r = await async_client.post(
        f"/v1/reviews/{review_id}/complete",
        json=body,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200, r.text


# ── Idempotent second callback ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_callback_same_decision_is_idempotent(
    async_client, org_and_key, db_session
):
    """Two approve callbacks → second returns 200 with no new chain record
    and no new webhook delivery for ``attestation_conflict``."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    await _resolve_via_callback(async_client, raw_key, approval.id)

    # Snapshot pre-existing chain + delivery counts so the assertions
    # measure the *delta* caused by the second callback.
    pre_chain_rows = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.org_id == org.id)
        )
    ).scalars().all()
    pre_conflict_count = sum(
        1 for r in pre_chain_rows if r.action_type == "attestation_conflict"
    )

    r2 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_second",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "approved"
    # Canonical (first) reviewer is preserved — the second reviewer's
    # vote is NOT appended.
    assert len(body["decisions"]) == 1
    assert "dr_first" in body["decisions"][0]["approver"]

    post_chain_rows = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.org_id == org.id)
        )
    ).scalars().all()
    post_conflict_count = sum(
        1 for r in post_chain_rows if r.action_type == "attestation_conflict"
    )
    assert post_conflict_count == pre_conflict_count == 0
    # No NEW chain records of any kind for the idempotent path.
    assert len(post_chain_rows) == len(pre_chain_rows)


# ── Conflicting second callback ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_callback_conflicting_decision_returns_409_envelope(
    async_client, org_and_key, db_session
):
    """approve → reject: 409 with the flat ``attestation_conflict`` envelope."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(async_client, raw_key, approval.id)

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_second",
            "note": "I disagree.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "attestation_conflict"
    assert body["review_id"] == approval.id
    assert body["canonical_decision"] == "approve"
    assert body["conflicting_decision"] == "reject"

    # Canonical status MUST NOT flip.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "approved"


@pytest.mark.asyncio
async def test_second_callback_reject_then_approve_conflicts(
    async_client, org_and_key, db_session
):
    """Reverse arrow: reject → approve also yields a 409 + chain record."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(
        async_client, raw_key, approval.id, decision="reject"
    )

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_second",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["canonical_decision"] == "reject"
    assert body["conflicting_decision"] == "approve"

    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "rejected"


@pytest.mark.asyncio
async def test_conflict_writes_chain_record_with_both_attestations(
    async_client, org_and_key, db_session
):
    """Chain record carries reviewer_id / decision / decided_at for BOTH
    attestations — auditors must be able to reconstruct who said what."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(
        async_client,
        raw_key,
        approval.id,
        reviewer_id="dr_canonical",
        note="Approve — chart confirms.",
    )

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_conflict",
            "note": "Reject — second look disagrees.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409

    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    rec = rows[0]
    assert rec.result == "failure"

    reasoning = rec.reasoning
    assert reasoning["canonical_decision"] == "approve"
    assert reasoning["conflicting_decision"] == "reject"
    assert "conflict_detected_at" in reasoning

    canonical = reasoning["canonical_attestation"]
    assert canonical["decision"] == "approve"
    # ``approver`` carries the ``reviewer_id:reviewer_role`` composite
    # the canonical path records.
    assert canonical["approver"] is not None
    assert "dr_canonical" in canonical["approver"]
    assert canonical["decided_at"] is not None

    conflicting = reasoning["conflicting_attestation"]
    assert conflicting["decision"] == "reject"
    assert conflicting["reviewer_id"] == "dr_conflict"
    assert conflicting["reviewer_role"] == "attending_physician"
    assert conflicting["decided_at"] is not None
    assert conflicting["note"] == "Reject — second look disagrees."

    # Chain record's input_data references the original review.
    assert rec.input_data["review_id"] == approval.id


@pytest.mark.asyncio
async def test_conflict_dispatches_attestation_conflict_webhook(
    async_client, org_and_key, db_session, monkeypatch
):
    """Subscribers to ``attestation_conflict`` receive a delivery row.

    The actual HTTP POST is stubbed out so the test doesn't depend on
    an outbound httpbin.
    """
    org, raw_key, _ = org_and_key

    sub = WebhookSubscription(
        org_id=org.id,
        url="http://test.example/webhook",
        event_types=["attestation_conflict"],
        secret="whsec_test",
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()

    import app.services.webhooks as webhooks_mod

    async def _noop_attempt(*args, **kwargs):
        return None

    monkeypatch.setattr(webhooks_mod, "_attempt_delivery", _noop_attempt)

    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(async_client, raw_key, approval.id)

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_conflict",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409

    deliveries = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.org_id == org.id,
                WebhookDelivery.event_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(deliveries) == 1
    payload = deliveries[0].payload
    assert payload["review_id"] == approval.id
    assert payload["canonical_decision"] == "approve"
    assert payload["conflicting_decision"] == "reject"
    assert "canonical_attestation" in payload
    assert "conflicting_attestation" in payload
    assert "conflict_detected_at" in payload


@pytest.mark.asyncio
async def test_multiple_conflicting_callbacks_log_separate_chain_records(
    async_client, org_and_key, db_session
):
    """Three reject callbacks against an approved review → three
    ``attestation_conflict`` chain records. Auditors see the full
    history of disagreement, not just the first one."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(async_client, raw_key, approval.id)

    for i in range(3):
        r = await async_client.post(
            f"/v1/reviews/{approval.id}/complete",
            json={
                "decision": "reject",
                "reviewer_role": "attending_physician",
                "reviewer_id": f"dr_conflict_{i}",
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert r.status_code == 409

    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(rows) == 3
    reviewer_ids = {
        r.reasoning["conflicting_attestation"]["reviewer_id"] for r in rows
    }
    assert reviewer_ids == {"dr_conflict_0", "dr_conflict_1", "dr_conflict_2"}


@pytest.mark.asyncio
async def test_conflict_preserves_canonical_resolution_record_id(
    async_client, org_and_key, db_session
):
    """A conflict must NOT overwrite the original ``resolution_record_id``
    — the canonical attestation chain row stays the source of truth for
    the approval's outcome."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(async_client, raw_key, approval.id)

    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    canonical_resolution_id = refreshed.resolution_record_id
    assert canonical_resolution_id is not None

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_conflict",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409

    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.resolution_record_id == canonical_resolution_id


# ── PR A4 regression guards: expired / cancelled stay non-conflict ─────────


@pytest.mark.asyncio
async def test_expired_review_is_not_treated_as_attestation_conflict(
    async_client, org_and_key, db_session
):
    """A callback on an ``expired`` row must surface as 410, NOT as an
    attestation conflict — PR A6 must not regress PR A4's expiry path.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(
        db_session, org.id, expires_in_seconds=60
    )
    # Sweeper path: row is already terminal-state expired. A6.5:
    # _resolve_and_record no longer commits — caller owns the boundary.
    await _resolve_and_record(db_session, approval, "expired")
    await db_session.commit()
    await db_session.refresh(approval)

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_late",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 410
    assert "expired" in r.json()["detail"].lower()

    # No attestation_conflict chain record was written.
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_cancelled_review_is_not_treated_as_attestation_conflict(
    async_client, org_and_key, db_session
):
    """A callback on a ``cancelled`` row stays a generic 409 — there was
    never a canonical attestation, so the conflict concept doesn't
    apply."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    await cancel_approval(db_session, org.id, approval.id, "admin")

    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_late",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 409
    # PR A4's "already cancelled" message — NOT the conflict envelope.
    body = r.json()
    assert body.get("code") != "attestation_conflict"
    assert "cancelled" in body["detail"].lower()

    # No attestation_conflict chain record.
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert rows == []


# ── Concurrent-callback race ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_callbacks_same_decision_resolve_exactly_once(
    async_client, org_and_key, db_session
):
    """Two parallel approve callbacks → both return 200, exactly one
    chain ``human_approval_resolved`` record exists, no conflict logged.

    SQLite is single-threaded so this exercises the second-callback
    idempotent branch. On Postgres the row lock would serialise the two
    transactions and produce the same observable outcome.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    body = {
        "decision": "approve",
        "reviewer_role": "attending_physician",
        "reviewer_id": "dr_race",
    }
    headers = {"Authorization": f"Bearer {raw_key}"}

    r1, r2 = await asyncio.gather(
        async_client.post(
            f"/v1/reviews/{approval.id}/complete", json=body, headers=headers
        ),
        async_client.post(
            f"/v1/reviews/{approval.id}/complete",
            json={**body, "reviewer_id": "dr_race_2"},
            headers=headers,
        ),
    )
    assert {r1.status_code, r2.status_code} == {200}, (
        r1.status_code,
        r1.text,
        r2.status_code,
        r2.text,
    )

    # Exactly one resolution record — the second callback was idempotent.
    resolution_rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "human_approval_resolved",
            )
        )
    ).scalars().all()
    assert len(resolution_rows) == 1

    # No conflict was logged.
    conflict_rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert conflict_rows == []


# ── /review-driven hardening (Codex #6, #8, #9) ────────────────────────────


@pytest.mark.asyncio
async def test_complete_review_rejects_non_uuid_path_segment(
    async_client, org_and_key
):
    """Codex #8: validate the ``review_id`` path segment is a UUID
    BEFORE allocating a per-review asyncio lock keyed by it. Without
    this guard, any caller with a valid write key could grow the
    unbounded ``_review_locks`` dict in every worker by POSTing
    arbitrary path strings — a slow memory-DoS vector.
    """
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/reviews/not-a-uuid/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # Returned BEFORE the lock allocation; the body shape matches the
    # legitimate "no such review" 404 since both surface as
    # "review not found" from the caller's perspective.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_multi_approver_canonical_attestation_matches_terminal_decision(
    async_client, org_and_key, db_session
):
    """Codex #6: in a 2-of-N approve gate where reviewer A approves
    (pending) then reviewer B rejects (status flips to rejected), the
    conflict record's ``canonical_attestation`` MUST be the vote whose
    decision matches the terminal status (``reject``), not
    ``decisions[0]`` (which is reviewer A's earlier ``approve``).
    Otherwise the chain record would be self-contradictory:
    ``canonical_decision="reject"`` paired with
    ``canonical_attestation.decision="approve"``.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(
        db_session, org.id, approvers_required=2
    )
    headers = {"Authorization": f"Bearer {raw_key}"}

    # First vote: approve (stays pending — 1 of 2).
    r1 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_first_approves",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "pending"

    # Second vote: reject (terminates — status flips to rejected).
    r2 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_second_rejects",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "rejected"

    # Third callback: approve — conflicts with canonical decision "reject".
    r3 = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_third_approves",
        },
        headers=headers,
    )
    assert r3.status_code == 409
    assert r3.json()["canonical_decision"] == "reject"

    # The chain record's canonical_attestation must point at the reject
    # vote (dr_second_rejects), NOT decisions[0] (dr_first_approves).
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    canonical = rows[0].reasoning["canonical_attestation"]
    assert canonical["decision"] == "reject"
    assert "dr_second_rejects" in canonical["approver"]


@pytest.mark.asyncio
async def test_repeated_conflict_from_same_reviewer_dedupes_webhook(
    async_client, org_and_key, db_session, monkeypatch
):
    """Codex #9: client-side retry of the same conflicting callback
    (same reviewer_id + same decision) must NOT spawn a fresh webhook
    delivery on every attempt. The chain record is still written each
    time (every attempt is a distinct audit event), but the webhook
    layer dedupes via the explicit idempotency key
    ``{review_id}:{reviewer_id}:{decision}:attestation_conflict``.
    """
    org, raw_key, _ = org_and_key

    sub = WebhookSubscription(
        org_id=org.id,
        url="http://test.example/webhook",
        event_types=["attestation_conflict"],
        secret="whsec_test",
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()

    import app.services.webhooks as webhooks_mod

    async def _noop_attempt(*args, **kwargs):
        return None

    monkeypatch.setattr(webhooks_mod, "_attempt_delivery", _noop_attempt)

    approval = await _seed_hitl_approval(db_session, org.id)
    await _resolve_via_callback(async_client, raw_key, approval.id)

    conflict_body = {
        "decision": "reject",
        "reviewer_role": "attending_physician",
        "reviewer_id": "dr_retry",
    }
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Three consecutive retries from the SAME reviewer.
    for _ in range(3):
        r = await async_client.post(
            f"/v1/reviews/{approval.id}/complete",
            json=conflict_body,
            headers=headers,
        )
        assert r.status_code == 409

    deliveries = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.org_id == org.id,
                WebhookDelivery.event_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    # Exactly one delivery for the same-reviewer retries.
    assert len(deliveries) == 1

    # A DISTINCT reviewer with a conflicting decision DOES get its own
    # delivery — the dedup is scoped per-reviewer, not per-review.
    r = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "reject",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_other_dissenter",
        },
        headers=headers,
    )
    assert r.status_code == 409

    deliveries = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.org_id == org.id,
                WebhookDelivery.event_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(deliveries) == 2


@pytest.mark.asyncio
async def test_concurrent_callbacks_different_decisions_produce_conflict(
    async_client, org_and_key, db_session
):
    """Two parallel callbacks with opposing decisions → exactly one 200
    + exactly one 409. The loser's attempt is captured as a chain
    ``attestation_conflict`` record."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)
    headers = {"Authorization": f"Bearer {raw_key}"}

    r1, r2 = await asyncio.gather(
        async_client.post(
            f"/v1/reviews/{approval.id}/complete",
            json={
                "decision": "approve",
                "reviewer_role": "attending_physician",
                "reviewer_id": "dr_yes",
            },
            headers=headers,
        ),
        async_client.post(
            f"/v1/reviews/{approval.id}/complete",
            json={
                "decision": "reject",
                "reviewer_role": "attending_physician",
                "reviewer_id": "dr_no",
            },
            headers=headers,
        ),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], (r1.status_code, r1.text, r2.status_code, r2.text)

    # Exactly one canonical resolution + exactly one conflict record.
    resolution_rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "human_approval_resolved",
            )
        )
    ).scalars().all()
    assert len(resolution_rows) == 1

    conflict_rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "attestation_conflict",
            )
        )
    ).scalars().all()
    assert len(conflict_rows) == 1

    # The 409 body identifies the canonical winner.
    conflict_response = r1 if r1.status_code == 409 else r2
    body = conflict_response.json()
    assert body["code"] == "attestation_conflict"
    assert body["canonical_decision"] in {"approve", "reject"}
    assert body["conflicting_decision"] in {"approve", "reject"}
    assert body["canonical_decision"] != body["conflicting_decision"]
