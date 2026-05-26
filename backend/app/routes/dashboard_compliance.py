"""Dashboard-namespaced routes for the compliance reviewer surface
(Workstream F1 + F3).

These are thin Clerk-authenticated wrappers around existing services so the
``/v1/dashboard/*`` boundary stays the human/Clerk side and the legacy
``/v1/*`` routes stay the SDK/API-key side. The split is deliberate — see
``backend/app/middleware/clerk_auth.py`` for the rationale.

Two flavours of route live here:

1. **Mirror routes** that compliance reviewers (and developers/admins)
   use to read records, approvals, violations, and exports. These wear
   the ``compliance_review_audit`` dependency so every reviewer hit is
   logged to ``compliance_review_records`` (F3).

2. **Compliance-dashboard data routes** under
   ``/v1/dashboard/compliance/*`` that Phase 4b's UI will call to build
   summary cards, recent-risk lists, exports list, and the review-trail
   itself. These wear ``compliance_review_audit(..., exclude_path_audit=True)``
   so a reviewer reading their own log doesn't generate a fresh row on
   every page refresh (audit-loop bug).

Single-dep pattern: each audited route accepts ONE dependency,
``compliance_review_audit([...])``. FastAPI's dependency DAG dedupes the
underlying ``require_clerk_role`` call so RBAC enforcement still happens
once per request — but routes no longer declare the role check twice
(once in ``dependencies=[]``, once as a param), which was running the
membership lookup + Clerk freshness re-check redundantly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.clerk_auth import compliance_review_audit
from ..models import (
    ActionRecord,
    Approval,
    ComplianceReviewRecord,
    PolicyViolation,
)
from ..schemas.action import ActionRecordListResponse, ActionRecordResponse
from ..schemas.approval import ApprovalListResponse, ApprovalResponse
from ..services.dashboard_views import serialize_approval_for_dashboard
from ..services.export import generate_pdf, stream_csv
from ..services.verification import verify_chain


# Broad reader tier — admin, developer, compliance_reviewer all read.
_READ_ROLES = ["admin", "developer", "compliance_reviewer"]
# Review-trail / audit-of-audit data is admin + compliance_reviewer only.
# Developers don't get a "look at my colleague's audit trail" surface.
_REVIEW_TRAIL_ROLES = ["admin", "compliance_reviewer"]


def _utcnow_naive() -> datetime:
    """Tz-aware UTC, stripped to naïve for the DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_to_response(record: ActionRecord) -> ActionRecordResponse:
    """Mirror of ``routes/actions._record_to_response``. We can't import the
    actions module directly without dragging in the API-key dependency
    chain, and SQLAlchemy's ``metadata`` attribute on the declarative base
    shadows ``ActionRecord.metadata_`` for ``from_attributes`` mapping —
    so we build the response by hand here too."""
    return ActionRecordResponse(
        id=record.id,
        org_id=record.org_id,
        sequence_number=record.sequence_number,
        previous_hash=record.previous_hash,
        record_hash=record.record_hash,
        recorded_at=record.recorded_at,
        agent_name=record.agent_name,
        agent_version=record.agent_version,
        agent_id=record.agent_id,
        data_subject_id=record.data_subject_id,
        model_id=record.model_id,
        model_version=record.model_version,
        framework=record.framework,
        framework_version=record.framework_version,
        action_type=record.action_type,
        action_name=record.action_name,
        action_description=record.action_description,
        action_timestamp=record.action_timestamp,
        target_system=record.target_system,
        target_resource=record.target_resource,
        authorized_by=record.authorized_by,
        authorization_scope=record.authorization_scope,
        delegation_chain=record.delegation_chain or [],
        result=record.result,
        error_message=record.error_message,
        duration_ms=record.duration_ms,
        input_data=record.input_data or {},
        policies_applied=record.policies_applied or [],
        environment=record.environment or {},
        outcome=record.outcome or {},
        reasoning=record.reasoning or {},
        metadata=record.metadata_ or {},
    )


router = APIRouter(prefix="/v1/dashboard", tags=["dashboard-compliance"])


# ── Mirror routes (audited when called by compliance_reviewer) ──────────────


@router.get(
    "/actions",
    response_model=ActionRecordListResponse,
)
async def dashboard_list_actions(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    agent_name: Optional[str] = None,
    action_type: Optional[str] = None,
    result: Optional[str] = None,
    data_subject_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> ActionRecordListResponse:
    """List action records scoped to the active Clerk org. Read-only.

    Mirrors ``GET /v1/actions`` (the API-key-auth route) but uses Clerk
    auth and runs through the compliance audit dependency when the caller
    is a reviewer."""
    org_id = ctx["org_id"]
    query = select(ActionRecord).where(ActionRecord.org_id == org_id)
    count_query = select(func.count(ActionRecord.id)).where(
        ActionRecord.org_id == org_id
    )
    if agent_name:
        query = query.where(ActionRecord.agent_name == agent_name)
        count_query = count_query.where(ActionRecord.agent_name == agent_name)
    if action_type:
        query = query.where(ActionRecord.action_type == action_type)
        count_query = count_query.where(ActionRecord.action_type == action_type)
    if result:
        query = query.where(ActionRecord.result == result)
        count_query = count_query.where(ActionRecord.result == result)
    if data_subject_id:
        query = query.where(ActionRecord.data_subject_id == data_subject_id)
        count_query = count_query.where(
            ActionRecord.data_subject_id == data_subject_id
        )
    if start_date:
        query = query.where(ActionRecord.action_timestamp >= start_date)
        count_query = count_query.where(ActionRecord.action_timestamp >= start_date)
    if end_date:
        query = query.where(ActionRecord.action_timestamp <= end_date)
        count_query = count_query.where(ActionRecord.action_timestamp <= end_date)

    total = (await session.execute(count_query)).scalar() or 0
    query = (
        query.order_by(ActionRecord.sequence_number.desc()).limit(limit).offset(offset)
    )
    records = (await session.execute(query)).scalars().all()
    return ActionRecordListResponse(
        records=[_record_to_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/actions/{record_id}",
    response_model=ActionRecordResponse,
)
async def dashboard_get_action(
    record_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
) -> ActionRecordResponse:
    org_id = ctx["org_id"]
    row = (
        await session.execute(
            select(ActionRecord).where(
                ActionRecord.id == record_id, ActionRecord.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Action record not found")
    return _record_to_response(row)


@router.get(
    "/approvals",
    response_model=ApprovalListResponse,
)
async def dashboard_list_approvals(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    status: Optional[str] = Query(
        default=None, pattern="^(pending|approved|rejected|expired|cancelled)$"
    ),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApprovalListResponse:
    org_id = ctx["org_id"]
    query = select(Approval).where(Approval.org_id == org_id)
    count_query = select(func.count(Approval.id)).where(Approval.org_id == org_id)
    if status:
        query = query.where(Approval.status == status)
        count_query = count_query.where(Approval.status == status)
    total = (await session.execute(count_query)).scalar() or 0
    query = query.order_by(Approval.requested_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(query)).scalars().all()
    # W2.2 — this route is dashboard-only (Clerk-gated under
    # ``/v1/dashboard/*``); apply the same PHI-strip serializer used by
    # the API-key-shared ``/v1/approvals`` route when called via Clerk
    # session. The ``dashboard_compliance`` namespace doesn't see SDK
    # callers, so the strip is unconditional here.
    return ApprovalListResponse(
        approvals=[
            ApprovalResponse.model_validate(serialize_approval_for_dashboard(r))
            for r in rows
        ],
        total=total,
    )


@router.get(
    "/approvals/{approval_id}",
    response_model=ApprovalResponse,
)
async def dashboard_get_approval(
    approval_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
) -> ApprovalResponse:
    org_id = ctx["org_id"]
    row = (
        await session.execute(
            select(Approval).where(
                Approval.id == approval_id, Approval.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    # W2.2 — same PHI strip as the list route above.
    return ApprovalResponse.model_validate(serialize_approval_for_dashboard(row))


@router.get("/violations")
async def dashboard_list_violations(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    severity: Optional[str] = Query(
        default=None, pattern="^(critical|high|medium|low)$"
    ),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    org_id = ctx["org_id"]
    query = select(PolicyViolation).where(PolicyViolation.org_id == org_id)
    count_query = select(func.count(PolicyViolation.id)).where(
        PolicyViolation.org_id == org_id
    )
    if severity:
        query = query.where(PolicyViolation.severity == severity)
        count_query = count_query.where(PolicyViolation.severity == severity)
    total = (await session.execute(count_query)).scalar() or 0
    query = (
        query.order_by(PolicyViolation.triggered_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(query)).scalars().all()
    return {
        "violations": [
            {
                "id": v.id,
                "policy_id": v.policy_id,
                "record_id": v.record_id,
                "severity": v.severity,
                "triggered_at": v.triggered_at.isoformat() if v.triggered_at else None,
                "context": v.context,
                "resolved_at": v.resolved_at.isoformat() if v.resolved_at else None,
                "resolved_by": v.resolved_by,
            }
            for v in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/export/pdf")
async def dashboard_export_pdf(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    action_type: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
):
    org_id = ctx["org_id"]
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "agent_name": agent_name,
        "action_type": action_type,
        "result": result,
    }
    timestamp = _utcnow_naive().strftime("%Y%m%d_%H%M%S")
    filename = f"vera_report_{timestamp}.pdf"
    pdf_bytes = await generate_pdf(session, org_id, filters)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/csv")
async def dashboard_export_csv(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    action_type: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    limit: int = Query(default=5000, le=10_000, ge=1),
):
    org_id = ctx["org_id"]
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "agent_name": agent_name,
        "action_type": action_type,
        "result": result,
        "limit": limit,
    }
    timestamp = _utcnow_naive().strftime("%Y%m%d_%H%M%S")
    filename = f"vera_export_{timestamp}.csv"
    return StreamingResponse(
        stream_csv(session, org_id, filters),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/verify/chain")
async def dashboard_verify_chain(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    start_seq: Optional[int] = Query(default=None),
    end_seq: Optional[int] = Query(default=None),
) -> dict:
    org_id = ctx["org_id"]
    result = await verify_chain(session, org_id, start_seq, end_seq)
    return {
        "is_valid": result.is_valid,
        "records_checked": result.records_checked,
        "first_invalid_sequence": result.first_invalid_sequence,
        "message": result.message,
    }


@router.get("/data-subjects/{data_subject_id}")
async def dashboard_get_data_subject(
    data_subject_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(compliance_review_audit(_READ_ROLES)),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """GDPR/HIPAA right-of-access lookup — all records mentioning this
    data subject. Every hit is audited so the org can prove which
    reviewer pulled what subject's data.

    Note: ``data_subject_id`` is treated as PHI by the audit middleware —
    the value is HMAC-hashed before it lands in
    ``compliance_review_records.target_id`` / ``http_path``. Analysts can
    still correlate within an org (same subject + same org → same hash)
    but cannot reverse-engineer the raw identifier from a stolen audit
    table.
    """
    org_id = ctx["org_id"]
    actions_q = (
        select(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.data_subject_id == data_subject_id,
        )
        .order_by(ActionRecord.sequence_number.desc())
        .limit(limit)
        .offset(offset)
    )
    actions = (await session.execute(actions_q)).scalars().all()
    return {
        "data_subject_id": data_subject_id,
        "actions": [_record_to_response(a).model_dump() for a in actions],
        "count": len(actions),
    }


# ── Compliance dashboard data routes (Phase 4b will consume) ────────────────
#
# These routes have ``exclude_path_audit=True``: role gating still happens
# but no compliance review record is written. The reasoning:
#
#   /summary       — page-view metadata, low audit value, fires on every
#                    dashboard refresh.
#   /recent        — same; renders the dashboard hero list.
#   /exports       — surfacing PAST exports is itself non-PHI. The export
#                    rows are already audited via the underlying
#                    /v1/dashboard/export/{pdf,csv} hits.
#   /review-trail  — the audit-loop endpoint. A compliance_reviewer
#                    paging through THEIR OWN audit log must NOT generate
#                    fresh rows on every refresh (CRITICAL #3).

compliance_router = APIRouter(
    prefix="/v1/dashboard/compliance", tags=["dashboard-compliance"]
)


@compliance_router.get("/summary")
async def compliance_summary(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(
        compliance_review_audit(_READ_ROLES, exclude_path_audit=True)
    ),
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """30-day rollup the compliance landing page uses for its hero
    cards: count of high-risk decisions, HITL approvals taken, and
    policy violations."""
    org_id = ctx["org_id"]
    cutoff = _utcnow_naive() - timedelta(days=days)

    high_risk_approvals_q = select(func.count(Approval.id)).where(
        Approval.org_id == org_id,
        Approval.requested_at >= cutoff,
        Approval.risk_tier.in_(["high", "critical"]),
    )
    hitl_taken_q = select(func.count(Approval.id)).where(
        Approval.org_id == org_id,
        Approval.requested_at >= cutoff,
        Approval.status.in_(["approved", "rejected"]),
    )
    violations_q = select(func.count(PolicyViolation.id)).where(
        PolicyViolation.org_id == org_id,
        PolicyViolation.triggered_at >= cutoff,
    )

    return {
        "window_days": days,
        "high_risk_decisions": (await session.execute(high_risk_approvals_q)).scalar() or 0,
        "hitl_approvals_taken": (await session.execute(hitl_taken_q)).scalar() or 0,
        "policy_violations": (await session.execute(violations_q)).scalar() or 0,
    }


@compliance_router.get("/recent")
async def compliance_recent(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(
        compliance_review_audit(_READ_ROLES, exclude_path_audit=True)
    ),
    limit: int = Query(default=20, le=100),
) -> dict:
    """Last N records that either failed, were blocked, or triggered a
    policy violation. Surfaces what compliance needs to look at first."""
    org_id = ctx["org_id"]
    actions_q = (
        select(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.result.in_(["failure", "blocked"]),
        )
        .order_by(ActionRecord.sequence_number.desc())
        .limit(limit)
    )
    actions = (await session.execute(actions_q)).scalars().all()
    return {
        "records": [_record_to_response(a).model_dump() for a in actions],
        "count": len(actions),
    }


@compliance_router.get("/exports")
async def compliance_exports(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(
        compliance_review_audit(_READ_ROLES, exclude_path_audit=True)
    ),
    limit: int = Query(default=50, le=200),
) -> dict:
    """List of recent PDF/CSV exports the org has generated. We don't
    store the exported bytes — we read the compliance review log for
    rows whose http_path is an export endpoint."""
    org_id = ctx["org_id"]
    rows = (
        await session.execute(
            select(ComplianceReviewRecord)
            .where(
                ComplianceReviewRecord.org_id == org_id,
                ComplianceReviewRecord.http_path.like("%/export/%"),
            )
            .order_by(ComplianceReviewRecord.occurred_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "exports": [
            {
                "id": r.id,
                "path": r.http_path,
                "clerk_user_id": r.clerk_user_id,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "query_params": r.query_params,
                "response_metadata": r.response_metadata,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@compliance_router.get("/review-trail")
async def compliance_review_trail(
    session: AsyncSession = Depends(get_db),
    # Reviewers can see their own trail; admins can see the team's. Developers
    # are NOT a recorded role and don't need this view per F3 spec.
    # ``exclude_path_audit=True`` prevents the audit-loop: a reviewer paging
    # through their own log otherwise generates a new row per request.
    ctx: dict = Depends(
        compliance_review_audit(
            _REVIEW_TRAIL_ROLES, exclude_path_audit=True
        )
    ),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    org_id = ctx["org_id"]
    rows = (
        await session.execute(
            select(ComplianceReviewRecord)
            .where(ComplianceReviewRecord.org_id == org_id)
            .order_by(ComplianceReviewRecord.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "membership_id": r.membership_id,
                "clerk_user_id": r.clerk_user_id,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "query_params": r.query_params,
                "response_metadata": r.response_metadata,
                "http_method": r.http_method,
                "http_path": r.http_path,
                "request_id": r.request_id,
                "ip_address": r.ip_address,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


__all__ = ["router", "compliance_router"]
