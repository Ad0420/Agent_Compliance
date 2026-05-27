"""Response schemas for ``POST /v1/compliance/insights`` (Phase 4 Wave 2 PR B2).

The AI Insights endpoint runs a synchronous OpenAI Responses-API call
over the live posture snapshot for the requesting org and returns 3-5
recommendation cards. The endpoint contract is:

  * Exactly 3-5 cards (the route layer clamps to that range — fewer
    are padded with fallback cards, more are truncated).
  * Each card has a literal ``quoted_source`` substring that appears
    in the posture payload. Hallucinated quotes are caught by the
    validator + replaced with a fallback card.
  * The ``disclaimer`` field is server-side hard-coded; the model is
    explicitly forbidden from generating it.
  * ``posture_snapshot`` is the SAME shape returned by
    ``GET /v1/compliance/posture`` at call time — included for
    transparency so the dashboard can render the source data
    alongside the recommendations without a second round-trip.

See ``policy-engine-mvp.md §AI Insights`` for the underlying spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .posture import PostureResponse


# The exact disclaimer string. Server-hard-coded — the route layer
# overwrites whatever the model emits with this constant. Voice rule:
# "regulator-ready" or "informational only", never "court-admissible".
INSIGHTS_DISCLAIMER = (
    "Recommendations are informational only; "
    "they are not regulatory advice."
)


# Severity bucket for an insight. The validator clamps any unknown
# value the model emits down to ``LOW`` rather than 500-ing the
# request — the brief is explicit that bad model output is a normal
# path, not an error.
InsightSeverity = Literal["HIGH", "MEDIUM", "LOW"]


class Insight(BaseModel):
    """A single recommendation card returned by the insights endpoint.

    Fields mirror the dashboard's card layout 1:1. The producer (this
    backend) does all the formatting; the consumer (the dashboard)
    renders verbatim. No client-side string assembly.
    """

    id: str = Field(
        ...,
        description=(
            "Server-generated UUID4 string. Stable per-card within a "
            "single response; NOT persisted across requests (insights "
            "regenerate on every call in v1)."
        ),
    )
    title: str = Field(
        ...,
        max_length=200,
        description=(
            "Short headline rendered as the card title. ≤10 words is "
            "the prompt's instruction to the model; the schema is "
            "tolerant at 200 chars in case the model overshoots."
        ),
    )
    severity: InsightSeverity = Field(
        ...,
        description=(
            "Visual severity (HIGH/MEDIUM/LOW). Unknown values from "
            "the model are clamped to LOW by the validator."
        ),
    )
    quoted_source: str = Field(
        ...,
        max_length=500,
        description=(
            "Literal substring from the posture JSON the model is "
            "citing as evidence. Validated server-side (substring "
            "check, whitespace-tolerant, case-insensitive). Hallucinated "
            "quotes are replaced with a fallback card."
        ),
    )
    description: str = Field(
        ...,
        max_length=1000,
        description="1-2 sentence explanation of what the signal means.",
    )
    suggested_action: str = Field(
        ...,
        max_length=500,
        description=(
            "Single-sentence recommendation. Starts with 'Consider' "
            "or 'Recommended:' per project voice rules; never a bare "
            "imperative."
        ),
    )

    model_config = {"from_attributes": True}


class InsightsResponse(BaseModel):
    """Full response from ``POST /v1/compliance/insights``.

    ``insights`` is guaranteed to be 3-5 entries inclusive. The
    ``disclaimer`` is the project's hard-coded constant
    (:data:`INSIGHTS_DISCLAIMER`). ``posture_snapshot`` is the byte-equal
    payload of ``GET /v1/compliance/posture`` at call time — the
    dashboard renders it alongside the cards so the user can audit the
    source.
    """

    insights: list[Insight] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 recommendation cards, inclusive.",
    )
    disclaimer: str = Field(
        ...,
        description=(
            "Server-hard-coded informational-only notice. ALWAYS "
            "equals :data:`INSIGHTS_DISCLAIMER`."
        ),
    )
    generated_at: datetime = Field(
        ...,
        description="UTC wall-clock at the moment this response was assembled.",
    )
    window_days: int = Field(
        ...,
        ge=1,
        le=365,
        description="Rolling window the underlying posture was computed over.",
    )
    posture_snapshot: PostureResponse = Field(
        ...,
        description=(
            "The full posture payload the recommendations were drawn "
            "from. Byte-equal to ``GET /v1/compliance/posture`` for the "
            "same org + window."
        ),
    )

    model_config = {"from_attributes": True}
