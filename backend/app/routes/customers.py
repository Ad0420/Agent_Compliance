"""Customer CRUD endpoints (Phase 1 PR 2, Stream B item B1).

Three endpoints, all scoped to the authenticated org:

  * ``GET    /v1/customers``                — list with paging + filters
  * ``GET    /v1/customers/{tenant_id}``    — single Customer by tenant_id
  * ``PATCH  /v1/customers/{tenant_id}``    — update display_name + contacts

The lifecycle / status / baa_status fields are NOT mutable from this PR;
Phase 1 PR 3 owns lifecycle transitions and PR 10 owns BAA upload. The
PATCH route refuses status/baa_status payloads with 400 so an operator
who mistakenly tries to flip the status from this surface gets a clear
error rather than a silent ignore.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey, Customer
from ..schemas.customer import (
    BAAStatus,
    CustomerListResponse,
    CustomerResponse,
    CustomerStatus,
    CustomerUpdate,
)
from ..services.auth import require_permission

router = APIRouter(prefix="/customers", tags=["customers"])


def _to_response(c: Customer) -> CustomerResponse:
    """Materialise a Customer ORM row as the API response shape.

    ``decision_count_30d`` is always 0 in Phase 1 — the real
    aggregation lands in Phase 2 once we have the per-customer query
    path warm. Surfacing the field today keeps the dashboard contract
    stable across phases.
    """
    return CustomerResponse(
        id=c.id,
        org_id=c.org_id,
        tenant_id=c.tenant_id,
        display_name=c.display_name,
        status=c.status,
        baa_status=c.baa_status,
        contact_email=c.contact_email,
        contact_name=c.contact_name,
        jurisdictions=c.jurisdictions,
        first_seen_at=c.first_seen_at,
        last_seen_at=c.last_seen_at,
        decision_count_30d=0,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    status: Optional[CustomerStatus] = Query(default=None),
    baa_status: Optional[BAAStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """List Customers for the authenticated org.

    Order: most-recently-seen first (NULLs last), then created_at desc.
    Falling back to ``created_at`` keeps freshly-discovered customers
    that have never had a second action visible at the top of the matrix.
    """
    org_id, _ = auth

    base = select(Customer).where(Customer.org_id == org_id)
    count_base = select(func.count(Customer.id)).where(Customer.org_id == org_id)

    if status is not None:
        base = base.where(Customer.status == status)
        count_base = count_base.where(Customer.status == status)
    if baa_status is not None:
        base = base.where(Customer.baa_status == baa_status)
        count_base = count_base.where(Customer.baa_status == baa_status)

    total_result = await session.execute(count_base)
    total = int(total_result.scalar() or 0)

    base = (
        base.order_by(
            Customer.last_seen_at.desc().nullslast(),
            Customer.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(base)).scalars().all()

    return CustomerListResponse(
        items=[_to_response(c) for c in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{tenant_id}", response_model=CustomerResponse)
async def get_customer(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Fetch a single Customer by tenant_id within the authenticated org."""
    org_id, _ = auth
    result = await session.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return _to_response(customer)


@router.patch("/{tenant_id}", response_model=CustomerResponse)
async def update_customer(
    tenant_id: str,
    payload: CustomerUpdate,
    session: AsyncSession = Depends(get_db),
    # ``admin`` permission matches ``organizations.update_alert_email``'s
    # gate. Clerk session admins or API keys with admin scope can mutate;
    # read-only sessions / SDK pilots cannot accidentally rename customers.
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Update display_name + contact fields for a Customer.

    Refuses ``status`` / ``baa_status`` mutations with 400 — those live
    on the Phase 1 PR 3 lifecycle endpoint (status) and PR 10 BAA upload
    flow (baa_status). Allowing them here would let an operator
    side-step the BAA workflow's audit trail.
    """
    org_id, _ = auth

    if payload.status is not None or payload.baa_status is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "status and baa_status are managed by the lifecycle and "
                "BAA upload endpoints, not by PATCH /v1/customers."
            ),
        )

    result = await session.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    # ``model_dump(exclude_unset=True)`` is the partial-update idiom: a
    # caller can clear ``contact_email`` by sending ``null`` (which IS
    # set), but leaving the field out entirely preserves the existing
    # value. The lifecycle / BAA fields are filtered above; everything
    # else flows through.
    patch_data = payload.model_dump(exclude_unset=True)
    for field in ("status", "baa_status"):
        patch_data.pop(field, None)
    for key, value in patch_data.items():
        setattr(customer, key, value)

    await session.commit()
    await session.refresh(customer)
    return _to_response(customer)
