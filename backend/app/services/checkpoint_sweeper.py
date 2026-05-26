"""In-process background sweeper for per-org checkpoint cadence.

Phase 3 Wave 3A.b — Eng review finding 1D.
==========================================

The implicit "daily KMS-signed checkpoint" requirement from
``v1-implementation-plan.md`` §Phase 3 line 142 turns into a concrete
per-org cadence here: each org's ``checkpoint_cadence`` (``daily`` /
``hourly`` / ``disabled``) controls how often this sweeper triggers a
fresh ``services.checkpoint.create_checkpoint`` call for it.

Why a separate module (not bolted onto ``webhook_sweeper.py``)?
---------------------------------------------------------------

* **Different cadence.** The webhook sweeper ticks every 30s because
  webhook delivery latency matters. The checkpoint sweeper ticks every
  5 minutes by default because the finest cadence threshold is 1h.
* **Different work model.** The webhook sweeper claims due rows from a
  scheduling table. The checkpoint sweeper walks the org table and
  joins against the ``checkpoints`` table to find the per-org most-
  recent checkpoint timestamp.
* **Different failure modes.** A checkpoint creation acquires the
  per-org chain lock and signs with KMS; a partial failure should NOT
  block other orgs (KMS hiccups affect everyone otherwise).

The Phase 2 PR A3 (#215) ``_track_task`` strong-reference pattern
from ``services.webhooks`` is reused verbatim here — the /review found
that a missing strong reference let the GC cancel mid-flight async
tasks. We do NOT regress that fix.

Concurrency safety
------------------

Two concurrent ticks for the *same* org are serialised by
``services.checkpoint.create_checkpoint``'s ``get_org_lock`` (which
``chain.py`` action inserts also hold). So even if the sweeper races
itself, double-checkpointing is impossible — the second call observes
the first call's new row when it computes "is this org due".
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import Checkpoint, Organization
from .checkpoint import create_checkpoint
from .checkpoint_cadence import cadence_threshold

logger = logging.getLogger("vera.checkpoint_sweeper")


# Module-level singleton — re-imports under reload don't orphan a
# second sweeper task.
_sweeper_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_INSTANCE_ID: str = str(uuid.uuid4())

# Strong-reference set for fire-and-forget tasks the sweeper kicks off
# inside a tick. Same pattern as ``services.webhooks._inflight_tasks``
# — without holding a strong ref, Python's GC may cancel the task mid-
# flight (asyncio docs warn about this). This was a Phase 2 PR A3
# /review-caught critical bug; do NOT regress.
_inflight_tasks: set[asyncio.Task] = set()

# Per-org sweeper-side lock. Distinct from ``locks.get_org_lock`` (the
# chain lock that ``create_checkpoint`` itself holds): if we used the
# *same* lock, our hold-across-create_checkpoint would deadlock the
# inner ``async with lock`` inside ``create_checkpoint``. This second
# lock serialises *sweep-tick decisions* (one tick at a time per org
# decides "due → call create_checkpoint"), so two concurrent ticks
# don't both reach the create call.
_sweeper_org_locks: dict[str, asyncio.Lock] = {}
_sweeper_locks_lock = asyncio.Lock()


async def _get_sweeper_org_lock(org_id: str) -> asyncio.Lock:
    async with _sweeper_locks_lock:
        if org_id not in _sweeper_org_locks:
            _sweeper_org_locks[org_id] = asyncio.Lock()
        return _sweeper_org_locks[org_id]


def _track_task(task: asyncio.Task) -> asyncio.Task:
    """Hold a strong reference until the task finishes.

    The done-callback discards the task so the set doesn't grow
    unbounded.
    """
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    return task


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def sweep_due_checkpoints(session: AsyncSession) -> int:
    """For each org whose cadence threshold has elapsed since the last
    checkpoint, trigger a fresh checkpoint.

    Returns the count of checkpoints created on this tick.

    Notes:
    * ``disabled`` orgs are skipped — their ``cadence_threshold()``
      returns ``None`` so the comparison short-circuits before we even
      hit the per-org checkpoint call.
    * Orgs that have never checkpointed (no row in ``checkpoints`` for
      the org_id) are treated as "due immediately". The first sweep
      after this PR ships will create the baseline checkpoint.
    * Soft-deleted orgs (``deleted_at IS NOT NULL``) are skipped — they
      shouldn't accumulate evidence and the per-org lock might collide
      with admin tooling tearing them down.

    The per-org ``services.checkpoint.create_checkpoint`` call already
    holds ``get_org_lock``, so two concurrent ticks racing on the same
    org are serialised at that boundary — exactly one wins, the other
    observes a fresh checkpoint and concludes "not due".
    """
    now = _now()

    # Single LEFT JOIN gets us the per-org latest checkpoint timestamp
    # in one round trip — much cheaper than N+1 selects.
    stmt = (
        select(
            Organization.id,
            Organization.checkpoint_cadence,
            func.max(Checkpoint.created_at).label("last_checkpoint_at"),
        )
        .outerjoin(Checkpoint, Checkpoint.org_id == Organization.id)
        .where(Organization.deleted_at.is_(None))
        .group_by(Organization.id, Organization.checkpoint_cadence)
        .limit(max(1, int(settings.checkpoint_sweeper_batch_size)))
    )
    result = await session.execute(stmt)
    rows = result.all()

    created = 0
    for org_id, cadence, last_checkpoint_at in rows:
        threshold = cadence_threshold(cadence)
        if threshold is None:
            # ``disabled`` or unknown — never auto-create.
            continue

        if last_checkpoint_at is not None:
            elapsed = now - last_checkpoint_at
            if elapsed < threshold:
                continue

        # ── Per-org sweeper lock + double-check + delegate ──────────
        # Two concurrent ticks may BOTH have observed "due" via the
        # LEFT JOIN above (the JOIN is outside any lock). Hold the
        # sweeper-side lock for the *whole* freshness-check +
        # create_checkpoint call: that way, the second tick blocks
        # at the lock; once the first commits a new checkpoint and
        # releases, the second's re-read of the latest timestamp
        # sees the fresh row and skips.
        #
        # We use a sweeper-specific lock (NOT ``locks.get_org_lock``)
        # because ``create_checkpoint`` already acquires that chain
        # lock internally — holding it here too would deadlock the
        # inner ``async with lock`` inside ``create_checkpoint``.
        sweeper_lock = await _get_sweeper_org_lock(org_id)
        async with sweeper_lock:
            fresh_stmt = (
                select(func.max(Checkpoint.created_at))
                .where(Checkpoint.org_id == org_id)
            )
            latest_under_lock = (
                await session.execute(fresh_stmt)
            ).scalar_one_or_none()
            if latest_under_lock is not None:
                elapsed_under_lock = _now() - latest_under_lock
                if elapsed_under_lock < threshold:
                    continue

            try:
                await create_checkpoint(session, org_id)
                created += 1
            except Exception:
                # One bad org must not poison the rest of the tick —
                # the KMS / chain_state / external-store failure paths
                # inside ``create_checkpoint`` are all per-org. Surface
                # the error to ops via the log; the next tick retries.
                logger.exception(
                    "checkpoint creation failed for org %s; continuing",
                    org_id,
                )

    if created:
        logger.info("checkpoint sweeper created %s checkpoints", created)
    return created


async def tick() -> int:
    """One sweeper pass. Opens its own session via
    ``AsyncSessionLocal`` so the sweeper doesn't share a session with
    any request-handling code path. Returns count created.
    """
    try:
        async with AsyncSessionLocal() as session:
            return await sweep_due_checkpoints(session)
    except Exception:
        logger.exception("checkpoint sweeper tick failed; skipping")
        return 0


async def _run_forever(stop_event: asyncio.Event) -> None:
    interval = max(1, int(settings.checkpoint_sweeper_tick_seconds))
    logger.info(
        "checkpoint sweeper started: instance=%s tick=%ss batch=%s",
        _INSTANCE_ID,
        interval,
        settings.checkpoint_sweeper_batch_size,
    )
    while not stop_event.is_set():
        try:
            # Wrap tick so we can keep its task strongly referenced.
            # ``tick`` itself is awaited (not fire-and-forget) so the
            # strong-ref set is mostly a safety net here — but we use
            # the same machinery the webhook sweeper uses so future
            # parallel tick logic Just Works.
            task = asyncio.create_task(tick(), name="vera-checkpoint-tick")
            _track_task(task)
            await task
        except Exception:
            logger.exception(
                "checkpoint sweeper tick raised — continuing"
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("checkpoint sweeper stopped: instance=%s", _INSTANCE_ID)


def start_in_process() -> Optional[asyncio.Task]:
    """Start the sweeper as a background asyncio task.

    No-op when ``settings.checkpoint_sweeper_enabled`` is false.
    Idempotent — calling twice returns the existing task.
    """
    global _sweeper_task, _stop_event
    if not settings.checkpoint_sweeper_enabled:
        logger.info("checkpoint sweeper disabled by config")
        return None
    if _sweeper_task is not None and not _sweeper_task.done():
        return _sweeper_task
    _stop_event = asyncio.Event()
    _sweeper_task = asyncio.create_task(
        _run_forever(_stop_event), name="vera-checkpoint-sweeper"
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
