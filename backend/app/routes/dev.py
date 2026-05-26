"""Dev-only endpoints for local-environment org provisioning (W1.6).

Closes Phase 2 acceptance finding ``v1-register-removed-no-local-replacement``
(High): production org provisioning runs through Clerk webhooks
(``routes/clerk_webhooks.py``), and the legacy ``POST /v1/register``
returns 410 Gone. That left local dev + the simulator's
``bootstrap_orgs.py`` with no API path to create an org.

This router restores a dev-only path:

  * ``POST /v1/dev/orgs``  → creates Organization + ChainState +
                              admin APIKey (and optionally an active
                              BAA + placeholder Customer when
                              ``with_baa=True``). Returns the raw API
                              key ONCE.
  * ``GET /v1/dev/orgs``   → lists orgs (id, name, has_baa) so the
                              bootstrap script can detect a slug that
                              already exists before attempting to
                              create.

**Production safety.** Both routes raise a generic 404 when
``settings.environment != "development"``. This is intentional: a 403
("forbidden") would confirm the endpoint exists and reveal the path
to a probing attacker. A 404 makes the dev surface indistinguishable
from any other unrouted path on a production deployment.

The check happens at request time (not at module load) so the same
binary can be a dev build or a prod build based on the runtime
``ENVIRONMENT`` env var. The router is always registered in ``main.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, settings as global_settings
from ..database import get_db
from ..models import (
    APIKey,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from ..schemas.dev import (
    DevOrgCreateInput,
    DevOrgCreateResponse,
    DevOrgInfo,
    DevOrgListResponse,
)
from ..services.auth import generate_api_key


router = APIRouter(prefix="/dev", tags=["dev"])


def get_settings() -> Settings:
    """Dependency that returns the live ``Settings`` instance.

    Wrapped (rather than importing the module-level singleton directly
    in the handler) so tests can override via
    ``app.dependency_overrides[get_settings]``. The dev endpoints'
    environment check is the only behaviour we need to flip per-test.
    """
    return global_settings


def _require_dev_environment(settings: Settings) -> None:
    """Raise 404 in any non-development environment.

    See module docstring for the 404-vs-403 rationale: we deliberately
    do NOT confirm the endpoint exists in production.
    """
    if settings.environment != "development":
        raise HTTPException(status_code=404, detail="Not Found")


def _now_naive_utc() -> datetime:
    """Naive UTC, matching project convention (see ``services/hashing.py``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _has_active_scoped_baa(session: AsyncSession, org_id: str) -> bool:
    """True if ``org_id`` has at least one ``status='active'`` BAA + scope."""
    row = (
        await session.execute(
            select(BAAAgreement.id)
            .join(BAAScope, BAAScope.baa_agreement_id == BAAAgreement.id)
            .where(
                BAAAgreement.org_id == org_id,
                BAAAgreement.status == "active",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _seed_active_baa(
    session: AsyncSession, org_id: str, org_name: str
) -> None:
    """Create a placeholder Customer + active BAA + wildcard scope.

    Mirrors the workaround at ``/tmp/bootstrap_local.py``: every Phase 2
    gate except ``stale_baa`` requires the org to have at least one
    active+scoped BAA, otherwise Gate 3 fires on everything and the
    acceptance test paths are unreachable. The wildcard scope
    (``is_unrestricted=True``) means ``covered_services`` /
    ``covered_agent_types`` are advisory only — the BAA covers
    everything, which is what local-dev needs.
    """
    tenant_id = f"{org_name}-default-customer"
    customer = (
        await session.execute(
            select(Customer).where(
                Customer.org_id == org_id, Customer.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        customer = Customer(
            org_id=org_id,
            tenant_id=tenant_id,
            display_name=f"{org_name} default customer",
            status="active",
            baa_status="active",
        )
        session.add(customer)
        await session.flush()

    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
        signed_at=now - timedelta(days=1),
    )
    session.add(baa)
    await session.flush()

    scope = BAAScope(
        baa_agreement_id=baa.id,
        is_unrestricted=True,
        covered_services=["*"],
        covered_agent_types=["*"],
        granted_at=now,  # NOT NULL — see ``baa_scope.py`` model docstring
    )
    session.add(scope)


@router.post("/orgs", status_code=201, response_model=DevOrgCreateResponse)
async def create_dev_org(
    payload: DevOrgCreateInput,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DevOrgCreateResponse:
    """Provision a new local-dev org + admin API key.

    Idempotency: relies on the database's UNIQUE constraint on
    ``organizations.name`` (migration ``s9n1o2p3q4r5``). A duplicate
    name surfaces as an ``IntegrityError`` from the flush and is
    translated to a 409 here. We deliberately do NOT do a
    "fetch-then-create" pre-check — that's racy with a sibling
    process — the DB-level constraint is the source of truth.
    """
    _require_dev_environment(settings)

    name = payload.name.strip()
    if not name:
        # Pydantic's min_length=1 catches the empty case, but a string
        # of pure whitespace passes that check and lands here as a
        # zero-length name post-strip. Reject it with the same status
        # the validator would have used so callers can write one error
        # handler.
        raise HTTPException(status_code=422, detail="name cannot be blank")

    org = Organization(name=name)
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        # Unique-name collision. Roll the txn back so the session is
        # usable for any subsequent test fixture teardown.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "org_name_taken",
                "detail": f"An organization named {name!r} already exists.",
            },
        )

    chain = ChainState(org_id=org.id)
    session.add(chain)
    await session.flush()

    raw_key, api_key = await generate_api_key(
        session,
        org_id=org.id,
        name=f"{name}-admin",
        permissions=["read", "write", "admin"],
        kind="test",
    )

    has_baa = False
    if payload.with_baa:
        await _seed_active_baa(session, org.id, name)
        await session.commit()
        # Verify via the same query the gate-3 path would use, so the
        # response is honest about the resulting state.
        has_baa = await _has_active_scoped_baa(session, org.id)
    else:
        await session.commit()

    return DevOrgCreateResponse(
        org_id=org.id,
        name=org.name,
        api_key=raw_key,
        api_key_prefix=api_key.key_prefix,
        has_baa=has_baa,
    )


@router.get("/orgs", response_model=DevOrgListResponse)
async def list_dev_orgs(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    name: str | None = Query(
        default=None,
        description="Filter to orgs with this exact name (case-sensitive).",
    ),
) -> DevOrgListResponse:
    """List dev orgs, optionally filtered to a specific name.

    Used by ``simulator/scripts/bootstrap_orgs.py`` to check whether
    a customer slug already has an org provisioned before attempting
    a create.

    Excludes soft-deleted orgs (``deleted_at IS NOT NULL``) so a
    re-bootstrap after a Clerk-driven org deletion can re-use the
    name. The unique constraint allows this because soft-delete
    leaves the row but the bootstrap's identity check filters it.
    """
    _require_dev_environment(settings)

    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    if name is not None:
        stmt = stmt.where(Organization.name == name)
    rows = (await session.execute(stmt)).scalars().all()

    out: list[DevOrgInfo] = []
    for org in rows:
        has_baa = await _has_active_scoped_baa(session, org.id)
        out.append(DevOrgInfo(org_id=org.id, name=org.name, has_baa=has_baa))
    return DevOrgListResponse(orgs=out)
