"""Pure backoff/idempotency tests for ``app/services/webhook_retry.py``.

No DB, no event loop, no freezegun — every function takes its time
input as a parameter so tests just feed in ``datetime(...)`` values.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from app.services.webhook_retry import (
    DEFAULT_JITTER_PCT,
    MAX_ATTEMPTS,
    RETRY_SCHEDULE_SECONDS,
    compute_next_retry_at,
    idempotency_key_for_review,
    is_terminal_attempt,
)


# ── schedule shape ─────────────────────────────────────────────────────────


def test_max_attempts_is_seven():
    assert MAX_ATTEMPTS == 7
    assert len(RETRY_SCHEDULE_SECONDS) == 6


def test_schedule_is_strictly_monotonic():
    # Each step must be longer than the previous — exponential-ish.
    for prev, cur in zip(RETRY_SCHEDULE_SECONDS, RETRY_SCHEDULE_SECONDS[1:]):
        assert cur > prev


def test_schedule_values_match_plan():
    """Plan §3 ladder: 60s, 5m, 30m, 2h, 8h, 24h."""
    assert RETRY_SCHEDULE_SECONDS == (60, 300, 1_800, 7_200, 28_800, 86_400)


# ── compute_next_retry_at — happy path ────────────────────────────────────


@pytest.mark.parametrize(
    "attempt,expected_seconds",
    [
        (1, 60),
        (2, 300),
        (3, 1_800),
        (4, 7_200),
        (5, 28_800),
        (6, 86_400),
    ],
)
def test_compute_next_retry_at_returns_correct_base_no_jitter(
    attempt, expected_seconds
):
    """With ``jitter_pct=0`` the next-retry is exactly base seconds out."""
    now = datetime(2026, 5, 24, 12, 0, 0)
    out = compute_next_retry_at(attempt, now, jitter_pct=0.0)
    assert out == now + timedelta(seconds=expected_seconds)


def test_compute_next_retry_at_returns_none_when_exhausted():
    """Attempt 7 just failed → no more retries."""
    now = datetime(2026, 5, 24, 12, 0, 0)
    assert compute_next_retry_at(MAX_ATTEMPTS, now) is None
    # Out-of-range values also return None (defensive).
    assert compute_next_retry_at(MAX_ATTEMPTS + 1, now) is None
    assert compute_next_retry_at(99, now) is None


def test_compute_next_retry_at_rejects_zero_or_negative():
    now = datetime(2026, 5, 24, 12, 0, 0)
    with pytest.raises(ValueError):
        compute_next_retry_at(0, now)
    with pytest.raises(ValueError):
        compute_next_retry_at(-1, now)


# ── jitter band ────────────────────────────────────────────────────────────


def test_jitter_is_symmetric_within_band():
    """``jitter_pct=0.10`` means delay ∈ base * [0.9, 1.1)."""
    now = datetime(2026, 5, 24, 12, 0, 0)
    rng = random.Random(0)
    # Sample many to confirm bounds — deterministic via seeded RNG.
    samples = [
        (compute_next_retry_at(1, now, jitter_pct=0.10, rng=rng) - now).total_seconds()
        for _ in range(1000)
    ]
    base = 60
    band = base * 0.10
    for s in samples:
        assert base - band <= s < base + band, s


def test_default_jitter_is_ten_percent():
    assert DEFAULT_JITTER_PCT == 0.10


# ── is_terminal_attempt ────────────────────────────────────────────────────


def test_is_terminal_attempt_true_only_at_max():
    for i in range(1, MAX_ATTEMPTS):
        assert is_terminal_attempt(i) is False
    assert is_terminal_attempt(MAX_ATTEMPTS) is True
    assert is_terminal_attempt(MAX_ATTEMPTS + 1) is True


# ── idempotency_key_for_review ────────────────────────────────────────────


def test_idempotency_key_for_review_is_deterministic():
    k1 = idempotency_key_for_review("approval-123", "review.completed")
    k2 = idempotency_key_for_review("approval-123", "review.completed")
    assert k1 == k2
    assert k1 == "approval-123:review.completed"


def test_idempotency_key_for_review_distinguishes_event_types():
    """Same approval → distinct keys for ``requested`` vs ``completed`` vs ``expired``."""
    aid = "approval-abc"
    keys = {
        idempotency_key_for_review(aid, "review.requested"),
        idempotency_key_for_review(aid, "review.completed"),
        idempotency_key_for_review(aid, "review.expired"),
    }
    assert len(keys) == 3


def test_idempotency_key_for_review_requires_both_args():
    with pytest.raises(ValueError):
        idempotency_key_for_review("", "review.completed")
    with pytest.raises(ValueError):
        idempotency_key_for_review("approval-1", "")
