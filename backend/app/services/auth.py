import hashlib
import logging
import secrets
import time
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import APIKey

logger = logging.getLogger(__name__)

security = HTTPBearer()

# ── Clerk JWT verification ────────────────────────────────────────────────────
# In-process JWKS cache. Keyed by `kid` → loaded RSA public key. Refreshed when
# either (a) TTL has elapsed or (b) we encounter an unknown kid (key rotation).
_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}
_JWKS_TTL_SECONDS = 3600


async def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch a JWKS document over HTTPS. Separated for ease of testing."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        return resp.json()


async def get_jwks_keys(force_refresh: bool = False) -> dict[str, Any]:
    """Return cached map of `kid` → RSA public key. Fetches on miss/expiry.

    Raises HTTPException(503) if `CLERK_JWKS_URL` is unconfigured — refusing to
    silently accept tokens beats failing open.
    """
    if not settings.clerk_jwks_url:
        logger.warning("CLERK_JWKS_URL is not configured — refusing to verify Clerk JWTs")
        raise HTTPException(
            status_code=503,
            detail="Clerk auth is not configured on this server",
        )

    now = time.time()
    cache_fresh = (now - _JWKS_CACHE["fetched_at"]) < _JWKS_TTL_SECONDS
    if not force_refresh and cache_fresh and _JWKS_CACHE["keys"]:
        return _JWKS_CACHE["keys"]

    try:
        jwks = await _fetch_jwks(settings.clerk_jwks_url)
    except httpx.HTTPError as exc:
        logger.exception("Failed to fetch Clerk JWKS")
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch Clerk JWKS",
        ) from exc

    keys: dict[str, Any] = {}
    for jwk in jwks.get("keys", []):
        kid = jwk.get("kid")
        if not kid:
            continue
        try:
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
        except (ValueError, TypeError, jwt.InvalidKeyError):
            logger.warning("Skipping malformed JWK kid=%s", kid)
            continue

    _JWKS_CACHE["fetched_at"] = now
    _JWKS_CACHE["keys"] = keys
    return keys


async def verify_clerk_jwt(token: str) -> dict[str, Any]:
    """Verify a Clerk-issued RS256 JWT and return its claims.

    Raises HTTPException(401) on any verification failure, HTTPException(503)
    if Clerk auth is not configured.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Malformed JWT: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="JWT missing kid header")

    keys = await get_jwks_keys()
    key = keys.get(kid)
    if key is None:
        # Cache miss — refetch once in case Clerk rotated keys.
        keys = await get_jwks_keys(force_refresh=True)
        key = keys.get(kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Unknown JWT kid")

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "options": {"require": ["exp", "iat"]},
    }
    if settings.clerk_issuer:
        decode_kwargs["issuer"] = settings.clerk_issuer
    if settings.clerk_audience:
        decode_kwargs["audience"] = settings.clerk_audience
    else:
        # When no audience is configured, skip the aud claim verification (Clerk
        # session tokens by default carry an `azp` rather than `aud`).
        decode_kwargs["options"]["verify_aud"] = False

    try:
        claims = jwt.decode(token, key=key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="JWT expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(status_code=401, detail="Invalid JWT issuer") from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(status_code=401, detail="Invalid JWT audience") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"JWT verification failed: {exc}") from exc

    return claims


def _reset_jwks_cache_for_tests() -> None:
    """Test-only helper. Wipes the JWKS cache so tests are isolated."""
    _JWKS_CACHE["fetched_at"] = 0.0
    _JWKS_CACHE["keys"] = {}


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

    # Strip timezone before writing to TIMESTAMP WITHOUT TIME ZONE column.
    if expires_at is not None and expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)

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
