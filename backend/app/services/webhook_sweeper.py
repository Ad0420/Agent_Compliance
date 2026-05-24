"""In-process background sweeper for webhook delivery retries.

Wave 2B PR A3 design notes
==========================

* **In-process asyncio task.** The current architecture has no
  Celery/RQ/dramatiq dependency. Plan §5 documents the
  in-process-now / external-worker-later decision; the schema
  (``status``, ``locked_until``, ``next_retry_at``) is worker-agnostic
  so the swap is a drop-in when scale demands.
* **Lifespan-managed.** ``start_in_process`` is called from
  ``app.main.lifespan`` on startup; ``stop_in_process`` cancels the
  task on shutdown. Disabled via ``VERA_WEBHOOK_SWEEPER_ENABLED=false``
  for tests that don't want time-driven side effects.
* **Race-safe row claim.** Postgres uses ``SELECT … FOR UPDATE SKIP
  LOCKED`` so multiple instances can sweep in parallel without
  double-firing. SQLite (single-instance per the README) uses the
  ``locked_until`` lease.
* **Crash recovery.** Mid-attempt crash leaves a row in ``in_progress``
  with ``locked_until <= now()``. The reclaim filter
  (``status='pending' AND locked_until<=now()`` OR
  ``status='in_progress' AND locked_until<=now()``) re-picks it up.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import WebhookDelivery
from .approval_expiry import sweep_expired_approvals
from .webhooks import _attempt_delivery


logger = logging.getLogger("vera.webhook_sweeper")


# Lease applied when the sweeper claims a row. Generous because the
# ``_attempt_delivery`` HTTP call has its own 5-second timeout but
# bookkeeping after the call can be slow on first-tick cold paths.
SWEEPER_LEASE_SECONDS = 120

# Module-level singleton task handle so re-imports under reload don't
# orphan a second sweeper.
_sweeper_task: Optional[asyncio.Task] = None
# Distinct UUID per process so log lines + ``locked_by`` rows are
# attributable when (eventually) multiple instances run.
_INSTANCE_ID: str = str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_postgres(session: AsyncSession) -> bool:
    url = str(session.bind.url) if session.bind else ""
    return url.startswith("postgresql")


async def _claim_due_deliveries(
    session: AsyncSession,
    *,
    now: datetime,
    batch_size: int,
) -> list[str]:
    """Claim up to ``batch_size`` due deliveries.

    Returns the IDs of claimed rows. Each row is transitioned to
    ``status='in_progress'`` with a fresh lease before the function
    returns, so the caller is safe to schedule attempts without holding
    the session.
    """
    # The filter:
    #   - pending AND next_retry_at <= now AND lease expired
    #   - OR in_progress AND lease expired  (crash recovery)
    base_filter = or_(
        (WebhookDelivery.status == "pending")
        & (WebhookDelivery.next_retry_at <= now)
        & (
            (WebhookDelivery.locked_until.is_(None))
            | (WebhookDelivery.locked_until <= now)
        ),
        (WebhookDelivery.status == "in_progress")
        & (
            (WebhookDelivery.locked_until.is_(None))
            | (WebhookDelivery.locked_until <= now)
        ),
    )

    stmt = (
        select(WebhookDelivery)
        .where(base_filter)
        .order_by(WebhookDelivery.next_retry_at)
        .limit(batch_size)
    )
    if _is_postgres(session):
        stmt = stmt.with_for_update(skip_locked=True)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    claimed: list[str] = []
    new_lease_until = now + timedelta(seconds=SWEEPER_LEASE_SECONDS)
    for row in rows:
        row.status = "in_progress"
        row.locked_until = new_lease_until
        row.locked_by = _INSTANCE_ID
        claimed.append(row.id)

    await session.commit()
    return claimed


async def tick() -> int:
    """One sweeper pass. Returns the number of deliveries scheduled.

    Also runs the approval-expiry pass on the same tick (cheap; bounded
    by ``settings.approval_expiry_batch_size``).
    """
    scheduled = 0

    # Approval expiry first: lazy expiry already covers reads, but
    # webhooks need a writer-driven path for ``review.expired``.
    try:
        async with AsyncSessionLocal() as session:
            await sweep_expired_approvals(
                session, batch_size=settings.approval_expiry_batch_size
            )
    except Exception:
        logger.exception("approval-expiry sweep failed; continuing")

    try:
        async with AsyncSessionLocal() as session:
            ids = await _claim_due_deliveries(
                session,
                now=_now(),
                batch_size=settings.webhook_sweeper_batch_size,
            )
    except Exception:
        logger.exception("delivery claim query failed; skipping tick")
        return 0

    for delivery_id in ids:
        asyncio.create_task(_attempt_delivery(delivery_id))
        scheduled += 1

    if scheduled:
        logger.info("webhook sweeper scheduled %s deliveries", scheduled)
    return scheduled


async def _run_forever(stop_event: asyncio.Event) -> None:
    """Inner loop. Sleeps ``tick_seconds`` between passes."""
    interval = max(1, int(settings.webhook_sweeper_tick_seconds))
    logger.info(
        "webhook sweeper started: instance=%s tick=%ss batch=%s",
        _INSTANCE_ID,
        interval,
        settings.webhook_sweeper_batch_size,
    )
    while not stop_event.is_set():
        try:
            await tick()
        except Exception:
            logger.exception("webhook sweeper tick raised — continuing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("webhook sweeper stopped: instance=%s", _INSTANCE_ID)


_stop_event: Optional[asyncio.Event] = None


def start_in_process() -> Optional[asyncio.Task]:
    """Start the sweeper as a background asyncio task.

    No-op when ``settings.webhook_sweeper_enabled`` is false. Idempotent
    — calling twice returns the existing task.
    """
    global _sweeper_task, _stop_event
    if not settings.webhook_sweeper_enabled:
        logger.info("webhook sweeper disabled by config")
        return None
    if _sweeper_task is not None and not _sweeper_task.done():
        return _sweeper_task
    _stop_event = asyncio.Event()
    _sweeper_task = asyncio.create_task(
        _run_forever(_stop_event), name="vera-webhook-sweeper"
    )
    return _sweeper_task


async def stop_in_process() -> None:
    """Signal the sweeper to exit and await its cancellation."""
    global _sweeper_task, _stop_event
    if _sweeper_task is None:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        await asyncio.wait_for(_sweeper_task, timeout=5.0)
    except asyncio.TimeoutError:
        _sweeper_task.cancel()
        try:
            await _sweeper_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    finally:
        _sweeper_task = None
        _stop_event = None
