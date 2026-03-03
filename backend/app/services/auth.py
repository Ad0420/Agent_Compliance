import hashlib
import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import APIKey

security = HTTPBearer()


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def generate_api_key(
    session: AsyncSession, org_id: str, name: str, permissions: list[str],
    expires_at=None,
) -> tuple[str, APIKey]:
    """Generate a new API key. Returns (raw_key, api_key_model)."""
    raw_key = settings.api_key_prefix + secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]

    api_key = APIKey(
        org_id=org_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        permissions=permissions,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return raw_key, api_key


async def authenticate_request(
    session: AsyncSession, raw_key: str
) -> APIKey | None:
    """Look up an API key by its hash. Returns None if not found or revoked."""
    key_hash = _hash_key(raw_key)
    result = await session.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None or not api_key.is_active:
        return None
    return api_key


async def get_current_org(
    credentials: HTTPAuthorizationCredentials = Security(security),
    session: AsyncSession = Depends(get_db),
) -> tuple[str, APIKey]:
    """FastAPI dependency: extract Bearer token, authenticate, return (org_id, api_key)."""
    api_key = await authenticate_request(session, credentials.credentials)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return api_key.org_id, api_key


def require_permission(permission: str):
    """Returns a dependency that checks for a specific permission."""
    async def _check(
        auth: tuple[str, APIKey] = Depends(get_current_org),
    ) -> tuple[str, APIKey]:
        org_id, api_key = auth
        if permission not in api_key.permissions:
            raise HTTPException(
                status_code=403,
                detail=f"API key lacks '{permission}' permission",
            )
        return org_id, api_key
    return _check
