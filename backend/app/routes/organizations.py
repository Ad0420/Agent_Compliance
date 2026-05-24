from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Organization, ChainState, APIKey
from ..schemas.organization import AlertEmailUpdate, OrganizationCreate, OrganizationResponse
from ..services.auth import require_permission
from ..services.baa import is_org_baa_active

router = APIRouter(prefix="/organizations", tags=["organizations"])


class BAAStatusResponse(BaseModel):
    """Response for ``GET /v1/organizations/me/baa-status``.

    Single boolean (``active``) is enough for the API-key dialog's
    "Production" tab gating in Phase 1 PR 4 (Stream C item C5). We
    deliberately do NOT include the BAA's ``document_uri`` or any
    customer-identifying fields here — the API-key surface should not
    leak the org's customer roster.
    """

    active: bool
    fix_url: str = "/customers"


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    data: OrganizationCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Create a new organization. Requires admin API key."""
    org = Organization(name=data.name)
    session.add(org)
    await session.flush()

    # Initialize chain state for this org
    chain_state = ChainState(org_id=org.id)
    session.add(chain_state)

    await session.commit()
    await session.refresh(org)
    return OrganizationResponse.model_validate(org)


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse.model_validate(org)


@router.get("/me/baa-status", response_model=BAAStatusResponse)
async def get_current_organization_baa_status(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Whether the active org has at least one active+scoped BAA right now.

    Used by the API-keys dialog (frontend `/api-keys`) to enable or
    disable the "Create production key" button before the user hits
    submit. The mint endpoint (`POST /v1/dashboard/api-keys`) does the
    real enforcement; this endpoint is purely UX so the operator sees
    the gate state inline instead of guessing after a 403.

    Bypasses the BAA freshness cache so a newly-uploaded BAA is visible
    immediately — the cost is one extra DB query per dialog open, which
    is fine for a low-frequency user-initiated flow.
    """
    org_id, _ = auth
    active = await is_org_baa_active(session, org_id, bypass_cache=True)
    return BAAStatusResponse(active=active)


@router.patch("/me/alert-email", response_model=OrganizationResponse)
async def update_alert_email(
    data: AlertEmailUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Set or clear the tamper-alert email address for this organization."""
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    org.alert_email = str(data.alert_email) if data.alert_email else None
    await session.commit()
    await session.refresh(org)
    return OrganizationResponse.model_validate(org)
