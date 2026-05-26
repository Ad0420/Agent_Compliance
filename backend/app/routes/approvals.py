from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
from ..services.auth import (
    AuthContext,
    require_permission,
    require_permission_with_context,
)
from ..services.iam import IamTier, audit_staff_read, redact_approval

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _approval_response_with_redaction(
    approval, ctx: AuthContext
) -> ApprovalResponse:
    """Build the response, redacting PHI for staff callers.

    Customers see the raw approval row. Staff see ``context.original_input_data``
    stripped from ``context`` and ``data_subject_id`` collapsed to
    ``"[REDACTED]"``. Gate metadata (gate_name, required_role, citation,
    reason) is intact in both cases — that's what staff need to triage a
    ticket.
    """
    if ctx.tier == IamTier.CUSTOMER:
        return ApprovalResponse.model_validate(approval)
    raw = ApprovalResponse.model_validate(approval).model_dump(mode="json")
    return ApprovalResponse.model_validate(redact_approval(raw, ctx.tier))


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
    ctx: AuthContext = Depends(require_permission_with_context("read")),
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
    org_id = ctx.org_id

    # Wave 3A.c. Same PHI side-channel as ``/v1/actions?data_subject_id=`` —
    # a staff member could probe presence of a specific subject without
    # ever seeing the value in the response. Block at the filter layer.
    if ctx.tier == IamTier.STAFF_READ_ONLY and data_subject_id is not None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "staff_phi_filter_forbidden",
                "detail": (
                    "Vera staff sessions cannot filter approvals by "
                    "data_subject_id — it would leak presence of "
                    "specific subjects via timing/count side channel."
                ),
            },
        )

    rows, total = await list_approvals(
        session, org_id, status, risk_tier, data_subject_id, limit, offset
    )
    if ctx.tier == IamTier.STAFF_READ_ONLY:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/approvals",
            org_id=org_id,
            resource_type="approval",
            resource_id=None,
            redacted=True,
        )
    return ApprovalListResponse(
        approvals=[_approval_response_with_redaction(a, ctx) for a in rows],
        total=total,
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval_route(
    approval_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
):
    """Get an approval's current status. SDK polls this until resolved."""
    org_id = ctx.org_id
    approval = await get_approval_with_lazy_expiry(session, org_id, approval_id)
    if ctx.tier == IamTier.STAFF_READ_ONLY:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/approvals/{approval_id}",
            org_id=org_id,
            resource_type="approval",
            resource_id=approval_id,
            redacted=True,
        )
    return _approval_response_with_redaction(approval, ctx)


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
    # api_key is None for Clerk-authenticated requests; use a generic label
    # so the audit row still records the channel even without a key prefix.
    canceller = (
        f"api_key:{api_key.key_prefix}" if api_key is not None else "dashboard"
    )
    approval = await cancel_approval(
        session, org_id, approval_id, canceller=canceller
    )
    return ApprovalResponse.model_validate(approval)
