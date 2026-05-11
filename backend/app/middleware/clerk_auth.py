"""Clerk JWT verification dependency for dashboard routes.

Use as a FastAPI route-level dependency:

    @app.get("/v1/dashboard/me", dependencies=[Depends(require_clerk_auth)])
    def me(request: Request) -> dict:
        return request.state.clerk_user

Or to receive the claims directly:

    @app.get("/v1/dashboard/me")
    async def me(claims: dict = Depends(require_clerk_auth)) -> dict:
        return claims

Verification flow: fetch Clerk's JWKS (cached for 1h, refetched on unknown
kid), verify RS256 signature against the matching `kid`, validate `iss`
against ``CLERK_ISSUER`` if configured, validate `aud` if ``CLERK_AUDIENCE``
is set, validate ``exp``/``iat``, then populate ``request.state.clerk_user``
with the decoded claims.

This middleware is intentionally additive: it lives alongside the existing
API-key auth in ``services/auth.py``. Existing ``/v1/*`` routes continue
to use API keys; only ``/v1/dashboard/*`` routes use Clerk JWTs.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import OrgMembership
from ..services.auth import verify_clerk_jwt

logger = logging.getLogger(__name__)

# auto_error=False so we control the 401 message ourselves and don't leak the
# default "Not authenticated" string when the header is missing entirely.
_bearer = HTTPBearer(auto_error=False)


async def require_clerk_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Verify Clerk JWT bearer token. Raises 401 on any failure.

    On success, populates ``request.state.clerk_user`` and returns the decoded
    JWT claims dict.
    """
    request_id = getattr(request.state, "request_id", None)

    if credentials is None or credentials.scheme.lower() != "bearer":
        # Generic 401 detail — don't leak whether the issue was a missing
        # header vs a wrong scheme. The server-side log keeps the detail.
        logger.info(
            "Clerk JWT rejected: missing or non-bearer Authorization header",
            extra={"request_id": request_id} if request_id else {},
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    claims = await verify_clerk_jwt(credentials.credentials, request_id=request_id)
    request.state.clerk_user = claims
    return claims


def require_clerk_role(allowed_roles: Iterable[str]):
    """Dependency factory enforcing RBAC against the active Clerk org context.

    Use::

        @router.post(
            "/v1/dashboard/api-keys",
            dependencies=[Depends(require_clerk_role(["admin"]))],
        )

    or, to receive the membership::

        async def route(ctx = Depends(require_clerk_role(["admin"]))): ...

    On success the dependency returns a dict::

        {
            "claims": <decoded JWT claims>,
            "membership": <OrgMembership ORM row>,
            "org_id": <backend Organization.id>,
        }

    The membership and org_id are looked up by the JWT's ``org_id`` claim
    (Clerk includes this when the user has an active org context selected).
    Without that claim we 400 — the user is signed in but not "in" an org,
    so RBAC cannot apply.
    """
    allowed = tuple(allowed_roles)

    async def _dep(
        request: Request,
        claims: dict[str, Any] = Depends(require_clerk_auth),
        session: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        clerk_user_id = claims.get("sub")
        clerk_org_id = claims.get("org_id")

        if not clerk_user_id:
            # JWT verified but missing `sub` — shouldn't happen but defensive.
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not clerk_org_id:
            raise HTTPException(
                status_code=400,
                detail="No active organization in Clerk session",
            )

        result = await session.execute(
            select(OrgMembership).where(
                OrgMembership.clerk_user_id == clerk_user_id,
                OrgMembership.clerk_org_id == clerk_org_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this organization",
            )
        if membership.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {list(allowed)}",
            )

        # Stash for downstream introspection (e.g. logging middleware).
        request.state.clerk_membership = membership
        return {
            "claims": claims,
            "membership": membership,
            "org_id": membership.org_id,
        }

    return _dep


__all__ = ["require_clerk_auth", "require_clerk_role"]
