"""Generator orchestrator for the AI Insights endpoint.

:func:`generate_insights` is the single async entry point the route
handler depends on. It:

  1. Calls :func:`compute_posture` to get the live snapshot.
  2. Builds the OpenAI prompt + asks the SDK once.
  3. Parses + validates the response.
  4. On parse failure, retries once with a stricter reminder.
  5. On second failure or timeout, returns canned fallback cards.

The OpenAI client is constructed lazily (one per process) — the SDK
holds an HTTP connection pool we want to reuse. ``OPENAI_API_KEY``
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
    """Raised when the OpenAI call exceeds ``insights_timeout_seconds``.

    The route layer maps this onto an HTTP 504 with
    ``error.code == "insights_timeout"`` per the brief. We define a
    project-specific exception (rather than letting the bare
    ``asyncio.TimeoutError`` propagate) so the route handler can
    distinguish "OpenAI slow" from any other unrelated upstream
    timeout in the stack.
    """


# Lazy client cache. The OpenAI SDK is an optional dependency in
# tests that monkeypatch the call site — we import inside the helper
# so a test that never exercises the live path doesn't have to install
# the SDK. Real deploys always have it (requirements.txt pins
# ``openai>=1.50,<2``).
_client_cache: dict[str, Any] = {}


def _openai_client() -> Any | None:
    """Return a cached :class:`AsyncOpenAI` client, or None.

    ``None`` means ``OPENAI_API_KEY`` is unset; callers should
    degrade to fallback cards rather than raising. Otherwise returns
    the same client on every call so the SDK's HTTP connection pool
    is reused.
    """
    if not settings.openai_api_key:
        return None

    cached = _client_cache.get("client")
    if cached is not None:
        return cached

    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError:
        logger.warning(
            "openai SDK not installed; insights endpoint will "
            "return fallback cards"
        )
        return None

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    _client_cache["client"] = client
    return client


def _reset_client_cache() -> None:
    """Drop the cached client. Test-only — invalidates after monkeypatch."""
    _client_cache.clear()


async def _call_openai(
    client: Any,
    *,
    system_prompt: str,
    user_message: str,
) -> str:
    """Run a single OpenAI Responses-API call + extract the text output.

    Returns the model's text content as a string. Raises whatever the
    SDK raises (caller catches + falls through).

    Uses the Responses API (``client.responses.create``) with a
    structured ``input`` array carrying the system prompt + user
    message. The convenience accessor ``response.output_text`` returns
    the final text output; we fall back to walking
    ``response.output[*].content[*].text`` if that accessor is absent
    on a particular SDK version.
    """
    response = await client.responses.create(
        model=settings.openai_insights_model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    # Preferred path: the SDK exposes ``output_text`` as a convenience
    # accessor that concatenates every text segment in the response.
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text:
        return text

    # Fallback path: walk the structured output. Each element of
    # ``response.output`` is a message-like object with a ``content``
    # list; each content element exposes a ``text`` attribute (or a
    # dict shape under raw HTTP). We concatenate every text fragment
    # we find — matches the convenience accessor's behaviour.
    output = getattr(response, "output", None) or []
    pieces: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if not content:
            continue
        for block in content:
            block_text = getattr(block, "text", None)
            if block_text is None and isinstance(block, dict):
                block_text = block.get("text")
            if isinstance(block_text, str) and block_text:
                pieces.append(block_text)
    return "".join(pieces)


async def _attempt_openai_call(
    posture_payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> list[Insight]:
    """Run up to two OpenAI attempts; return validated cards.

    Returns:
      * The validated card list on success (any length — the route
        layer clamps to 3-5).
      * ``fallback_insights()`` if both attempts fail JSON parse or
        the SDK raises.

    Raises :class:`InsightsTimeoutError` on timeout — the route layer
    maps to 504.

    Total wall-clock budget is capped at ``timeout_seconds`` across
    BOTH attempts (the brief says "Hard 15s timeout on the OpenAI
    call"). We track a single deadline and deduct elapsed time from
    the retry's timeout so two consecutive slow responses can't bust
    the cap.
    """
    client = _openai_client()
    if client is None:
        # Degraded mode: no API key / SDK missing. Don't pretend we
        # called OpenAI; just hand back canned cards. Operator gets a
        # one-line log so the silent fallback is auditable.
        logger.info(
            "insights: OPENAI_API_KEY unset or SDK missing; "
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
            _call_openai(
                client,
                system_prompt=INSIGHTS_SYSTEM_PROMPT,
                user_message=user_message,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise InsightsTimeoutError(
            f"OpenAI call exceeded {timeout_seconds}s"
        ) from exc
    except Exception:
        # Any non-timeout SDK exception → fallback. We log + swallow;
        # the endpoint must not 500 on transient model issues.
        logger.exception("insights: first OpenAI call raised; falling back")
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
            _call_openai(
                client,
                system_prompt=retry_prompt,
                user_message=user_message,
            ),
            timeout=remaining,
        )
    except asyncio.TimeoutError as exc:
        raise InsightsTimeoutError(
            f"OpenAI retry exceeded the {timeout_seconds}s total budget"
        ) from exc
    except Exception:
        logger.exception("insights: retry OpenAI call raised; falling back")
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
    that math here), feeds it to OpenAI, validates the response,
    clamps to 3-5 cards, and hard-codes the disclaimer.

    Raises :class:`InsightsTimeoutError` on OpenAI timeout; the route
    layer translates to HTTP 504. All other SDK failures are
    swallowed and surface as fallback cards.
    """
    posture = await compute_posture(session, org_id, window_days=window_days)

    # Serialise the posture once so the validator's substring check
    # and the model's user message see the same source string. Using
    # mode="json" gives us serializable datetimes for the validator.
    posture_payload = posture.model_dump(mode="json")

    cards = await _attempt_openai_call(
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
