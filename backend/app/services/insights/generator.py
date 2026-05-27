"""Generator orchestrator for the AI Insights endpoint.

:func:`generate_insights` is the single async entry point the route
handler depends on. It:

  1. Calls :func:`compute_posture` to get the live snapshot.
  2. Builds the Haiku prompt + asks the SDK once.
  3. Parses + validates the response.
  4. On parse failure, retries once with a stricter reminder.
  5. On second failure or timeout, returns canned fallback cards.

The Haiku client is constructed lazily (one per process) — the SDK
holds an HTTP connection pool we want to reuse. ``ANTHROPIC_API_KEY``
unset is a tolerated degraded mode: we skip the live call entirely
and return fallback cards so the endpoint still serves the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...schemas.insights import (
    INSIGHTS_DISCLAIMER,
    Insight,
    InsightsResponse,
)
from ..posture import compute_posture
from .prompt import (
    INSIGHTS_RETRY_REMINDER,
    INSIGHTS_SYSTEM_PROMPT,
    build_user_message,
)
from .validator import (
    clamp_count,
    fallback_insights,
    parse_and_validate,
)

logger = logging.getLogger(__name__)


# Sentinel raised by the route layer to map onto a 504. Generator
# does NOT catch this — the caller (route handler) decides whether
# timeout returns canned cards or a 504 response. The brief is
# explicit: timeout returns 504. We surface the raw exception via
# :class:`InsightsTimeoutError`.
class InsightsTimeoutError(Exception):
    """Raised when the Haiku call exceeds ``insights_timeout_seconds``.

    The route layer maps this onto an HTTP 504 with
    ``error.code == "insights_timeout"`` per the brief. We define a
    project-specific exception (rather than letting the bare
    ``asyncio.TimeoutError`` propagate) so the route handler can
    distinguish "Haiku slow" from any other unrelated upstream
    timeout in the stack.
    """


# Lazy client cache. The Anthropic SDK is an optional dependency in
# tests that monkeypatch the call site — we import inside the helper
# so a test that never exercises the live path doesn't have to install
# the SDK. Real deploys always have it (requirements.txt pins
# ``anthropic>=0.40``).
_client_cache: dict[str, Any] = {}


def _get_client() -> Any | None:
    """Return a cached :class:`AsyncAnthropic` client, or None.

    ``None`` means ``ANTHROPIC_API_KEY`` is unset; callers should
    degrade to fallback cards rather than raising. Otherwise returns
    the same client on every call so the SDK's HTTP connection pool
    is reused.
    """
    if not settings.anthropic_api_key:
        return None

    cached = _client_cache.get("client")
    if cached is not None:
        return cached

    try:
        from anthropic import AsyncAnthropic  # type: ignore
    except ImportError:
        logger.warning(
            "anthropic SDK not installed; insights endpoint will "
            "return fallback cards"
        )
        return None

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    _client_cache["client"] = client
    return client


def _reset_client_cache() -> None:
    """Drop the cached client. Test-only — invalidates after monkeypatch."""
    _client_cache.clear()


async def _call_haiku(
    client: Any,
    *,
    system_prompt: str,
    user_message: str,
) -> str:
    """Run a single Haiku messages.create + extract the text block.

    Returns the assistant's text content as a string. Raises whatever
    the SDK raises (caller catches + falls through).
    """
    response = await client.messages.create(
        model=settings.anthropic_insights_model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    # ``response.content`` is a list of content blocks; the first
    # block on a non-streaming text-only reply is a TextBlock. We
    # defensively look up the ``.text`` attribute and fall back to
    # the dict-style access the SDK sometimes returns under raw HTTP.
    if not response.content:
        return ""
    block = response.content[0]
    text = getattr(block, "text", None)
    if text is None and isinstance(block, dict):
        text = block.get("text", "")
    return text or ""


async def _attempt_haiku_call(
    posture_payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> list[Insight]:
    """Run up to two Haiku attempts; return validated cards.

    Returns:
      * The validated card list on success (any length — the route
        layer clamps to 3-5).
      * ``fallback_insights()`` if both attempts fail JSON parse or
        the SDK raises.

    Raises :class:`InsightsTimeoutError` on timeout — the route layer
    maps to 504.

    Total wall-clock budget is capped at ``timeout_seconds`` across
    BOTH attempts (the brief says "Hard 15s timeout on the Haiku
    call"). We track a single deadline and deduct elapsed time from
    the retry's timeout so two consecutive slow responses can't bust
    the cap.
    """
    client = _get_client()
    if client is None:
        # Degraded mode: no API key / SDK missing. Don't pretend we
        # called Haiku; just hand back canned cards. Operator gets a
        # one-line log so the silent fallback is auditable.
        logger.info(
            "insights: ANTHROPIC_API_KEY unset or SDK missing; "
            "returning fallback cards"
        )
        return fallback_insights()

    user_message = build_user_message(posture_payload)
    posture_str = json.dumps(posture_payload, default=str)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds

    def _remaining() -> float:
        """Seconds left in the total budget. Always >0 (caller checks)."""
        return deadline - loop.time()

    # First attempt — full budget.
    try:
        raw_text = await asyncio.wait_for(
            _call_haiku(
                client,
                system_prompt=INSIGHTS_SYSTEM_PROMPT,
                user_message=user_message,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise InsightsTimeoutError(
            f"Haiku call exceeded {timeout_seconds}s"
        ) from exc
    except Exception:
        # Any non-timeout SDK exception → fallback. We log + swallow;
        # the endpoint must not 500 on transient model issues.
        logger.exception("insights: first Haiku call raised; falling back")
        return fallback_insights()

    cards = parse_and_validate(raw_text, posture_str)
    if cards is not None:
        return cards

    # JSON parse failed. Retry once with the stricter reminder, but
    # ONLY if there's enough of the total budget left to make the
    # retry meaningful. A near-zero deadline means we'd hand back a
    # timeout-flavoured 504 even if the model responded; better to
    # fall through to canned cards.
    remaining = _remaining()
    if remaining < 1.0:
        logger.info(
            "insights: first attempt was non-JSON and budget exhausted "
            "(%.2fs left); using fallback cards",
            remaining,
        )
        return fallback_insights()

    logger.info(
        "insights: first attempt returned non-JSON; retrying once "
        "(%.2fs remaining in budget)",
        remaining,
    )
    retry_prompt = INSIGHTS_SYSTEM_PROMPT + INSIGHTS_RETRY_REMINDER
    try:
        raw_text = await asyncio.wait_for(
            _call_haiku(
                client,
                system_prompt=retry_prompt,
                user_message=user_message,
            ),
            timeout=remaining,
        )
    except asyncio.TimeoutError as exc:
        raise InsightsTimeoutError(
            f"Haiku retry exceeded the {timeout_seconds}s total budget"
        ) from exc
    except Exception:
        logger.exception("insights: retry Haiku call raised; falling back")
        return fallback_insights()

    cards = parse_and_validate(raw_text, posture_str)
    if cards is None:
        logger.warning(
            "insights: retry also returned non-JSON; using fallback cards"
        )
        return fallback_insights()
    return cards


async def generate_insights(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int = 30,
) -> InsightsResponse:
    """Produce an :class:`InsightsResponse` for ``org_id``.

    Computes the posture snapshot (delegating to the same
    ``compute_posture`` the GET endpoint uses — we never duplicate
    that math here), feeds it to Haiku, validates the response,
    clamps to 3-5 cards, and hard-codes the disclaimer.

    Raises :class:`InsightsTimeoutError` on Haiku timeout; the route
    layer translates to HTTP 504. All other SDK failures are
    swallowed and surface as fallback cards.
    """
    posture = await compute_posture(session, org_id, window_days=window_days)

    # Serialise the posture once so the validator's substring check
    # and the model's user message see the same source string. Using
    # mode="json" gives us serializable datetimes for the validator.
    posture_payload = posture.model_dump(mode="json")

    cards = await _attempt_haiku_call(
        posture_payload,
        timeout_seconds=settings.insights_timeout_seconds,
    )

    # Always clamp to 3-5. The validator handles the padding; we just
    # call its helper here to keep the contract enforcement local.
    cards = clamp_count(cards)

    return InsightsResponse(
        insights=cards,
        # Hard-coded; never trust the model.
        disclaimer=INSIGHTS_DISCLAIMER,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        window_days=window_days,
        posture_snapshot=posture,
    )
