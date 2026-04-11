from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Organization, ChainState, APIKey
from ..schemas.organization import AlertEmailUpdate, OrganizationCreate, OrganizationResponse
from ..services.auth import require_permission

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    data: OrganizationCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("admin")),
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
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse.model_validate(org)


@router.patch("/me/alert-email", response_model=OrganizationResponse)
async def update_alert_email(
    data: AlertEmailUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("admin")),
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
