from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.approval import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalResponse,
)
from ..services.approvals import (
    cancel_approval,
    decide_approval,
    get_approval_with_lazy_expiry,
    list_approvals,
    request_approval,
)
from ..services.auth import require_permission

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("", response_model=ApprovalResponse, status_code=201)
async def create_approval(
    data: ApprovalCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("write")),
):
    """Agent requests human approval for a pending action.

    Writes a pending ActionRecord to the chain and returns the approval row.
    The agent SDK then polls GET /approvals/{id} until status changes.
    """
    org_id, _ = auth
    approval = await request_approval(session, org_id, data)
    return ApprovalResponse.model_validate(approval)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals_route(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("read")),
    status: Optional[str] = Query(
        default=None, pattern="^(pending|approved|rejected|expired|cancelled)$"
    ),
    risk_tier: Optional[str] = Query(
        default=None, pattern="^(low|medium|high|critical)$"
    ),
    data_subject_id: Optional[str] = Query(default=None, max_length=500),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List approvals with optional filters (status, risk_tier, data_subject_id)."""
    org_id, _ = auth
    rows, total = await list_approvals(
        session, org_id, status, risk_tier, data_subject_id, limit, offset
    )
    return ApprovalListResponse(
        approvals=[ApprovalResponse.model_validate(a) for a in rows],
        total=total,
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval_route(
    approval_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("read")),
):
    """Get an approval's current status. SDK polls this until resolved."""
    org_id, _ = auth
    approval = await get_approval_with_lazy_expiry(session, org_id, approval_id)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval_route(
    approval_id: str,
    data: ApprovalDecision,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Human reviewer approves or rejects. Requires admin key for MVP.

    EU AI Act Art. 14: for dual-verification (approvers_required=2),
    two distinct approvers must each vote approve before status becomes 'approved'.
    Any single 'reject' vote immediately rejects the approval.
    """
    org_id, _ = auth
    approval = await decide_approval(session, org_id, approval_id, data)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/cancel", response_model=ApprovalResponse)
async def cancel_approval_route(
    approval_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Cancel a pending approval. Writes a resolution record to the chain."""
    org_id, api_key = auth
    approval = await cancel_approval(
        session, org_id, approval_id, canceller=f"api_key:{api_key.key_prefix}"
    )
    return ApprovalResponse.model_validate(approval)
