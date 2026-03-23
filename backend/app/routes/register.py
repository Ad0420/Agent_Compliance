from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Organization, ChainState
from ..schemas.organization import RegisterRequest, RegisterResponse
from ..services.auth import generate_api_key

router = APIRouter(tags=["register"])


@router.post("/register", response_model=RegisterResponse)
async def register(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_db),
):
    """Self-serve signup. Creates an org + default admin API key. No auth required."""
    org = Organization(name=data.org_name.strip())
    session.add(org)
    await session.flush()

    chain_state = ChainState(org_id=org.id)
    session.add(chain_state)
    await session.flush()

    raw_key, api_key = await generate_api_key(
        session=session,
        org_id=org.id,
        name="default",
        permissions=["write", "read", "admin"],
    )

    # generate_api_key commits the session, expiring all ORM objects.
    # Refresh org to safely read server-default fields like created_at.
    await session.refresh(org)

    return RegisterResponse(
        org_id=org.id,
        org_name=org.name,
        api_key=raw_key,
        key_prefix=api_key.key_prefix,
        created_at=org.created_at,
    )
