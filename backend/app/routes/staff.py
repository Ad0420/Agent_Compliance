"""Staff audit log endpoint (Wave 3A.c — IAM hardening).

Single read-only endpoint exposing rows from ``staff_audit_log``:

  * ``GET /v1/staff/audit-log``

Two access patterns share the endpoint:

  * **Staff caller** (Vera Clerk session, tier=STAFF_READ_ONLY): see
    their own activity. Filtered server-side to ``staff_id == ctx.staff_id``.
    They MAY filter by ``org_id`` to scope to one customer.

  * **Customer admin** (API key with ``admin`` permission, or
    Clerk customer-org admin): see which Vera staff have read THEIR org's
    data. Filtered server-side to ``org_id == ctx.org_id``. They MAY
    filter by ``staff_id`` to scope to one engineer.

Cross-tier isolation is enforced server-side — never trust a client
query parameter to widen the scope. The audit log is per-org by design:
customer A's admin can never see reads on customer B's org even if they
pass ``?org_id=B``.

Non-admin customer callers receive a 403. Staff never receive 403 on
this endpoint — they always have access to their own activity.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import StaffAuditLog
from ..services.auth import AuthContext, require_staff_or_customer_admin
from ..services.iam import IamTier


router = APIRouter(prefix="/staff", tags=["staff"])


class StaffAuditLogEntry(BaseModel):
    """One row from ``staff_audit_log``, surfaced to the caller."""

    model_config = {"from_attributes": True}

    id: str
    staff_id: str
    endpoint: str
    org_id: str
    resource_type: str
    resource_id: Optional[str] = None
    redacted: bool
    read_at: datetime


class StaffAuditLogListResponse(BaseModel):
    entries: list[StaffAuditLogEntry]
    total: int
    limit: int
    offset: int


@router.get("/audit-log", response_model=StaffAuditLogListResponse)
async def list_staff_audit_log(
    staff_id: Optional[str] = Query(default=None, max_length=128),
    org_id: Optional[str] = Query(default=None, max_length=36),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_staff_or_customer_admin()),
):
    """List staff-read audit entries.

    Authorization model:
      * Customer admin (CUSTOMER tier with ``admin`` permission) — sees
        reads against THEIR org_id. The ``org_id`` query param is
        ignored if it doesn't match; the dependency already proved the
        caller is admin of ``ctx.org_id``. Optional ``staff_id`` filter
        narrows to one engineer.
      * Staff (STAFF_READ_ONLY tier) — sees THEIR own activity. The
        ``staff_id`` query param is ignored. Optional ``org_id`` filter
        scopes to one customer they've touched.
      * Customer non-admin — 403 (the dependency rejected ``admin``
        already; this branch is unreachable in v1).

    The audit-log read itself is NOT itself audit-logged (no infinite
    regress; reads of the log are an internal SOC concern, not a
    data-access event).
    """
    # Build the filter predicate once so the rows query and the count
    # query use the same WHERE. Server-side scoping (staff_id for staff,
    # org_id for customer admin) is non-negotiable — we never read client
    # params for the scoping anchor.
    filters = []
    if ctx.tier == IamTier.STAFF_READ_ONLY:
        if not ctx.staff_id:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session"
            )
        filters.append(StaffAuditLog.staff_id == ctx.staff_id)
        if org_id:
            filters.append(StaffAuditLog.org_id == org_id)
    else:
        # Customer admin: scope to own org. The org_id query param is
        # ignored; the caller's own org is the only allowed scope.
        filters.append(StaffAuditLog.org_id == ctx.org_id)
        if staff_id:
            filters.append(StaffAuditLog.staff_id == staff_id)

    count_query = select(func.count(StaffAuditLog.id)).where(*filters)
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    rows_query = (
        select(StaffAuditLog)
        .where(*filters)
        .order_by(StaffAuditLog.read_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(rows_query)
    rows = result.scalars().all()

    return StaffAuditLogListResponse(
        entries=[StaffAuditLogEntry.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
