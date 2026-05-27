"""Pure helpers that keep AI-Insights model output honest.

Why a separate module
---------------------
The OpenAI call is one of three places model output can go wrong:

  1. Bad JSON  → caller retries once, then falls through to
     :func:`fallback_insights`.
  2. Hallucinated ``quoted_source`` (not a substring of the posture
     payload) → the offending card is replaced with a fallback card
     via :func:`fallback_card`.
  3. Off-spec ``severity`` (e.g. "CRITICAL") → :func:`clamp_severity`
     normalises to ``LOW``.

Each helper is pure and side-effect-free so the unit tests cover the
clamp + substring logic without the SDK in the picture.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ...schemas.insights import Insight, InsightSeverity


# Allowed severities. Anything not in this set gets clamped to LOW.
_ALLOWED_SEVERITIES: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")

# Lower-bound + upper-bound on the insight count we return. Brief
# says 3-5 inclusive — both directions enforced here. Keep these as
# module constants so the route layer + tests reference the same
# numbers.
MIN_INSIGHTS = 3
MAX_INSIGHTS = 5


def _normalize_whitespace(s: str) -> str:
    """Collapse all runs of whitespace to a single space and lower-case.

    Used by :func:`validate_quoted_source` to do a whitespace-tolerant,
    case-insensitive substring match. The model often tweaks quoting
    minor ways ("12 of 14" → "12 of  14", or capitalisation drift on
    field names) — we accept these as semantically identical to the
    posture payload rather than calling them hallucinations.
    """
    return re.sub(r"\s+", " ", s).strip().lower()


def validate_quoted_source(
    quoted: str, posture_payload: dict[str, Any] | str
) -> bool:
    """Return True if ``quoted`` appears verbatim in the posture payload.

    Whitespace-tolerant + case-insensitive — see
    :func:`_normalize_whitespace`. Empty/blank quotes fail (they can't
    cite anything). Accepts either a dict (serialised with
    ``json.dumps`` here) or a pre-serialised string.

    The intent: the validator catches "the org has 999999 actions" but
    accepts "HITL completion : 12 of 14" (extra space) when the
    posture string was "HITL completion: 12 of 14".
    """
    if not quoted or not quoted.strip():
        return False

    if isinstance(posture_payload, dict):
        payload_str = json.dumps(posture_payload, default=str)
    else:
        payload_str = posture_payload

    return _normalize_whitespace(quoted) in _normalize_whitespace(payload_str)


def clamp_severity(value: Any) -> InsightSeverity:
    """Map any input to one of {HIGH, MEDIUM, LOW}.

    Case-insensitive on entry; off-spec values (e.g. "CRITICAL",
    "warn", 7, None) all clamp to ``LOW``. The brief is explicit:
    "Map any other value the model might emit to LOW."
    """
    if isinstance(value, str):
        up = value.strip().upper()
        if up in _ALLOWED_SEVERITIES:
            return up  # type: ignore[return-value]
    return "LOW"


def _new_id() -> str:
    """Fresh UUID4 string. Wrapped for ease of test monkeypatching."""
    return str(uuid.uuid4())


def fallback_card(
    *,
    title: str | None = None,
    description: str | None = None,
    quoted_source: str | None = None,
    suggested_action: str | None = None,
) -> Insight:
    """Build a single "insufficient signal" fallback card.

    Used in three places:
      * Padding when the model returned fewer than ``MIN_INSIGHTS``.
      * Replacing a card whose ``quoted_source`` failed validation.
      * Filling all three slots when JSON parsing failed twice.

    Voice rules apply here — every string is hard-coded, not
    model-emitted. "Consider …" / "Recommended: …" lead-in on the
    action, never a bare imperative.
    """
    return Insight(
        id=_new_id(),
        title=title or "Insufficient signal for a specific recommendation",
        severity="LOW",
        # Fallback quote is the literal phrase the model is told to use
        # when it can't anchor a card. We mirror that phrasing here so
        # the dashboard render is consistent across "model fell short"
        # and "validator rejected" paths.
        quoted_source=quoted_source or "Insufficient signal",
        description=(
            description
            or (
                "There is not yet enough activity in this window to "
                "produce a specific recommendation for this dimension."
            )
        ),
        suggested_action=(
            suggested_action
            or (
                "Consider collecting additional decisions over the "
                "next reporting window to unlock richer recommendations."
            )
        ),
    )


def _coerce_card(raw: Any, posture_payload: dict[str, Any] | str) -> Insight:
    """Coerce one raw dict from the model into a validated Insight.

    Any field shape issue (missing field, off-spec severity, hallucinated
    quote) routes through :func:`fallback_card` so the caller gets a
    usable card regardless. ``id`` is server-generated even if the
    model emitted one — we never trust caller-supplied UUIDs.
    """
    if not isinstance(raw, dict):
        return fallback_card()

    title = raw.get("title")
    description = raw.get("description")
    suggested_action = raw.get("suggested_action")
    quoted_source = raw.get("quoted_source")

    # Any missing required field → fallback. We could partially
    # rescue, but the brief is clear that the validator is allowed to
    # be conservative.
    if not (
        isinstance(title, str)
        and title.strip()
        and isinstance(description, str)
        and description.strip()
        and isinstance(suggested_action, str)
        and suggested_action.strip()
        and isinstance(quoted_source, str)
        and quoted_source.strip()
    ):
        return fallback_card()

    if not validate_quoted_source(quoted_source, posture_payload):
        return fallback_card()

    return Insight(
        id=_new_id(),
        title=title.strip(),
        severity=clamp_severity(raw.get("severity")),
        quoted_source=quoted_source.strip(),
        description=description.strip(),
        suggested_action=suggested_action.strip(),
    )


def clamp_count(insights: list[Insight]) -> list[Insight]:
    """Force the list to MIN_INSIGHTS..MAX_INSIGHTS inclusive.

    Too-many → take the first MAX_INSIGHTS (the model produces in
    rough priority order; preserving that beats random sampling).
    Too-few → pad with fallback cards. The brief says we "always
    return at least 3".
    """
    if len(insights) > MAX_INSIGHTS:
        return insights[:MAX_INSIGHTS]
    while len(insights) < MIN_INSIGHTS:
        insights.append(fallback_card())
    return insights


def parse_and_validate(
    raw_text: str, posture_payload: dict[str, Any] | str
) -> list[Insight] | None:
    """Parse the model's JSON output → list of validated Insights.

    Returns ``None`` if the JSON is unparseable so the caller can
    decide whether to retry or fall back. On a parse success, EVERY
    card runs through :func:`_coerce_card` (which may itself produce
    a fallback) before count-clamping in the route layer.

    Accepts either ``{"insights": [...]}`` or a bare ``[...]`` —
    The model occasionally drops the wrapper key on short replies.
    """
    text = raw_text.strip()
    # Strip ```json fences the model sometimes wraps output in despite
    # being told not to. A defensive cleanup; the validator still
    # catches "you sent us pure prose" via the JSON parse failure
    # below.
    if text.startswith("```"):
        # Drop the leading fence (possibly ```json) and trailing fence.
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if isinstance(parsed, dict):
        cards = parsed.get("insights")
        if not isinstance(cards, list):
            return None
    elif isinstance(parsed, list):
        cards = parsed
    else:
        return None

    return [_coerce_card(c, posture_payload) for c in cards]


def fallback_insights() -> list[Insight]:
    """Return MIN_INSIGHTS canned fallback cards.

    Used when the OpenAI call fails outright (timeout, two JSON parse
    failures, SDK exception). The cards are minimally varied so the
    dashboard doesn't render three identical tiles.
    """
    return [
        fallback_card(
            title="Insufficient signal for richer insights this window",
            description=(
                "Recommendation generation did not return analysable "
                "results for this request."
            ),
            quoted_source="Insufficient signal",
            suggested_action=(
                "Consider re-running insights after additional "
                "compliance activity has been recorded."
            ),
        ),
        fallback_card(
            title="More decisions needed to unlock specific guidance",
            description=(
                "The current posture snapshot does not contain enough "
                "activity to anchor a targeted recommendation."
            ),
            quoted_source="Insufficient signal",
            suggested_action=(
                "Recommended: review the posture summary directly "
                "while additional decisions are collected."
            ),
        ),
        fallback_card(
            title="Recommendations engine returned no actionable cards",
            description=(
                "The model did not produce a usable recommendation "
                "set for this request."
            ),
            quoted_source="Insufficient signal",
            suggested_action=(
                "Consider re-running insights shortly; transient model "
                "failures resolve on retry."
            ),
        ),
    ]
