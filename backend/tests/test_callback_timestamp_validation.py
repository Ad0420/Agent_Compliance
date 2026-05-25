"""Phase 2 Wave 2D closeout — callback ``decided_at`` validation.

Covers the v1-test-plan.md "Callback timestamp validation" row:

* ``decided_at`` more than the clock-skew tolerance in the future →
  400 ``decided_at_in_future``.
* ``decided_at`` strictly older than ``requested_at`` →
  400 ``decided_at_before_requested_at``.
* ``decided_at`` past ``expires_at`` → 400 ``review_expired``.
* Happy path: a sensible client-supplied ``decided_at`` lands on the
  row (overrides the server's ``_now()`` for the row-level column;
  ``callback_received_at`` still tracks server clock).
* Omitting ``decided_at`` falls through to PR A4's legacy behaviour
  (server fills with ``_now()``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Approval
from app.schemas.approval import ApprovalCreate
from app.services.approvals import request_approval


async def _seed_hitl_approval(
    db_session,
    org_id: str,
    *,
    expires_in_seconds: int | None = 4 * 60 * 60,
) -> Approval:
    """Materialise a HITL approval mirroring A2's gate materializer."""
    create = ApprovalCreate(
        agent_name="scribemd",
        action_name="add_diagnosis",
        action_summary="Add diagnosis E11.9 for patient_42",
        data_subject_id="patient_42",
        context={
            "gate_name": "new_diagnosis_requires_attending",
            "required_role": "attending_physician",
            "citation": "42 CFR 482.24(c)(4)(viii)",
        },
        risk_tier="high",
        approvers_required=1,
        expires_in_seconds=expires_in_seconds,
    )
    return await request_approval(db_session, org_id, create)


def _iso_naive_utc(dt: datetime) -> str:
    """Render a naive UTC datetime as ISO-8601 without offset.

    Server-side ``decided_at`` is naive UTC by project convention; the
    HTTP wire format that the schema accepts is permissive — pass
    naive ISO-8601 so the round-trip stays straightforward in tests.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


# ── Future-clock rejection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decided_at_two_hours_in_future_is_rejected(
    async_client, org_and_key, db_session
):
    """``decided_at`` 2h ahead of server → 400 ``decided_at_in_future``."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "note": "Patient history confirms diagnosis.",
            "decided_at": _iso_naive_utc(future),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 400, response.text
    # ``main._flatten_dict_detail`` lifts dict ``detail`` payloads to
    # the top level (so SDK ``wrap_httpx_error`` finds ``code`` directly).
    body = response.json()
    assert body["code"] == "decided_at_in_future"
    assert body["review_id"] == approval.id
    assert "skew_tolerance_seconds" in body

    # The row should NOT be resolved — validation runs before any
    # side-effect.
    await db_session.refresh(approval)
    assert approval.status == "pending"
    assert approval.decided_at is None


# ── Pre-request rejection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decided_at_before_requested_at_is_rejected(
    async_client, org_and_key, db_session
):
    """``decided_at`` < ``requested_at`` → 400 ``decided_at_before_requested_at``."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    # 1 day before the approval was requested — physically impossible.
    too_early = approval.requested_at - timedelta(days=1)
    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "decided_at": _iso_naive_utc(too_early),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "decided_at_before_requested_at"
    assert body["review_id"] == approval.id


# ── Past-expiry rejection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decided_at_past_expires_at_is_rejected_with_review_expired(
    async_client, org_and_key, db_session
):
    """``decided_at`` > ``expires_at`` → 400 ``review_expired``.

    Uses a long expiry so the approval itself is still pending (the
    spec wants the 400 to fire on the timestamp, not on the lazy-
    expiry 410). A client trying to back-date a decision into the
    expiry window is the attack surface this guard exists for.
    """
    org, raw_key, _ = org_and_key
    # 1-day expiry so the row is still pending when we POST.
    approval = await _seed_hitl_approval(
        db_session, org.id, expires_in_seconds=24 * 60 * 60
    )

    too_late = approval.expires_at + timedelta(minutes=10)
    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "decided_at": _iso_naive_utc(too_late),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "review_expired"
    assert body["review_id"] == approval.id


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decided_at_within_window_lands_on_row(
    async_client, org_and_key, db_session
):
    """Sensible ``decided_at`` overrides the server clock on the row.

    The reviewer's clock is captured on ``Approval.decided_at`` so
    auditors see the human's timestamp. ``callback_received_at``
    still tracks the server's processing time so both sides of the
    clock are recorded.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    # Pin client clock 1 second after the approval was requested —
    # well inside [requested_at, expires_at] and trivially distinct
    # from the server's ``_now()`` once the request round-trip lands.
    client_decided_at = approval.requested_at + timedelta(seconds=1)

    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
            "decided_at": _iso_naive_utc(client_decided_at),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"

    await db_session.refresh(approval)
    # Row-level decided_at == client value (truncated to ~microsecond
    # via JSON round-trip; assert within 1s).
    assert approval.decided_at is not None
    delta = abs((approval.decided_at - client_decided_at).total_seconds())
    assert delta < 1.0, (
        f"decided_at should track the client clock; "
        f"got {approval.decided_at} vs {client_decided_at}"
    )
    # callback_received_at tracks server wall clock — strictly after
    # the request was issued, NOT equal to the client value.
    assert approval.callback_received_at is not None
    assert approval.callback_received_at > approval.requested_at


# ── Omission preserves legacy behaviour ─────────────────────────────────────


@pytest.mark.asyncio
async def test_decided_at_omitted_falls_back_to_server_now(
    async_client, org_and_key, db_session
):
    """No ``decided_at`` → server fills the row (PR A4 legacy behaviour)."""
    org, raw_key, _ = org_and_key
    approval = await _seed_hitl_approval(db_session, org.id)

    before = datetime.now(timezone.utc).replace(tzinfo=None)
    response = await async_client.post(
        f"/v1/reviews/{approval.id}/complete",
        json={
            "decision": "approve",
            "reviewer_role": "attending_physician",
            "reviewer_id": "dr_smith@hospital.example",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    assert response.status_code == 200, response.text
    await db_session.refresh(approval)
    assert approval.decided_at is not None
    # Server-filled, so it should sit inside [before, after] modulo the
    # request round-trip.
    assert before - timedelta(seconds=1) <= approval.decided_at
    assert approval.decided_at <= after + timedelta(seconds=1)
