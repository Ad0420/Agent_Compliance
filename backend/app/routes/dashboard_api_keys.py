"""API-key issuance UX for Clerk-authenticated users (Workstream E4).

These routes mirror the existing ``/v1/api-keys/*`` endpoints — list,
create, revoke — but gate access via Clerk RBAC (``require_clerk_role``)
instead of an API-key bearer (``require_permission``). They live under
``/v1/dashboard/api-keys`` so the frontend can call them with the user's
Clerk session token (forwarded from the Next.js server component).

RBAC matrix:
    list   — admin OR developer (developers can view but not mint/revoke)
    create — admin only
    revoke — admin only

The legacy ``/v1/api-keys/*`` endpoints are unchanged. Once the dashboard
is fully migrated to Clerk auth those legacy endpoints can be removed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.clerk_auth import require_clerk_role
from ..models import APIKey
from ..schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyResponse
from ..services.auth import generate_api_key
from ..services.baa import is_org_baa_active

router = APIRouter(prefix="/v1/dashboard/api-keys", tags=["dashboard-api-keys"])


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin", "developer"])),
) -> list[APIKeyResponse]:
    """List API keys for the active Clerk org. Read-only — visible to both
    admins and developers, since developers need the prefix to recognise
    their own keys in logs.
    """
    org_id = ctx["org_id"]
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
            # Surface the actual DB-stored kind rather than the schema
            # default — once PR 4 lets callers mint live keys, the dashboard
            # will need to distinguish them visually.
            kind=k.kind,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
            expires_at=k.expires_at,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.post("", response_model=APIKeyCreateResponse)
async def create_api_key(
    data: APIKeyCreate,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> APIKeyCreateResponse:
    """Mint a new API key for the active Clerk org. Admin-only.

    The raw key is returned ONCE — the database stores only the SHA-256
    hash plus a 12-char prefix for display. Callers must capture the
    response and persist the key out-of-band; a second GET on this route
    cannot recover it.
    """
    org_id = ctx["org_id"]
    # Phase 1 PR 4 (Stream C item C1): live keys require an active BAA at
    # mint time. ``bypass_cache=True`` because freshness matters more
    # than latency on the mint path (humans click "create" a few times
    # an hour) — we want the operator who *just uploaded* a BAA to see
    # the green light immediately. SDK PR #194 maps ``code='baa_required'``
    # → ``PolicyBlock``; emitting the structured payload here is the
    # activation moment for that defensive mapping.
    if data.kind == "live":
        baa_active = await is_org_baa_active(
            session, org_id, bypass_cache=True
        )
        if not baa_active:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "baa_required",
                    "detail": (
                        "Production API keys require an active Business "
                        "Associate Agreement on file. Upload a signed BAA "
                        "on the Customers page, then try again."
                    ),
                    "fix_url": "/customers",
                },
            )
    raw_key, api_key = await generate_api_key(
        session,
        org_id,
        data.name,
        data.permissions,
        expires_at=data.expires_at,
        kind=data.kind,
    )
    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        raw_key=raw_key,
        key_prefix=api_key.key_prefix,
        permissions=api_key.permissions,
        # Reflect the DB-assigned ``kind`` so the dashboard renders the
        # tier badge correctly without a follow-up list refresh.
        kind=api_key.kind,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> dict[str, str]:
    """Revoke an API key. Admin-only. Returns 404 if the key isn't in the
    caller's org (no information leak about other orgs' key IDs).
    """
    org_id = ctx["org_id"]
    result = await session.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.org_id == org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key already revoked")

    # Strip tzinfo for TIMESTAMP WITHOUT TIME ZONE compatibility (matches
    # the pattern in services/auth.generate_api_key).
    api_key.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return {"detail": "API key revoked"}


__all__ = ["router"]
