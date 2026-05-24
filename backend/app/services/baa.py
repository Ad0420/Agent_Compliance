"""BAA freshness helper service (Phase 1 PR 4, Stream C item C2).

Centralises the "does this org have an active BAA right now?" check so
both the dashboard create-key endpoint (C1) and the per-request live-key
gate (C2 in ``services.auth.require_permission``) share a single
definition of "active BAA".

Definition of *active BAA*: an ``BAAAgreement`` row scoped to ``org_id``
with ``status='active'``, ``effective_at`` in the past (or NULL — covers
agreements that pre-date a populated effective date), ``expires_at`` in
the future (or NULL — covers indefinite agreements), AND at least one
``BAAScope`` row joined to it. Scope is what makes the BAA usable by the
gate path in Phase 2; an agreement with zero scopes is documented but
unenforceable.

Caching (per Codex E6):
-----------------------
The per-request gate in C2 fires on every authenticated SDK call. A
naive implementation would hit the DB twice (BAA + scope) per request
even though BAA scope changes infrequently (humans signing PDFs). We
cache the boolean per org with a 60 s TTL keyed off ``time.monotonic()``
so:

* Hot path (typical): in-process dict lookup, no DB I/O.
* Revocation propagation: bounded by 60 s. Faster than the typical legal
  team's reaction time but slow enough that a kill-switch flip won't
  let runaway agents continue indefinitely.

The cache is intentionally per-process: there is no Redis dependency in
Phase 1, and each backend replica converges independently within the
TTL. If we ever need synchronous revocation we can add a pub/sub
invalidation hook on the BAA write paths — but that's a Phase 2
consideration.

The cache also stores the *negative* result (no active BAA) so a misconfigured
org doesn't get N DB lookups per request burst. Both polarities use the same
TTL.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BAAAgreement, BAAScope

# TTL in seconds. 60 s matches the Codex E6 freshness budget cited in
# v1-implementation-plan.md Stream C: gates must reflect *current* policy
# state, but per-request DB lookups are wasteful when the underlying
# document changes a few times a year.
_CACHE_TTL_SECONDS = 60.0

# {org_id: (cached_at_monotonic, is_active_bool)}. Module-level so it
# survives across requests within a single uvicorn worker. Wiped on
# process restart — which is fine because the data is purely a
# performance optimisation.
_BAA_FRESHNESS_CACHE: dict[str, tuple[float, bool]] = {}


def _reset_baa_freshness_cache_for_tests() -> None:
    """Test-only: wipe the freshness cache to isolate tests."""
    _BAA_FRESHNESS_CACHE.clear()


def _now_naive_utc() -> datetime:
    """Return a tz-naive UTC datetime.

    The ``BAAAgreement.effective_at`` / ``expires_at`` columns are
    ``DateTime`` (no tz) per the original migration; comparing them
    to a tz-aware ``datetime.now(timezone.utc)`` raises a TypeError on
    Postgres. Strip tz for comparison consistency.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _query_active_baa(
    session: AsyncSession, *, org_id: str, now: datetime
) -> bool:
    """Cache-bypassing DB check.

    Returns True iff a BAAAgreement row for ``org_id`` is currently
    active AND has at least one BAAScope. Uses an EXISTS-style query
    (LIMIT 1) so the cost is bounded even when an org accumulates many
    agreements over time.
    """
    stmt = (
        select(BAAAgreement.id)
        .join(BAAScope, BAAScope.baa_agreement_id == BAAAgreement.id)
        .where(
            BAAAgreement.org_id == org_id,
            BAAAgreement.status == "active",
            # ``effective_at IS NULL`` covers BAAs imported without an
            # explicit start date (legacy paper agreements). Treat as
            # always-effective once status flips to 'active'.
            (BAAAgreement.effective_at.is_(None))
            | (BAAAgreement.effective_at <= now),
            # ``expires_at IS NULL`` covers indefinite BAAs. Most BAAs
            # in practice are dated, but the column is nullable per the
            # model in PR #195, so we honour NULL here.
            (BAAAgreement.expires_at.is_(None))
            | (BAAAgreement.expires_at > now),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def is_org_baa_active(
    session: AsyncSession,
    org_id: str,
    *,
    bypass_cache: bool = False,
) -> bool:
    """Return True iff the org has an active+scoped BAA right now.

    Hot path is a dict lookup; on miss / expiry we hit the DB once and
    repopulate the cache. ``bypass_cache=True`` forces a DB lookup
    (used by the create-key endpoint, where freshness matters more than
    request latency).

    The cache is shared across BOTH the C1 (create-time) and C2
    (per-request gate) call sites so a freshly-uploaded BAA is visible
    to both paths after the next miss without coordination. Revocation
    propagation is bounded by ``_CACHE_TTL_SECONDS``.
    """
    if not bypass_cache:
        entry = _BAA_FRESHNESS_CACHE.get(org_id)
        if entry is not None:
            cached_at, cached_result = entry
            if (time.monotonic() - cached_at) < _CACHE_TTL_SECONDS:
                return cached_result

    is_active = await _query_active_baa(
        session, org_id=org_id, now=_now_naive_utc()
    )
    _BAA_FRESHNESS_CACHE[org_id] = (time.monotonic(), is_active)
    return is_active


def invalidate_org_baa_cache(org_id: str) -> None:
    """Drop ``org_id``'s cached freshness result.

    Called by the BAA upload endpoint (``POST /v1/customers/{tenant_id}/baa``,
    Phase 1 PR 13) so a freshly-uploaded BAA is visible to the next
    live-key authenticated request without waiting up to 60 s for the
    TTL. Safe to call when no entry exists.

    Revoke / status-flip / expire paths ship in a follow-up; each MUST
    call this after the commit lands. Grep for ``invalidate_org_baa_cache``
    on PRs that add those paths to confirm.
    """
    _BAA_FRESHNESS_CACHE.pop(org_id, None)


__all__ = [
    "is_org_baa_active",
    "invalidate_org_baa_cache",
    "_reset_baa_freshness_cache_for_tests",
]
