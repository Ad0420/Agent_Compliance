"""Compliance Posture routes (Phase 4 Wave 1 PR B1).

Mounts ``GET /v1/compliance/posture`` — the on-demand compute for the
six universal posture dimensions (artifact freshness, HITL completion,
reviewer integrity, notice delivery rate, chain integrity, workflow
timeliness).

IAM
---
Customer admin (Clerk session bound to the org) OR Vera staff
(STAFF_READ_ONLY via X-Org-Id header). Both tiers see the same payload
— no PHI in the response (all aggregate counts) — but staff calls
write a row to ``staff_audit_log`` so the customer can see who looked
at their posture.

The brief explicitly says "no API-key path needed for v1"; we still
register the route under ``/v1/compliance/posture`` because the
``require_permission_with_context`` dependency accepts both bearer
shapes and the route logic is identical. If a customer happens to
present an API key the route still serves them their own org's
posture — there's no PHI to leak.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.posture import PostureResponse
from ..services.auth import AuthContext, require_permission_with_context
from ..services.iam import audit_staff_read
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
