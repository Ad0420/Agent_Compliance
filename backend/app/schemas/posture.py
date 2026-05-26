"""Response schemas for ``GET /v1/compliance/posture`` (Phase 4 Wave 1 PR B1).

The Compliance Posture endpoint scores an org across six universal
dimensions (artifact freshness, HITL completion, reviewer integrity,
notice delivery rate, chain integrity, workflow timeliness). Each
dimension lands in one of two buckets:

* **measured** — the org has cleared the low-volume minimum, so we
  publish a 0-100 integer score plus a single short ``measured_fact_line``
  the dashboard renders verbatim.
* **not_yet_eligible** — the org is under the minimum data threshold;
  we publish ``current`` / ``needed`` counts plus a ``reason`` string
  so the dashboard can render an honest "insufficient data" state.

The composite headline counts how many dimensions are measured
(``N of 6 dimensions measured``). No single number is computed because
the v1 product policy is explicit: don't conflate "posture" with
"compliance". The dashboard layer (C1) does the rendering; this
endpoint is the data contract.

See ``policy-engine-mvp.md §Compliance Posture`` for the underlying
universal-dimensions model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# Six universal-dimension names. Kept here as a Literal so the response
# shape is type-checked end-to-end — adding a new dimension is a
# deliberate schema change, not a silent string drift.
DimensionName = Literal[
    "artifact_freshness",
    "hitl_completion",
    "reviewer_integrity",
    "notice_delivery_rate",
    "chain_integrity",
    "workflow_timeliness",
]


class MeasuredDimension(BaseModel):
    """A dimension that has enough data to publish a real score.

    ``score`` is an integer 0..100. ``raw_count`` is the denominator the
    score was computed against (e.g. number of HITL events in window).
    ``measured_fact_line`` is the short human-readable string the
    dashboard renders verbatim — voice & copy lives in the producer,
    not the consumer.
    """

    name: DimensionName
    score: int = Field(..., ge=0, le=100)
    raw_count: int = Field(
        ...,
        ge=0,
        description=(
            "Denominator used in the score calculation — for HITL "
            "completion this is the count of HITL-triggering decisions "
            "in the window, etc."
        ),
    )
    measured_fact_line: str = Field(
        ...,
        description=(
            "Short human-readable summary the dashboard renders "
            "verbatim. Already follows the project's voice rules "
            "(comma-separated thousands, customer-not-tenant wording)."
        ),
    )

    model_config = {"from_attributes": True}


class NotYetEligibleDimension(BaseModel):
    """A dimension under the low-volume threshold.

    The dashboard renders this honestly as "insufficient data" rather
    than computing a misleading score from a single data point. The
    ``current`` / ``needed`` numbers drive a "X of Y events captured"
    progress treatment.
    """

    name: DimensionName
    threshold: int = Field(
        ...,
        ge=1,
        description=(
            "Minimum number of data points required before a real "
            "score can be computed."
        ),
    )
    current: int = Field(
        ...,
        ge=0,
        description="Data points captured in the current window.",
    )
    needed: int = Field(
        ...,
        ge=0,
        description=(
            "Data points still required to reach the minimum — i.e. "
            "max(0, threshold - current). Pre-computed for the "
            "dashboard so the consumer can't drift from the rule."
        ),
    )
    reason: str = Field(
        ...,
        description=(
            "Short human-readable explanation of why this dimension "
            "isn't yet eligible (e.g. 'Insufficient HITL events')."
        ),
    )

    model_config = {"from_attributes": True}


class PostureResponse(BaseModel):
    """Full Compliance Posture aggregator response.

    ``composite_headline`` is a single short string of the form
    ``"Runtime posture: N of 6 dimensions measured"`` where N counts
    only the dimensions in ``measured``. The dashboard layer (C1)
    renders the headline as-is — no client-side string assembly.

    ``computed_at`` is the server's wall-clock at the moment the
    response was generated; the dashboard can surface a "fresh as of"
    timestamp without having to assume the request landed instantly.
    """

    composite_headline: str = Field(
        ...,
        description=(
            "Single-sentence headline of the form 'Runtime posture: N "
            "of 6 dimensions measured'."
        ),
    )
    measured: list[MeasuredDimension]
    not_yet_eligible: list[NotYetEligibleDimension]
    computed_at: datetime
    window_days: int = Field(..., ge=1, le=365)

    model_config = {"from_attributes": True}
