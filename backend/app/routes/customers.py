"""Customer CRUD endpoints (Phase 1 PR 2 + PR 13, Stream B item B1, Stream F item F2/F3/F4).

Six endpoints, all scoped to the authenticated org:

  * ``GET    /v1/customers``                       — list with paging + filters
  * ``GET    /v1/customers/{tenant_id}``           — single Customer by tenant_id
  * ``PATCH  /v1/customers/{tenant_id}``           — update display_name + contacts
  * ``GET    /v1/customers/{tenant_id}/agents``    — AI Coverage Matrix rows (PR 13)
  * ``POST   /v1/customers/{tenant_id}/baa``       — upload signed BAA (PR 13)
  * (``GET   /v1/customers?with_counts=1``)        — list with decision counts (PR 13)

The lifecycle / status / baa_status fields are NOT mutable from PATCH;
Phase 1 PR 3 owns lifecycle transitions and the BAA upload endpoint
below owns ``baa_status`` flips. The PATCH route refuses status/baa_status
payloads with 400 so an operator who mistakenly tries to flip the status
from that surface gets a clear error rather than a silent ignore.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    ActionRecord,
    APIKey,
    BAAAgreement,
    BAAScope,
    Customer,
    CustomerAgent,
)
from ..schemas.customer import (
    BAAStatus,
    BAAUploadRequest,
    BAAUploadResponse,
    CustomerAgentCoverage,
    CustomerAgentsResponse,
    CustomerListResponse,
    CustomerResponse,
    CustomerStatus,
    CustomerUpdate,
)
from ..services.auth import require_permission
from ..services.baa import invalidate_org_baa_cache

router = APIRouter(prefix="/customers", tags=["customers"])


def _naive_utc_now() -> datetime:
    """Return tz-naive UTC ``datetime`` matching the DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_response(c: Customer, *, decision_count_30d: int = 0) -> CustomerResponse:
    """Materialise a Customer ORM row as the API response shape.

    ``decision_count_30d`` defaults to 0 (cheap path used by the
    PATCH/GET-by-id routes that don't need the rollup). The list
    endpoint can opt into ``with_counts=1`` to compute it in a single
    batched query (see ``_decision_counts_for_customers``).
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
        decision_count_30d=decision_count_30d,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _decision_counts_for_customers(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_ids: list[str],
) -> dict[str, int]:
    """Batched COUNT(*) of last-30d ActionRecords grouped by tenant_id.

    One DB round-trip regardless of how many customers we're rolling up.
    Without this, the list endpoint would N+1 the action_records table.
    Empty input returns an empty dict.
    """
    if not tenant_ids:
        return {}
    since = _naive_utc_now() - timedelta(days=30)
    stmt = (
        select(ActionRecord.tenant_id, func.count(ActionRecord.id))
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id.in_(tenant_ids),
            ActionRecord.recorded_at >= since,
        )
        .group_by(ActionRecord.tenant_id)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    status: Optional[CustomerStatus] = Query(default=None),
    baa_status: Optional[BAAStatus] = Query(default=None),
    with_counts: bool = Query(
        default=False,
        description=(
            "When true, populates decision_count_30d for each row via a "
            "single batched COUNT(*) over action_records. Off by default "
            "so the Home page's tiny list remains cheap."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """List Customers for the authenticated org.

    Order: most-recently-seen first (NULLs last), then created_at desc.
    Falling back to ``created_at`` keeps freshly-discovered customers
    that have never had a second action visible at the top of the matrix.

    PR 13: ``with_counts=1`` opts into a per-row 30-day decision rollup.
    Implemented as a single batched COUNT(*) so the dashboard's Customers
    page doesn't pay an N+1 cost.
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

    counts: dict[str, int] = {}
    if with_counts and rows:
        counts = await _decision_counts_for_customers(
            session,
            org_id=org_id,
            tenant_ids=[c.tenant_id for c in rows],
        )

    return CustomerListResponse(
        items=[
            _to_response(c, decision_count_30d=counts.get(c.tenant_id, 0))
            for c in rows
        ],
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
    """Fetch a single Customer by tenant_id within the authenticated org.

    Always populates ``decision_count_30d`` — the Customer detail page
    needs it on every render to drive the "populated vs pending_setup"
    variant choice. One extra COUNT(*) per fetch is negligible.
    """
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
    counts = await _decision_counts_for_customers(
        session, org_id=org_id, tenant_ids=[customer.tenant_id]
    )
    return _to_response(
        customer, decision_count_30d=counts.get(customer.tenant_id, 0)
    )


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


# ── PR 13: AI Coverage Matrix per-customer agents ────────────────────────


async def _resolve_customer_or_404(
    session: AsyncSession, *, org_id: str, tenant_id: str
) -> Customer:
    """Common org-scoped lookup used by the /agents and /baa sub-routes."""
    result = await session.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.get("/{tenant_id}/agents", response_model=CustomerAgentsResponse)
async def list_customer_agents(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Return AI Coverage Matrix rows for the given customer.

    One ``CustomerAgentCoverage`` per ``CustomerAgent`` row. The
    Phase-1 columns are computed inline:

    * ``coverage`` is ``"covered"`` when ``status == 'active'`` else
      ``"none"``. Partial coverage is a Phase 2 concept once scoped
      BAAs land; surfacing the literal anyway keeps the dashboard
      contract stable.
    * ``has_capture`` is True iff at least one ActionRecord exists for
      the (org_id, tenant_id) pair. We collapse to a single boolean
      rather than agent-type-scoped match because ActionRecord doesn't
      carry ``agent_type`` directly today (it carries ``action_class``
      which the auto-discovery service maps); a per-agent_type roll-up
      lives in Phase 2 alongside gate execution.
    * ``hitl_gate_count``, ``pdf_included``, ``posture_included``: 0 /
      False — populated in Phases 2/4 respectively.
    """
    org_id, _ = auth
    customer = await _resolve_customer_or_404(
        session, org_id=org_id, tenant_id=tenant_id
    )

    rows = (
        await session.execute(
            select(CustomerAgent)
            .where(CustomerAgent.customer_id == customer.id)
            .order_by(CustomerAgent.last_seen_at.desc())
        )
    ).scalars().all()

    # Single capture check for the whole customer — cheap with the
    # idx_ar_org_tenant_seq index. We could split per agent_type but
    # Phase 1 has no public agent_type column on ActionRecord so the
    # boolean is the only honest answer today.
    capture_stmt = (
        select(ActionRecord.id)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id == customer.tenant_id,
        )
        .limit(1)
    )
    has_capture = (
        await session.execute(capture_stmt)
    ).scalar_one_or_none() is not None

    items: list[CustomerAgentCoverage] = []
    for r in rows:
        items.append(
            CustomerAgentCoverage(
                id=r.id,
                agent_type=r.agent_type,
                agent_id=r.agent_id,
                source=r.source,  # type: ignore[arg-type]
                confidence=r.confidence,  # type: ignore[arg-type]
                status=r.status,  # type: ignore[arg-type]
                first_seen_at=r.first_seen_at,
                last_seen_at=r.last_seen_at,
                coverage="covered" if r.status == "active" else "none",
                has_capture=has_capture,
                hitl_gate_count=0,
                pdf_included=False,
                posture_included=False,
            )
        )
    return CustomerAgentsResponse(items=items, total=len(items))


# ── PR 13: BAA upload (Phase 1 acceptance gate) ──────────────────────────


@router.post(
    "/{tenant_id}/baa",
    response_model=BAAUploadResponse,
    status_code=201,
)
async def upload_customer_baa(
    tenant_id: str,
    payload: BAAUploadRequest,
    session: AsyncSession = Depends(get_db),
    # Admin permission matches the PATCH route — uploading a BAA is a
    # legal-weight action and must not be available to read-only sessions
    # or SDK keys with only ``write`` scope.
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Attach a signed BAA to the given customer.

    Phase 1 contract:

    * Creates a ``BAAAgreement`` row with ``status='active'`` (the
      operator is uploading a signed PDF — there is no draft state to
      represent from the dashboard).
    * Creates exactly one ``BAAScope`` row. Defaults to
      ``is_unrestricted=True`` per the wizard spec; Phase 2 will let
      callers narrow ``covered_services`` / ``covered_agent_types``.
    * Flips the Customer's ``baa_status`` to ``active`` and, if the
      Customer was ``pending_setup``, advances ``status`` to ``active``
      (the BAA is the gating piece of the "complete setup" wizard —
      flipping both fields atomically here keeps the dashboard from
      flickering between intermediate states).
    * Invalidates the org's BAA freshness cache so the next live-key
      authenticated request reflects the new BAA without waiting up to
      60 s for the TTL (per ``services/baa.py``'s PR 10 TODO).

    The upload itself (multipart → S3) is deferred to a follow-up. The
    Phase 1 acceptance gate ("one BAA upload completes setup") is met
    by the schema change + cache invalidation; the document_uri may be
    a pre-signed S3 link supplied by the dashboard widget.
    """
    org_id, _ = auth
    customer = await _resolve_customer_or_404(
        session, org_id=org_id, tenant_id=tenant_id
    )

    now = _naive_utc_now()
    effective_at = payload.effective_at.replace(tzinfo=None) if (
        payload.effective_at and payload.effective_at.tzinfo
    ) else payload.effective_at
    expires_at = payload.expires_at.replace(tzinfo=None) if (
        payload.expires_at and payload.expires_at.tzinfo
    ) else payload.expires_at
    signed_at = payload.signed_at.replace(tzinfo=None) if (
        payload.signed_at and payload.signed_at.tzinfo
    ) else payload.signed_at

    # Temporal sanity. The ck_baa_temporal_order CHECK accepts NULL on
    # either side but rejects effective_at > expires_at. We catch it up
    # front so the dashboard gets a 400 with a usable message instead of
    # a 500 from the DB.
    if (
        effective_at is not None
        and expires_at is not None
        and effective_at > expires_at
    ):
        raise HTTPException(
            status_code=400,
            detail="effective_at must be on or before expires_at",
        )

    agreement = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        document_uri=payload.document_uri.strip(),
        effective_at=effective_at,
        expires_at=expires_at,
        signed_at=signed_at or now,
        status="active",
    )
    session.add(agreement)
    await session.flush()  # populate agreement.id before scope insert

    scope = BAAScope(
        baa_agreement_id=agreement.id,
        covered_services=payload.covered_services or [],
        covered_agent_types=payload.covered_agent_types or [],
        is_unrestricted=payload.is_unrestricted,
        granted_at=signed_at or now,
    )
    session.add(scope)

    # Flip customer status. The "BAA in effect" status feeds the dashboard
    # row colour + unblocks PDF generation in later phases; flipping
    # ``status`` from ``pending_setup`` to ``active`` here is the
    # acceptance-gate "complete setup" semantic.
    customer.baa_status = "active"
    if customer.status == "pending_setup":
        customer.status = "active"

    await session.commit()
    await session.refresh(agreement)
    await session.refresh(scope)
    await session.refresh(customer)

    # Cache invalidation MUST happen AFTER the commit lands — otherwise a
    # racing live-key request could repopulate the cache from a not-yet
    # committed row and we'd ship the stale "no BAA" result.
    invalidate_org_baa_cache(org_id)

    return BAAUploadResponse(
        agreement_id=agreement.id,
        scope_id=scope.id,
        customer_baa_status=customer.baa_status,  # type: ignore[arg-type]
        customer_status=customer.status,  # type: ignore[arg-type]
        effective_at=agreement.effective_at,
        expires_at=agreement.expires_at,
    )
