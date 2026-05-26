"""GET /v1/dashboard/chain-integrity — Phase 3 Wave 3D.1.

Aggregates the Home-page "Chain Integrity" tile in a single round-trip:
status (green/yellow/red), the latest checkpoint summary, chain depth,
current KMS key + algorithm, and the org's checkpoint cadence.

IAM:
* Customer tier sees their own org's chain.
* Staff tier with ``X-Org-Id`` sees that org's chain and writes a row
  to ``staff_audit_log`` (one row per request — chain-integrity scope,
  no PHI in the response body).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.chain_integrity import (
    ChainIntegrityResponse,
    KmsKeySummaryResponse,
    LatestCheckpointSummaryResponse,
)
from ..services.auth import AuthContext, require_permission_with_context
from ..services.chain_integrity import compute_chain_integrity
from ..services.iam import audit_staff_read

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/chain-integrity", response_model=ChainIntegrityResponse)
async def get_chain_integrity(
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> ChainIntegrityResponse:
    """Return the chain-integrity aggregate for the active org.

    See :func:`app.services.chain_integrity.compute_chain_integrity`
    for status semantics. The response body carries no PHI — chain
    integrity columns only — so the staff audit row is flagged
    ``redacted=False`` for future-tier-introduces-PHI defense.
    """
    org_id = ctx.org_id
    result = await compute_chain_integrity(session, org_id)

    # Per Wave 3B.3 policy (v1-test-plan row "STAFF_FULL behavioral
    # parity"), branch on ``ctx.is_staff`` so a future STAFF_FULL
    # tier writes the same audit row without a per-route fix.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/dashboard/chain-integrity",
            org_id=org_id,
            resource_type="chain_integrity",
            resource_id=None,
            redacted=False,
        )

    return ChainIntegrityResponse(
        status=result.status,
        message=result.message,
        latest_checkpoint=(
            LatestCheckpointSummaryResponse.model_validate(
                result.latest_checkpoint
            )
            if result.latest_checkpoint is not None
            else None
        ),
        chain_depth=result.chain_depth,
        kms_key=(
            KmsKeySummaryResponse.model_validate(result.kms_key)
            if result.kms_key is not None
            else None
        ),
        cadence=result.cadence,
    )
