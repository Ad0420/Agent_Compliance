"""Per-org sliding-window rate limiter for the AI Insights endpoint.

The existing :class:`RateLimitMiddleware` rate-limits the whole API
per bearer/IP at 120 rpm. The Insights brief is stricter:

  > Rate limit: 10 calls/min per org. Return 429 with
  > ``Retry-After: 60`` if exceeded.

We can't piggyback on the middleware because the middleware fires
*before* the auth dependency resolves the org_id — at that point we
only know the bearer token, not the org. So insights gets a dedicated
sliding-window counter keyed on ``(org_id, "insights")`` that runs
inside the route handler (after auth has resolved ``ctx.org_id``).

In-process only — multi-instance deploys swap this for Redis. v1
runs single-instance on Railway, so per-process state is fine.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass


# 60-second window — the brief specifies 10 calls/min and
# ``Retry-After: 60``. We commit to the same number here; if the
# product ever splits "per-minute window length" from "Retry-After
# value" we can wire two fields, but for v1 they're the same.
_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of a rate-limit check.

    ``allowed=False`` means the caller should return 429 with the
    ``retry_after_seconds`` value in the ``Retry-After`` header.
    """

    allowed: bool
    retry_after_seconds: int


# Module-level state. ``defaultdict(deque)`` so a brand-new
# ``(org_id, endpoint)`` pair gets an empty deque without a lookup
# pre-init step. ``_lock`` guards against concurrent requests from
# the same org racing each other's purge + append; under FastAPI's
# asyncio loop this matters because the route is async.
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()


async def check_rate_limit(
    org_id: str,
    endpoint: str,
    *,
    max_per_minute: int,
) -> RateLimitDecision:
    """Sliding-window rate-limit check for ``(org_id, endpoint)``.

    Atomically:
      1. Purges entries older than the 60s window.
      2. If the window already has ``max_per_minute`` entries → deny.
      3. Else append ``now()`` to the window and allow.

    Returns the decision; the caller is responsible for raising
    HTTPException(429) when ``allowed=False``.
    """
    if max_per_minute <= 0:
        # ``0`` or negative is the "rate limiting disabled" sentinel —
        # used by tests that hammer the endpoint without wanting to
        # care about cooldowns. Production sets a positive number.
        return RateLimitDecision(allowed=True, retry_after_seconds=0)

    key = (org_id, endpoint)
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS

    async with _lock:
        window = _buckets[key]
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= max_per_minute:
            # Retry-After: time until the oldest entry expires.
            # Always at least 1s — a 0-second Retry-After invites the
            # client to immediately re-burst.
            retry_after = max(1, int(_WINDOW_SECONDS - (now - window[0])) + 1)
            return RateLimitDecision(
                allowed=False, retry_after_seconds=retry_after
            )

        window.append(now)
        return RateLimitDecision(allowed=True, retry_after_seconds=0)


def _reset_for_tests() -> None:
    """Drop all buckets. Test fixture hook — never call from prod code."""
    _buckets.clear()
