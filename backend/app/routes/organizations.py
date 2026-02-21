from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Organization, ChainState, APIKey
from ..schemas.organization import OrganizationCreate, OrganizationResponse
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
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        created_at=org.created_at,
    )


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        created_at=org.created_at,
    )
