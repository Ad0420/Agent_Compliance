"""Sweeper claim + tick tests for ``app/services/webhook_sweeper.py``.

These tests exercise the row-claim filter and the integration tick
without spinning the background loop (no ``start_in_process``). The
``_patch_async_session_local_for_webhooks`` autouse fixture in
``conftest.py`` ensures bookkeeping sessions land on the in-memory
test engine.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import WebhookDelivery, WebhookSubscription
from app.services.webhook_sweeper import (
    SWEEPER_LEASE_SECONDS,
    _claim_due_deliveries,
    tick,
)
from app.services.webhook_retry import MAX_ATTEMPTS


def _ok_mock_client():
    response = MagicMock()
    response.status_code = 200
    response.content = b""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


def _err_mock_client(status_code: int = 500):
    response = MagicMock()
    response.status_code = status_code
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


async def _make_subscription(session, org_id):
    sub = WebhookSubscription(
        org_id=org_id,
        url="https://hooks.example.com/sweeper",
        secret="s",
        event_types=["policy.violation"],
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def _make_pending_delivery(
    session,
    *,
    sub: WebhookSubscription,
    org_id: str,
    next_retry_at: datetime,
    status: str = "pending",
    locked_until: datetime | None = None,
    attempt_count: int = 0,
) -> str:
    delivery = WebhookDelivery(
        subscription_id=sub.id,
        org_id=org_id,
        event_type="policy.violation",
        payload={"hello": "world"},
        status=status,
        attempt_count=attempt_count,
        next_retry_at=next_retry_at,
        locked_until=locked_until,
        idempotency_key=f"sweeper-{next_retry_at.isoformat()}-{status}-{attempt_count}",
    )
    session.add(delivery)
    await session.commit()
    await session.refresh(delivery)
    return delivery.id


# ── _claim_due_deliveries: pending-row selection ──────────────────────────


@pytest.mark.asyncio
async def test_claim_due_picks_pending_rows_past_next_retry(db_session, org_and_key):
    """A pending row with ``next_retry_at <= now`` gets claimed."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    overdue_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now - timedelta(seconds=10)
    )
    # Future row stays untouched.
    future_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now + timedelta(hours=1)
    )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=50)
    assert overdue_id in claimed
    assert future_id not in claimed


@pytest.mark.asyncio
async def test_claim_due_respects_active_lease(db_session, org_and_key):
    """A pending row with a live lease (locked_until > now) is NOT claimed."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    leased_id = await _make_pending_delivery(
        db_session,
        sub=sub,
        org_id=org.id,
        next_retry_at=now - timedelta(seconds=10),
        locked_until=now + timedelta(seconds=120),
    )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=50)
    assert leased_id not in claimed


@pytest.mark.asyncio
async def test_claim_due_reclaims_expired_lease_in_progress(db_session, org_and_key):
    """A crashed-mid-attempt row (in_progress + lease expired) is reclaimed."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    stale_id = await _make_pending_delivery(
        db_session,
        sub=sub,
        org_id=org.id,
        next_retry_at=now - timedelta(seconds=10),
        locked_until=now - timedelta(seconds=1),
        status="in_progress",
    )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=50)
    assert stale_id in claimed


@pytest.mark.asyncio
async def test_claim_due_respects_batch_size(db_session, org_and_key):
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    for i in range(5):
        await _make_pending_delivery(
            db_session,
            sub=sub,
            org_id=org.id,
            next_retry_at=now - timedelta(seconds=10 + i),
        )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=3)
    assert len(claimed) == 3


@pytest.mark.asyncio
async def test_claim_due_transitions_to_in_progress_with_lease(
    db_session, org_and_key
):
    """Claimed rows are bumped to in_progress with a fresh lease."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    overdue_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now - timedelta(seconds=10)
    )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=50)
    assert overdue_id in claimed

    row = await db_session.get(WebhookDelivery, overdue_id)
    assert row.status == "in_progress"
    assert row.locked_until is not None
    assert row.locked_until >= now + timedelta(seconds=SWEEPER_LEASE_SECONDS - 1)


@pytest.mark.asyncio
async def test_claim_due_orders_by_next_retry(db_session, org_and_key):
    """Oldest due row claimed first when batch caps mid-list."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0)
    earlier_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now - timedelta(hours=2)
    )
    await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now - timedelta(seconds=10)
    )

    claimed = await _claim_due_deliveries(db_session, now=now, batch_size=1)
    assert claimed == [earlier_id]


# ── tick: success path + retry path ───────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_succeeds_on_2xx(db_session, org_and_key):
    """A pending row whose POST returns 200 is marked succeeded."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0) - timedelta(seconds=10)
    delivery_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now
    )

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_ok_mock_client(),
    ):
        scheduled = await tick()
        await _flush_tasks()

    assert scheduled >= 1
    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "succeeded"
    assert refreshed.attempt_count == 1


@pytest.mark.asyncio
async def test_tick_retries_on_5xx(db_session, org_and_key):
    """5xx leaves the row pending with attempt_count bumped + next_retry_at advanced."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0) - timedelta(seconds=10)
    delivery_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now
    )

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_err_mock_client(503),
    ):
        await tick()
        await _flush_tasks()

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "pending"
    assert refreshed.attempt_count == 1
    assert refreshed.next_retry_at is not None
    assert refreshed.last_status_code == 503


@pytest.mark.asyncio
async def test_tick_aborts_after_max_attempts(db_session, org_and_key):
    """Attempt-7 failure flips status to aborted and emits webhook_delivery_aborted."""
    org, _, _ = org_and_key
    # Subscribe to BOTH the original event AND the abort event so we
    # can assert recursion-guarded abort emission.
    sub = WebhookSubscription(
        org_id=org.id,
        url="https://hooks.example.com/abort",
        secret="s",
        event_types=["policy.violation", "webhook_delivery_aborted"],
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    now = datetime(2026, 5, 24, 12, 0, 0) - timedelta(seconds=10)
    # Seed a delivery already at MAX_ATTEMPTS-1 attempts — one more
    # failure aborts.
    delivery_id = await _make_pending_delivery(
        db_session,
        sub=sub,
        org_id=org.id,
        next_retry_at=now,
        attempt_count=MAX_ATTEMPTS - 1,
    )

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_err_mock_client(500),
    ):
        await tick()
        await _flush_tasks()

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "aborted"
    assert refreshed.attempt_count == MAX_ATTEMPTS
    assert refreshed.next_retry_at is None
    assert refreshed.aborted_at is not None

    # The abort event itself should have been emitted as a NEW delivery
    # row. Recursion guard: an abort delivery never recursively aborts.
    from sqlalchemy import select

    abort_rows = (
        await db_session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.event_type == "webhook_delivery_aborted"
            )
        )
    ).scalars().all()
    assert len(abort_rows) >= 1
    payload = abort_rows[0].payload
    assert payload["original_event_type"] == "policy.violation"
    assert payload["attempts"] == MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_transport_error_counts_as_failure(db_session, org_and_key):
    """A raised exception during POST is treated as a failed attempt."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0) - timedelta(seconds=10)
    delivery_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now
    )

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=RuntimeError("dns failure"))
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=client
    ):
        await tick()
        await _flush_tasks()

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "pending"
    assert refreshed.attempt_count == 1


@pytest.mark.asyncio
async def test_4xx_still_retries(db_session, org_and_key):
    """4xx is treated like any non-2xx — schedule another attempt."""
    org, _, _ = org_and_key
    sub = await _make_subscription(db_session, org.id)
    now = datetime(2026, 5, 24, 12, 0, 0) - timedelta(seconds=10)
    delivery_id = await _make_pending_delivery(
        db_session, sub=sub, org_id=org.id, next_retry_at=now
    )

    with patch(
        "app.services.webhooks.httpx.AsyncClient",
        return_value=_err_mock_client(404),
    ):
        await tick()
        await _flush_tasks()

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "pending"
    assert refreshed.attempt_count == 1
    assert refreshed.last_status_code == 404
