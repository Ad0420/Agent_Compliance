"""Sweeper-side helper that resolves expired approvals + emits review.expired.

Wave 2B PR A3 design notes
==========================

* **Why a sweeper-driven path?** Today's ``approvals.py`` only resolves
  expired rows on read (``get_approval_with_lazy_expiry``). With
  ``review.expired`` now a customer-facing webhook event, expiry must
  fire as a *producer-side* event whether or not anyone is reading.
* **Chain implications.** Per plan §6, sweeper-driven expiry MUST write
  the same ``human_approval_resolved`` ActionRecord as the lazy path
  via ``_resolve_and_record`` — the chain is source of truth for every
  approval state transition and skipping creates a regulator-visible
  gap.
* **Per-org concurrency.** ``_resolve_and_record`` calls
  ``build_and_insert_record`` which acquires the in-process org lock,
  so expiry never interleaves with action inserts.
* **Idempotency.** ``_resolve_and_record`` is keyed on the approval
  row's status transition (``pending → expired``); the SELECT filter
  ``status='pending'`` ensures we never re-process a row.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval

if TYPE_CHECKING:  # pragma: no cover
    pass


logger = logging.getLogger("vera.approval_expiry")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_postgres(session: AsyncSession) -> bool:
    url = str(session.bind.url) if session.bind else ""
    return url.startswith("postgresql")


async def sweep_expired_approvals(
    session: AsyncSession, *, batch_size: int = 20
) -> int:
    """Resolve at most ``batch_size`` ``pending`` approvals past their deadline.

    Returns the number of rows resolved. Each row goes through
    ``approvals._resolve_and_record(approval, 'expired')`` which:
      1. Writes a ``human_approval_resolved`` ActionRecord (failure)
         to the chain.
      2. Flips the row to ``expired`` + sets ``resolved_at``,
         ``resolution_record_id``.
      3. Fires ``approval.resolved`` and ``review.expired`` webhooks
         (via the dual-emission patch in ``approvals.py``).
    """
    # Lazy import to break the cycle: approvals.py imports webhooks.py,
    # which imports webhook_sweeper.py, which imports this module.
    from .approvals import _resolve_and_record

    now = _now()
    stmt = (
        select(Approval)
        .where(Approval.status == "pending")
        .where(Approval.expires_at.is_not(None))
        .where(Approval.expires_at <= now)
        .order_by(Approval.expires_at)
        .limit(batch_size)
    )
    if _is_postgres(session):
        stmt = stmt.with_for_update(skip_locked=True)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return 0

    resolved = 0
    for approval in rows:
        try:
            # A6.5: _resolve_and_record no longer commits on its own.
            # Commit per-row so a failure on one expired approval does
            # not roll back the rest of the batch (preserves the
            # pre-refactor "best-effort batch" semantics + idempotency:
            # next sweeper tick re-tries any row left pending).
            await _resolve_and_record(session, approval, "expired")
            await session.commit()
            await session.refresh(approval)
            resolved += 1
        except Exception:
            logger.exception(
                "failed to expire approval=%s org=%s; will retry next tick",
                approval.id,
                approval.org_id,
            )
            # Drop the failed-row writes so the next iteration starts
            # from a clean session state.
            try:
                await session.rollback()
            except Exception:
                logger.exception(
                    "rollback after failed expiry also failed; "
                    "session may be in an unrecoverable state"
                )
    if resolved:
        logger.info("approval expiry sweep resolved %s rows", resolved)
    return resolved
