"""Pure backoff / idempotency math for the webhook retry pipeline.

Kept dependency-free so unit tests don't need a DB, freezegun, or an
event loop — every function here takes its time input as a parameter.

The schedule itself is the plan's §3 sketch:

  attempt 1 → immediate (the producer-side first attempt)
  attempt 2 → +60s
  attempt 3 → +5m
  attempt 4 → +30m
  attempt 5 → +2h
  attempt 6 → +8h
  attempt 7 → +24h
  attempt 8 → abort

That gives 7 total attempts spanning ~36 hours, ±10% jitter to break
recovery thundering herds.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional


# In seconds. Indexed by *zero-based* "this attempt has just failed, when
# do we try again?". ``RETRY_SCHEDULE_SECONDS[0]`` is the delay before
# attempt 2; ``RETRY_SCHEDULE_SECONDS[5]`` is the delay before attempt 7.
RETRY_SCHEDULE_SECONDS: tuple[int, ...] = (
    60,        # before attempt 2 (first retry)
    300,       # before attempt 3
    1_800,     # before attempt 4
    7_200,     # before attempt 5
    28_800,    # before attempt 6
    86_400,    # before attempt 7
)

# 1 initial attempt + len(schedule) retries.
MAX_ATTEMPTS: int = 1 + len(RETRY_SCHEDULE_SECONDS)  # 7

# Jitter is multiplicative around the base — ±10% by default. ``0.0`` is
# deterministic, used by tests that want predictable timestamps.
DEFAULT_JITTER_PCT: float = 0.10


def compute_next_retry_at(
    attempt_number: int,
    now: datetime,
    jitter_pct: float = DEFAULT_JITTER_PCT,
    rng: Optional[random.Random] = None,
) -> Optional[datetime]:
    """Return when to try delivery again, or ``None`` if we're out of attempts.

    Parameters
    ----------
    attempt_number
        The attempt that *just* failed (1-indexed). After attempt 1 fails
        we schedule attempt 2 at ``now + 60s ± jitter``. After attempt 7
        fails we return ``None`` — caller transitions the delivery to
        ``aborted``.
    now
        Wall clock. The pure function never reads time itself; this
        keeps tests deterministic without monkey-patching.
    jitter_pct
        Half-width of the ± jitter band. Set to ``0.0`` for tests that
        need an exact next-retry timestamp.
    rng
        Optional ``random.Random`` instance for deterministic tests. If
        omitted, the module-level ``random`` is used (which is fine for
        production — seeded by Python startup).

    Returns
    -------
    A future ``datetime`` matching ``now``'s timezone-awareness, or
    ``None`` when ``attempt_number`` has exhausted the schedule.
    """
    if attempt_number < 1:
        raise ValueError(
            f"attempt_number must be >= 1, got {attempt_number}"
        )
    if attempt_number >= MAX_ATTEMPTS:
        # Just-failed attempt was the last allowed one.
        return None
    base = RETRY_SCHEDULE_SECONDS[attempt_number - 1]
    if jitter_pct == 0:
        delta = float(base)
    else:
        source = rng if rng is not None else random
        # Symmetric ± jitter. ``random()`` is [0,1) → ``2*random - 1`` is
        # [-1,1), so the perturbation is base * jitter_pct * [-1, 1).
        offset = base * jitter_pct * (source.random() * 2 - 1)
        delta = base + offset
    return now + timedelta(seconds=delta)


def is_terminal_attempt(attempt_number: int) -> bool:
    """True if ``attempt_number`` is the last allowed attempt."""
    return attempt_number >= MAX_ATTEMPTS


def idempotency_key_for_review(approval_id: str, event_type: str) -> str:
    """Compose the composite idempotency key for ``review.*`` events.

    Returning a deterministic key for the same logical
    ``(approval, event_type)`` pair is what makes the producer-side
    double-emission a no-op (via the unique index on
    ``(subscription_id, idempotency_key)``).

    Example
    -------
    >>> idempotency_key_for_review("abc-123", "review.completed")
    'abc-123:review.completed'
    """
    if not approval_id or not event_type:
        raise ValueError("approval_id and event_type are both required")
    return f"{approval_id}:{event_type}"
