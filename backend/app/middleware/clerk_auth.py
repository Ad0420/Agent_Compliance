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

Membership freshness re-check (post-PR #164 audit, CRITICAL #5 + #6):
    ``require_clerk_role`` looks up the cached ``OrgMembership`` row by
    (clerk_user_id, clerk_org_id). If that row is older than
    ``settings.membership_freshness_seconds`` we make a server-to-server
    call to Clerk's REST API and confirm the user's current role for that
    org. Three cases:

      a) Clerk returns a matching role → refresh ``updated_at`` and proceed.
      b) Clerk returns a different role → update the cached row to match,
         then re-evaluate RBAC. Closes the "stale admin" privilege-escalation
         gap (CRITICAL #5).
      c) Clerk returns 404 / empty memberships → user is no longer in the
         org. Delete the cached row, raise 403. Closes the "JWT still valid
         for ~60 s after Clerk kick" gap (CRITICAL #6).

    If ``CLERK_SECRET_KEY`` isn't configured, OR the Clerk API call fails
    (timeout / 5xx), we log a warning and fall back to the cached role —
    availability beats consistency for a defense-in-depth check.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import OrgMembership
from ..services.auth import verify_clerk_jwt

logger = logging.getLogger(__name__)

# auto_error=False so we control the 401 message ourselves and don't leak the
# default "Not authenticated" string when the header is missing entirely.
_bearer = HTTPBearer(auto_error=False)


# ── Clerk role mapping (kept in sync with routes/clerk_webhooks.py) ───────────
# Duplicated here intentionally — the webhook handler is the canonical mapping
# for inbound events, but the freshness re-check is the canonical mapping for
# outbound API calls. Keeping them in two places means an unfamiliar reader
# doesn't have to chase the import; the small drift cost is mitigated by the
# fact that both lists are < 10 entries and tested in their own files.
_CLERK_TO_BACKEND_ROLE = {
    "org:admin": "admin",
    "admin": "admin",
    "org:compliance_reviewer": "compliance_reviewer",
    "compliance_reviewer": "compliance_reviewer",
    "org:member": "developer",
    "member": "developer",
    "org:developer": "developer",
    "developer": "developer",
}


def _map_clerk_role(clerk_role: str | None) -> str:
    """Map a Clerk role string to a backend role. Unknown → developer."""
    if clerk_role is None:
        return "developer"
    return _CLERK_TO_BACKEND_ROLE.get(clerk_role, "developer")


_CLERK_API_BASE = "https://api.clerk.com"


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


async def _fetch_clerk_membership_role(
    *, clerk_user_id: str, clerk_org_id: str
) -> str | None:
    """Query Clerk's REST API for the user's current role in the org.

    Returns the mapped backend role string on success, ``None`` if the user
    is not (or no longer) a member of the org. Raises ``httpx.HTTPError`` if
    the API call itself failed (timeout / 5xx) — callers must handle this by
    falling back to the cached role.

    Endpoint: ``GET /v1/organizations/{org_id}/memberships?user_id=...``
    Docs:     https://clerk.com/docs/reference/backend-api/tag/Organization-Memberships

    A 404 from Clerk means the org no longer exists. We treat that the same
    as "user no longer a member" (which is true — if the org is gone, no
    one is in it).
    """
    if not settings.clerk_secret_key:
        # No secret configured → caller's responsibility to skip the check.
        # We raise so the caller's exception handler kicks in.
        raise RuntimeError("clerk_secret_key not configured")

    url = f"{_CLERK_API_BASE}/v1/organizations/{clerk_org_id}/memberships"
    headers = {
        "Authorization": f"Bearer {settings.clerk_secret_key}",
        "Accept": "application/json",
    }
    params = {"user_id": clerk_user_id, "limit": 1}

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body = resp.json()
    # Clerk's list endpoint returns either a top-level list (older API) or
    # {"data": [...]} (newer paged shape). Handle both for forward-compat.
    if isinstance(body, list):
        data = body
    elif isinstance(body, dict):
        data = body.get("data") or []
    else:
        data = []
    if not data:
        return None
    role = (data[0] or {}).get("role") if isinstance(data[0], dict) else None
    return _map_clerk_role(role)


async def _maybe_refresh_membership(
    session: AsyncSession,
    membership: OrgMembership,
    *,
    clerk_user_id: str,
    clerk_org_id: str,
) -> OrgMembership | None:
    """Defense-in-depth re-check against Clerk if the cached row is stale.

    Returns the (possibly mutated) membership, or ``None`` if Clerk reports
    the user is no longer in the org (in which case we've also deleted the
    cached row). Side-effects:

      * On role mismatch: updates ``membership.role`` + ``updated_at`` and
        commits.
      * On role match:    updates ``membership.updated_at`` and commits
                          (so future requests within the window skip the
                          re-check).
      * On not-a-member:  deletes the cached row and commits.
      * On API failure:   logs a warning and returns the cached membership
                          unchanged (availability beats consistency).
    """
    freshness = settings.membership_freshness_seconds
    if freshness <= 0:
        return membership
    if not settings.clerk_secret_key:
        # Freshness check is opt-in: if the operator hasn't set
        # CLERK_SECRET_KEY, we skip silently. The cached role is trusted.
        return membership

    age = (datetime.utcnow() - membership.updated_at).total_seconds()
    if age < freshness:
        return membership

    try:
        fresh_role = await _fetch_clerk_membership_role(
            clerk_user_id=clerk_user_id, clerk_org_id=clerk_org_id
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        # Network glitch, Clerk 5xx, missing config — fail open with a
        # WARN log so the cached role still works. Failing closed here
        # would brick the dashboard on transient Clerk outages.
        logger.warning(
            "Clerk membership freshness check failed; using cached role: %s",
            exc,
            extra={
                "clerk_user_id": clerk_user_id,
                "clerk_org_id": clerk_org_id,
            },
        )
        return membership

    if fresh_role is None:
        # User is no longer a member of this org (or org is gone). Delete
        # the cached row and signal the caller to 403.
        logger.info(
            "Clerk reports user %s no longer a member of org %s; revoking cached membership",
            clerk_user_id,
            clerk_org_id,
        )
        await session.delete(membership)
        await session.commit()
        return None

    now = datetime.utcnow()
    if fresh_role != membership.role:
        logger.info(
            "Refreshing role for user %s in org %s: %s -> %s",
            clerk_user_id,
            clerk_org_id,
            membership.role,
            fresh_role,
        )
        membership.role = fresh_role
    membership.updated_at = now
    await session.commit()
    await session.refresh(membership)
    return membership


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

    Defense-in-depth: if the cached membership row is older than
    ``settings.membership_freshness_seconds``, we consult Clerk's REST API
    before deciding RBAC. See module docstring for the three cases.
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

        # Defense-in-depth freshness re-check against Clerk's REST API.
        # Skipped fast when the row was recently touched (common case) or
        # when CLERK_SECRET_KEY isn't configured (opt-in feature).
        refreshed = await _maybe_refresh_membership(
            session,
            membership,
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
        )
        if refreshed is None:
            # Clerk says the user was kicked from the org. Treat the same
            # as "no cached membership" — 403, not 401.
            raise HTTPException(
                status_code=403,
                detail="Not a member of this organization",
            )
        membership = refreshed

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
