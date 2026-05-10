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
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    claims = await verify_clerk_jwt(credentials.credentials)
    request.state.clerk_user = claims
    return claims


__all__ = ["require_clerk_auth"]
