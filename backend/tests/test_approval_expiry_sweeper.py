"""Approval-expiry sweeper tests — ``app/services/approval_expiry.py``.

Verifies that ``sweep_expired_approvals``:
  * Resolves pending approvals past ``expires_at``.
  * Writes a chain ActionRecord (``human_approval_resolved`` /
    ``result='failure'`` / ``reasoning.final_status='expired'``).
  * Fires both ``approval.resolved`` and ``review.expired`` webhooks
    via the dual-emission patch in ``services/approvals.py``.
  * Is idempotent — re-running after expiry sees no pending rows.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import ActionRecord, Approval, WebhookSubscription
from app.schemas.approval import ApprovalCreate
from app.services.approvals import request_approval
from app.services.approval_expiry import sweep_expired_approvals


def _ok_mock_client():
    response = MagicMock()
    response.status_code = 200
    response.content = b""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


async def _flush_tasks():
    for _ in range(100):
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return
        await asyncio.wait(
            pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED
        )


async def _make_subscription(session, org_id, event_types):
    sub = WebhookSubscription(
        org_id=org_id,
        url="https://hooks.example.com/expiry",
        secret="s",
        event_types=event_types,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def _make_pending_expired_approval(
    db_session, org_id, *, expires_at_offset_seconds: int = -10
) -> Approval:
    """Create a pending approval whose ``expires_at`` is already past."""
    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        approval = await request_approval(
            db_session,
            org_id,
            ApprovalCreate(
                agent_name="loan-bot",
                action_name="approve_loan",
                action_summary="Approve loan",
                data_subject_id="user_x",
                context={"amount": 100},
                risk_tier="high",
                approvers_required=1,
                expires_in_seconds=1,  # request_approval requires a positive value
            ),
        )
        await _flush_tasks()
    # Backdate expires_at past now so the sweeper picks it up.
    approval.expires_at = datetime.now(timezone.utc).replace(
        tzinfo=None
    ) + timedelta(seconds=expires_at_offset_seconds)
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


@pytest.mark.asyncio
async def test_sweep_resolves_expired_pending(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "approval.resolved", "review.requested", "review.expired"],
    )
    approval = await _make_pending_expired_approval(db_session, org.id)

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        n = await sweep_expired_approvals(db_session, batch_size=20)
        await _flush_tasks()

    assert n == 1
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "expired"
    assert refreshed.resolved_at is not None
    assert refreshed.resolution_record_id is not None


@pytest.mark.asyncio
async def test_sweep_writes_chain_record(db_session, org_and_key):
    """Expiry MUST write a ``human_approval_resolved`` ActionRecord."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "approval.resolved", "review.requested", "review.expired"],
    )
    approval = await _make_pending_expired_approval(db_session, org.id)

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        await sweep_expired_approvals(db_session)
        await _flush_tasks()

    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    record = await db_session.get(ActionRecord, refreshed.resolution_record_id)
    assert record is not None
    assert record.action_type == "human_approval_resolved"
    assert record.result == "failure"
    assert record.reasoning.get("final_status") == "expired"


@pytest.mark.asyncio
async def test_sweep_emits_review_expired_event(
    db_engine, db_session, org_and_key
):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "approval.resolved", "review.requested", "review.expired"],
    )
    approval = await _make_pending_expired_approval(db_session, org.id)

    mock = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock
    ):
        await sweep_expired_approvals(db_session)
        await _flush_tasks()

    event_types = [
        json.loads(c.kwargs["content"].decode("utf-8"))["event_type"]
        for c in mock.post.await_args_list
    ]
    assert "review.expired" in event_types
    # Legacy event still fires.
    assert "approval.resolved" in event_types

    # Payload sanity.
    expired_envelopes = [
        json.loads(c.kwargs["content"].decode("utf-8"))
        for c in mock.post.await_args_list
        if json.loads(c.kwargs["content"].decode("utf-8"))["event_type"]
        == "review.expired"
    ]
    assert expired_envelopes
    data = expired_envelopes[0]["data"]
    assert data["review_id"] == approval.id
    assert data["final_status"] == "expired"
    assert data["resolution_record_id"]


@pytest.mark.asyncio
async def test_sweep_leaves_pending_without_expires_at_alone(
    db_session, org_and_key
):
    """An approval with ``expires_at IS NULL`` must not be expired."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "review.requested"],
    )

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        await request_approval(
            db_session,
            org.id,
            ApprovalCreate(
                agent_name="loan-bot",
                action_name="approve_loan",
                action_summary="Approve loan",
                data_subject_id="user_y",
                context={"amount": 1},
                risk_tier="low",
                approvers_required=1,
            ),
        )
        await _flush_tasks()
        n = await sweep_expired_approvals(db_session)

    assert n == 0


@pytest.mark.asyncio
async def test_sweep_is_idempotent(db_session, org_and_key):
    """Two consecutive sweeps yield 1 resolution then 0."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "review.requested", "review.expired"],
    )
    await _make_pending_expired_approval(db_session, org.id)

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        first = await sweep_expired_approvals(db_session)
        await _flush_tasks()
        second = await sweep_expired_approvals(db_session)

    assert first == 1
    assert second == 0


@pytest.mark.asyncio
async def test_sweep_does_not_reprocess_already_expired(
    db_session, org_and_key
):
    """Already-``expired`` rows are never picked up again."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["approval.requested", "review.expired"],
    )
    approval = await _make_pending_expired_approval(db_session, org.id)
    # Pre-flip to expired manually.
    approval.status = "expired"
    db_session.add(approval)
    await db_session.commit()

    n = await sweep_expired_approvals(db_session)
    assert n == 0
