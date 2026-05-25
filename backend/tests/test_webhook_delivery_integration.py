"""End-to-end integration tests for the A3 webhook delivery pipeline.

Covers:
  * Happy path: dispatch → 200 → succeeded.
  * Retry path: dispatch → 500 → sweeper tick → 500 → success.
  * Abort path: 7 failures → status=aborted + webhook_delivery_aborted event.
  * Idempotency: double-dispatch of same review event → one delivery row.
  * Back-compat dual emission: approval.requested + review.requested both fire.
  * Admin endpoints: list deliveries + replay.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import (
    APIKey,
    Approval,
    Organization,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.schemas.approval import ApprovalCreate
from app.services.approvals import request_approval
from app.services.webhook_retry import MAX_ATTEMPTS
from app.services.webhook_sweeper import tick
from app.services.webhooks import dispatch_event


def _client_with_responses(*status_codes: int):
    """Return an AsyncMock client whose post() yields the given status sequence.

    The last status repeats forever, so a single trailing 200 means "all
    subsequent attempts succeed".
    """
    responses = []
    for code in status_codes:
        r = MagicMock()
        r.status_code = code
        r.content = b""
        responses.append(r)

    iterator = iter(responses)
    final = responses[-1]

    async def post(*_args, **_kwargs):
        try:
            return next(iterator)
        except StopIteration:
            return final

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=post)
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
        url="https://hooks.example.com/integration",
        secret="topsecret",
        event_types=event_types,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


# ── happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_first_attempt_succeeds(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(db_session, org.id, ["policy.violation"])

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_client_with_responses(200),
    ):
        await dispatch_event(
            db_session, org.id, "policy.violation", {"hello": "world"}
        )
        await _flush_tasks()

    rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.event_type == "policy.violation"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "succeeded"
    assert rows[0].attempt_count == 1

    attempts = (
        await db_session.execute(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == rows[0].id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status_code == 200


# ── retry path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_path_eventually_succeeds(db_session, org_and_key):
    """First attempt 500, second (via sweeper) 200 → succeeded."""
    org, _, _ = org_and_key
    await _make_subscription(db_session, org.id, ["policy.violation"])

    # First attempt fails 500; subsequent succeed.
    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_client_with_responses(500, 200),
    ):
        await dispatch_event(
            db_session, org.id, "policy.violation", {"retry": True}
        )
        await _flush_tasks()

        # Force the delivery to be due immediately.
        rows = (
            await db_session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.event_type == "policy.violation"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        delivery = rows[0]
        assert delivery.status == "pending"
        assert delivery.attempt_count == 1
        delivery.next_retry_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) - timedelta(seconds=10)
        delivery.locked_until = None
        db_session.add(delivery)
        await db_session.commit()

        await tick()
        await _flush_tasks()

    refreshed = await db_session.get(WebhookDelivery, delivery.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "succeeded"
    assert refreshed.attempt_count == 2


# ── abort path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abort_path_after_seven_failures(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        ["policy.violation", "webhook_delivery_aborted"],
    )

    # Always 500.
    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_client_with_responses(500),
    ):
        await dispatch_event(
            db_session, org.id, "policy.violation", {"doom": True}
        )
        await _flush_tasks()

        # Loop ticks until aborted or we've exceeded the schedule depth.
        for _ in range(MAX_ATTEMPTS + 2):
            await db_session.commit()  # flush any in-flight txn
            db_session.expire_all()
            rows = (
                await db_session.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.event_type == "policy.violation"
                    )
                )
            ).scalars().all()
            if rows and rows[0].status == "aborted":
                break
            # Make it immediately due, clear lease.
            for r in rows:
                if r.status == "pending":
                    r.next_retry_at = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    ) - timedelta(seconds=10)
                    r.locked_until = None
            await db_session.commit()
            await tick()
            await _flush_tasks()

    await db_session.commit()
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.event_type == "policy.violation"
            )
        )
    ).scalars().all()
    assert rows[0].status == "aborted"
    assert rows[0].attempt_count == MAX_ATTEMPTS

    # And the abort event itself has a delivery row.
    abort_rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.event_type == "webhook_delivery_aborted"
            )
        )
    ).scalars().all()
    assert len(abort_rows) >= 1


# ── idempotency ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_double_dispatch_review_is_idempotent(db_session, org_and_key):
    """Two ``review.completed`` dispatches with same approval_id → one delivery row."""
    org, _, _ = org_and_key
    await _make_subscription(db_session, org.id, ["review.completed"])

    payload = {
        "review_id": "approval-123",
        "final_status": "approved",
        "decisions": [],
        "resolved_at": "2026-05-24T12:00:00",
        "resolution_record_id": "record-1",
    }
    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_client_with_responses(200),
    ):
        await dispatch_event(db_session, org.id, "review.completed", payload)
        await _flush_tasks()
        await dispatch_event(db_session, org.id, "review.completed", payload)
        await _flush_tasks()

    rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.event_type == "review.completed"
            )
        )
    ).scalars().all()
    assert len(rows) == 1, [
        (r.id, r.idempotency_key, r.status) for r in rows
    ]


# ── dual emission ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dual_emission_request_approval_fires_both_names(
    db_session, org_and_key
):
    """``request_approval`` MUST fire approval.requested + review.requested."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session, org.id, ["approval.requested", "review.requested"]
    )

    mock_client = _client_with_responses(200)
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        await request_approval(
            db_session,
            org.id,
            ApprovalCreate(
                agent_name="loan-bot",
                action_name="approve_loan",
                action_summary="Approve loan",
                data_subject_id="user_z",
                context={"amount": 1},
                risk_tier="high",
                approvers_required=1,
            ),
        )
        await _flush_tasks()

    delivered_events = [
        json.loads(c.kwargs["content"].decode("utf-8"))["event_type"]
        for c in mock_client.post.await_args_list
    ]
    assert "approval.requested" in delivered_events
    assert "review.requested" in delivered_events


# ── admin endpoints ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_and_replay_deliveries(
    async_client, db_session, org_and_key
):
    """GET deliveries + POST replay round-trip."""
    org, raw_key, _ = org_and_key
    sub = await _make_subscription(db_session, org.id, ["policy.violation"])

    # Seed an aborted delivery directly so replay is meaningful.
    aborted = WebhookDelivery(
        subscription_id=sub.id,
        org_id=org.id,
        event_type="policy.violation",
        payload={"seed": True},
        status="aborted",
        attempt_count=MAX_ATTEMPTS,
        next_retry_at=None,
        aborted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        idempotency_key="seed-aborted",
    )
    db_session.add(aborted)
    await db_session.commit()
    await db_session.refresh(aborted)

    resp = await async_client.get(
        f"/v1/webhooks/{sub.id}/deliveries",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(d["id"] == aborted.id for d in body["deliveries"])

    # Replay flips status and fires a fresh attempt.
    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_client_with_responses(200),
    ):
        replay_resp = await async_client.post(
            f"/v1/webhooks/{sub.id}/deliveries/{aborted.id}/replay",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert replay_resp.status_code == 200, replay_resp.text
        replay_body = replay_resp.json()
        # Counter persists (does NOT reset to 0) — the replayed
        # attempts get fresh sequential numbers to avoid colliding with
        # historical rows on the (delivery_id, attempt_number) unique
        # constraint. Seed delivery was MAX_ATTEMPTS, so the next
        # attempt number will be MAX_ATTEMPTS + 1.
        assert replay_body["attempt_count"] == MAX_ATTEMPTS
        assert replay_body["status"] in ("pending", "in_progress", "succeeded")
        await _flush_tasks()
