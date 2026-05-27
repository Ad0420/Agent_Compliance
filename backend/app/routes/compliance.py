"""Compliance Posture + AI Insights routes.

Mounts:

  * ``GET  /v1/compliance/posture``  — Phase 4 Wave 1 PR B1. On-demand
    compute for the six universal posture dimensions (artifact
    freshness, HITL completion, reviewer integrity, notice delivery
    rate, chain integrity, workflow timeliness).

  * ``POST /v1/compliance/insights`` — Phase 4 Wave 2 PR B2.
    Synchronous OpenAI-backed call returning 3-5 recommendation cards
    over the live posture snapshot. No persistence — each call
    regenerates.

IAM
---
Customer admin (Clerk session bound to the org) OR Vera staff
(STAFF_READ_ONLY via X-Org-Id header). Both tiers see the same payload
— no PHI in either response (all aggregate counts) — but staff calls
write a row to ``staff_audit_log`` so the customer can see who looked
at their posture / insights.

The brief explicitly says "no API-key path needed for v1"; we still
register the routes under ``/v1/compliance/*`` because the
``require_permission_with_context`` dependency accepts both bearer
shapes and the route logic is identical. If a customer happens to
present an API key the route still serves them their own org's data
— there's no PHI to leak.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..schemas.insights import InsightsResponse
from ..schemas.posture import PostureResponse
from ..services.auth import AuthContext, require_permission_with_context
from ..services.iam import audit_staff_read
from ..services.insights import generate_insights
from ..services.insights.generator import InsightsTimeoutError
from ..services.insights.rate_limit import check_rate_limit
from ..services.posture import compute_posture


router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("/posture", response_model=PostureResponse)
async def get_compliance_posture(
    window_days: int = Query(
        default=30,
        ge=1,
        le=365,
        description=(
            "Rolling window (in days) for the dimensions that score "
            "against recent activity (HITL completion, reviewer "
            "integrity, notice delivery rate, workflow timeliness). "
            "Artifact freshness uses the canonical annual refresh "
            "cadence and ignores this parameter. Chain integrity "
            "uses the aggregator's own 30-day scan."
        ),
    ),
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> PostureResponse:
    """Return the Compliance Posture aggregate for the active org.

    Customer-tier callers see their own org's posture. Staff-tier
    callers see whichever org the ``X-Org-Id`` header pins, with a
    ``staff_audit_log`` row written per request (one row per HTTP
    request — chain-integrity-style aggregate scope, no PHI).
    """
    org_id = ctx.org_id
    result = await compute_posture(session, org_id, window_days=window_days)

    # Per Wave 3B.3 policy (CLAUDE.md IAM tier checks): branch on the
    # ``is_staff`` helper rather than a direct enum comparison —
    # STAFF_FULL is reserved for v2 and must behave identically here.
    # The CI gate ``iam-tier-check`` enforces this at PR time; see
    # backend/app/services/auth.py::AuthContext.is_staff for the
    # canonical rationale.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/compliance/posture",
            org_id=org_id,
            resource_type="compliance_posture",
            resource_id=None,
            resource_count=1,
            redacted=False,
        )

    return result


@router.post("/insights", response_model=InsightsResponse)
async def post_compliance_insights(
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> InsightsResponse:
    """Generate 3-5 AI recommendation cards for the active org.

    Synchronous OpenAI Responses-API call over the live posture
    snapshot. No request body — the org scope comes from the auth
    context, the window defaults to 30 days (matching
    ``GET /v1/compliance/posture``).

    Same auth shape as the posture endpoint: customer admin OR Vera
    staff via X-Org-Id. Staff calls write a single
    ``staff_audit_log`` row with ``resource_type="compliance_insights"``.

    Rate limit: ``settings.insights_rate_limit_per_min`` calls/minute
    per org. Exceeding returns 429 with ``Retry-After: 60``.

    Timeout: ``settings.insights_timeout_seconds`` (default 15s) on the
    OpenAI call. Returns 504 with ``error.code == "insights_timeout"``
    on hard timeout — operational failure modes downstream of the
    model (bad JSON, hallucinated quotes, etc.) are swallowed and
    surface as fallback cards rather than 5xx-ing the request.
    """
    org_id = ctx.org_id

    # Rate limit BEFORE running the OpenAI call. Cheaper to refuse
    # early; keeps cost predictable when a misconfigured client retries
    # on a tight loop.
    decision = await check_rate_limit(
        org_id,
        "insights",
        max_per_minute=settings.insights_rate_limit_per_min,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "insights_rate_limited",
                    "message": (
                        "Insights rate limit exceeded for this "
                        "organisation; retry shortly."
                    ),
                }
            },
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    try:
        result = await generate_insights(session, org_id)
    except InsightsTimeoutError as exc:
        # 504 Gateway Timeout — the upstream we depended on (OpenAI)
        # did not return within the configured budget. Per the brief,
        # error.code is exactly ``insights_timeout`` so the dashboard
        # can show a specific retry affordance.
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "code": "insights_timeout",
                    "message": (
                        "AI insights generation timed out; please try again."
                    ),
                }
            },
        ) from exc

    # Staff audit row: one per request, resource_type "compliance_insights".
    # Mirrors the posture endpoint's audit shape. Uses ``ctx.is_staff``
    # (not a direct enum compare) per the IAM tier policy — the CI
    # lint gate ``iam-tier-check`` enforces this on every PR.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/compliance/insights",
            org_id=org_id,
            resource_type="compliance_insights",
            resource_id=None,
            resource_count=1,
            redacted=False,
        )

    return result
