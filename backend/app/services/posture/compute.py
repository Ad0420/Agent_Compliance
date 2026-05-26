"""Compliance Posture orchestrator (Phase 4 Wave 1 PR B1).

Single async entry point :func:`compute_posture` that fans out across
the six dimensions and assembles a :class:`PostureResponse`.

We deliberately run the dimensions *sequentially* on the shared
``AsyncSession`` rather than fanning out with ``asyncio.gather``. The
brief allows either; sequential is simpler and avoids the "two
queries on the same session" gotcha that bites under SQLAlchemy's
async session model. The F7 deferral lifts this constraint when 1M
actions / p99 > 500ms pressure materialises.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.posture import (
    MeasuredDimension,
    NotYetEligibleDimension,
    PostureResponse,
)
from . import dimensions as dims


# Default rolling-window length. The route layer lets callers override
# via ``?window_days=N`` but tops out at 365 — the chain-integrity
# aggregator's own scan is bounded at 30 days so a longer window is
# silently no-op'd for that dimension (which is honestly fine; chain
# integrity is binary anyway).
DEFAULT_WINDOW_DAYS = 30


async def compute_posture(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> PostureResponse:
    """Compute the six universal posture dimensions for ``org_id``.

    Returns a :class:`PostureResponse` ready for FastAPI to serialise.
    Caller is responsible for IAM gating + audit-log writes (the route
    layer in ``backend/app/routes/compliance.py`` handles both).
    """
    results = []
    # Order matters only for the response — measured/not_yet_eligible
    # arrays are populated by name (Literal in the schema), but the
    # iteration order here drives the dashboard's "natural" reading
    # order.
    results.append(
        await dims.compute_artifact_freshness(
            session, org_id, window_days=window_days
        )
    )
    results.append(
        await dims.compute_hitl_completion(
            session, org_id, window_days=window_days
        )
    )
    results.append(
        await dims.compute_reviewer_integrity(
            session, org_id, window_days=window_days
        )
    )
    results.append(
        await dims.compute_notice_delivery_rate(
            session, org_id, window_days=window_days
        )
    )
    results.append(
        await dims.compute_chain_integrity_dimension(
            session, org_id, window_days=window_days
        )
    )
    results.append(
        await dims.compute_workflow_timeliness(
            session, org_id, window_days=window_days
        )
    )

    measured: list[MeasuredDimension] = []
    not_yet_eligible: list[NotYetEligibleDimension] = []
    for r in results:
        if r.score is not None:
            measured.append(
                MeasuredDimension(
                    name=r.name,
                    score=r.score,
                    raw_count=r.raw_count,
                    measured_fact_line=r.measured_fact_line,
                )
            )
        else:
            not_yet_eligible.append(
                NotYetEligibleDimension(
                    name=r.name,
                    threshold=r.threshold,
                    current=r.current,
                    needed=r.needed,
                    reason=r.reason,
                )
            )

    headline = f"Runtime posture: {len(measured)} of 6 dimensions measured"

    return PostureResponse(
        composite_headline=headline,
        measured=measured,
        not_yet_eligible=not_yet_eligible,
        computed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        window_days=window_days,
    )
