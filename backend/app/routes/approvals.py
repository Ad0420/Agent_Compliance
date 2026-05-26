from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey
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
from ..services.iam import audit_staff_read, redact_approval
from ..services.dashboard_views import (
    is_dashboard_request,
    serialize_approval_for_dashboard,
)

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

    Per Wave 3B.3 policy, we branch on ``ctx.is_customer`` so a future
    STAFF_FULL tier is redacted identically to STAFF_READ_ONLY without
    a per-route fix.
    """
    if ctx.is_customer:
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
    """List approvals with optional filters (status, risk_tier, data_subject_id).

    Three layers of PHI handling stack here:

    * **Vera staff** (Wave 3A.c — IamTier.STAFF_READ_ONLY): redact via
      ``redact_approval`` + write an audit log row. Filter-by-
      ``data_subject_id`` rejected as a PHI side-channel.
    * **Customer dashboard via Clerk** (W1.2 HIPAA minimum-necessary):
      strip ``Approval.context.original_input_data``, ``data_subject_id``,
      ``action_summary`` via ``serialize_approval_for_dashboard``.
    * **Customer SDK via API key**: full shape — needed for HITL polling.
    """
    org_id = ctx.org_id

    # Wave 3A.c — staff PHI filter side-channel guard.
    if ctx.is_staff and data_subject_id is not None:
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
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/approvals",
            org_id=org_id,
            resource_type="approval",
            resource_id=None,
            resource_count=len(rows),
            redacted=True,
        )
        approvals = [_approval_response_with_redaction(a, ctx) for a in rows]
    elif is_dashboard_request(ctx.api_key):
        # W1.2 — Clerk dashboard caller, strip PHI carriers.
        approvals = [
            ApprovalResponse.model_validate(serialize_approval_for_dashboard(a))
            for a in rows
        ]
    else:
        # Customer SDK via API key — full shape.
        approvals = [ApprovalResponse.model_validate(a) for a in rows]
    return ApprovalListResponse(approvals=approvals, total=total)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval_route(
    approval_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
):
    """Get an approval's current status. SDK polls this until resolved.

    PHI handling stacks identically to the list endpoint:
    Vera staff → ``redact_approval``; Clerk dashboard → dashboard strip;
    customer SDK → full shape.
    """
    org_id = ctx.org_id
    approval = await get_approval_with_lazy_expiry(session, org_id, approval_id)
    if ctx.is_staff:
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
    if is_dashboard_request(ctx.api_key):
        return ApprovalResponse.model_validate(
            serialize_approval_for_dashboard(approval)
        )
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval_route(
    approval_id: str,
    data: ApprovalDecision,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("write")),
):
    """Human reviewer approves or rejects.

    EU AI Act Art. 14: for dual-verification (approvers_required=2),
    two distinct approvers must each vote approve before status becomes 'approved'.
    Any single 'reject' vote immediately rejects the approval.

    Wave 2D follow-up W1.1 — auth relaxation
    ----------------------------------------
    Permission relaxed from ``admin`` → ``write``. Closes
    phase2-acceptance-findings
    ``require_permission-admin-too-strict-on-decide`` (Medium): real
    reviewers (attending physicians, nurses, etc.) should never need
    admin keys to register a decision. The security boundary is now
    the reviewer-role check inside
    ``services.approvals.decide_approval`` — when the approval is
    gated, the request must supply a ``reviewer_role`` that satisfies
    ``Approval.context.required_role``; insufficient roles are
    rejected 403 with an audit record + ``reviewed_below_threshold``
    flag flip. The API-key permission only gates *whether* the caller
    can hit the endpoint at all; the role check gates *which*
    decisions they can record on gated approvals.
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
