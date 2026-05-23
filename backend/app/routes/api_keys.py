from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey
from ..schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyResponse
from ..services.auth import require_permission, generate_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=APIKeyCreateResponse)
async def create_api_key(
    data: APIKeyCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    org_id, _ = auth
    raw_key, api_key = await generate_api_key(
        session, org_id, data.name, data.permissions, expires_at=data.expires_at
    )
    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        raw_key=raw_key,
        key_prefix=api_key.key_prefix,
        permissions=api_key.permissions,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    org_id, _ = auth
    result = await session.execute(
        select(APIKey).where(APIKey.org_id == org_id).order_by(APIKey.created_at)
    )
    keys = result.scalars().all()
    return [
        APIKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            permissions=k.permissions,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
            expires_at=k.expires_at,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    org_id, _ = auth
    result = await session.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.org_id == org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key already revoked")

    api_key.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return {"detail": "API key revoked"}
