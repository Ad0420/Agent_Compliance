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

Compliance audit-of-audit pipeline (Workstream F3, post-PR #172 audit):
    ``compliance_review_audit`` is now a thin shim. It runs ``require_clerk_role``
    to enforce RBAC, then — if the active membership is a ``compliance_reviewer``
    and the route hasn't opted out — stashes a context dict in a ``ContextVar``.
    ``ComplianceAuditMiddleware`` reads that context AFTER the route handler
    has run, augments it with the real ``response.status_code``, and writes a
    ``ComplianceReviewRecord`` row using a fresh DB session so a rolled-back
    request transaction can't take the audit row with it.

    Why a middleware, not ``BackgroundTasks``: FastAPI's request-scoped
    ``Response`` sentinel stays at ``status_code=None`` when the handler
    returns a dict / Pydantic model (Starlette builds a separate
    ``JSONResponse``). The old background-task implementation therefore wrote
    ``status_code=200`` for every audit — including 4xx and 5xx — which is an
    audit-integrity bug.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from ..config import settings
from ..database import get_db
from ..models import ComplianceReviewRecord, OrgMembership
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


def _utcnow_naive() -> datetime:
    """Tz-aware UTC, stripped to naïve for the DateTime columns (which are
    naïve at the SQLAlchemy type level). We compute the value in tz-aware
    form for clarity, then drop the offset right before passing to the ORM.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


async def maybe_refresh_membership(
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

    age = (_utcnow_naive() - membership.updated_at).total_seconds()
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

    now = _utcnow_naive()
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
        refreshed = await maybe_refresh_membership(
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


# ── Compliance reviewer audit-of-audit (Workstream F3) ───────────────────────
#
# Request-scoped audit context. Populated by ``compliance_review_audit``
# dep AFTER role gating succeeds and the active membership has role
# ``compliance_reviewer``; consumed by ``ComplianceAuditMiddleware`` AFTER
# the route handler has run so the recorded ``status_code`` is the real
# response status (200/4xx/5xx).
#
# Implementation note: we stash the dict on ``request.state`` rather than
# a module-level ``ContextVar``. Starlette's ``BaseHTTPMiddleware`` calls
# ``call_next`` in a CHILD anyio task with its own copy of the context, so
# a ``ContextVar.set()`` inside the route handler is invisible to the
# middleware when ``call_next`` returns. ``request.state`` is the same
# mutable object both sides see, which is exactly the shape we need.
_AUDIT_STATE_KEY = "compliance_audit_ctx"


# Path-segment param names known to carry PHI / patient identifiers.
# Their values are HMAC-hashed before persistence so analysts can correlate
# within an org but can't reverse the hash to recover the raw subject ID.
# Extend this set as new routes introduce PHI-bearing path params.
_PHI_PATH_PARAMS: set[str] = {
    "data_subject_id",
    "subject_id",
    "patient_id",
    "mrn",
}

# Path-segment param names that are safe to record verbatim. These are
# internal record IDs / approvals / policy IDs etc. — opaque slugs the org
# already controls, never sourced from user input.
_SAFE_PATH_PARAMS: tuple[str, ...] = (
    "id",
    "record_id",
    "approval_id",
    "key_id",
    "policy_id",
    "violation_id",
)

# Query-param keys we allow to be recorded verbatim. Everything else is
# dropped — defensive allowlist, since query strings sometimes carry
# patient IDs / emails / search terms that have no place in an audit row.
_QUERY_PARAM_ALLOWLIST: set[str] = {
    "limit",
    "offset",
    "page",
    "sort",
    "order",
    "since",
    "until",
    "from",
    "to",
    "before",
    "after",
    "agent_name",
    "action_name",
    "result",
    "framework",
    "model_id",
    "severity",
    "status",
    "tier",
    "days",
    "start_date",
    "end_date",
    "action_type",
    "start_seq",
    "end_seq",
}


def _hash_phi(value: str, org_id: str) -> str:
    """HMAC-SHA-256 of a PHI-bearing value, salted with the org_id.

    Same value within the same org → same hash → analysts can correlate
    reviewer activity across audit rows. Different orgs → different hashes
    → no cross-tenant correlation. The truncated 32-char hex prefix keeps
    audit rows readable while preserving >120 bits of collision resistance.

    The org_id is not a secret per se but it's not exposed externally either;
    combined with HMAC's PRF property this means an attacker who steals an
    audit table dump cannot brute-force the original IDs without also
    learning the org_id and the small space of plausible inputs.
    """
    key = f"vera-audit-phi-salt:{org_id}".encode()
    return "sha256:" + hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:32]


def _extract_target_id(request: Request, org_id: str) -> str | None:
    """Return the route's primary target identifier.

    PHI-bearing path-params (see ``_PHI_PATH_PARAMS``) are hashed; safe
    path-params are returned verbatim. Hash + safe is in a single pass so
    routes with both kinds of params (e.g. ``/data-subjects/{sid}/records/{rid}``)
    record the most specific one — currently the PHI param wins by
    iteration order, which is what we want for HIPAA reporting.
    """
    path_params = request.path_params or {}
    # First pass: PHI param if any (always wins; the route is about a subject).
    for key, value in path_params.items():
        if key in _PHI_PATH_PARAMS:
            return _hash_phi(str(value), org_id)
    # Second pass: first safe param in priority order.
    for safe_key in _SAFE_PATH_PARAMS:
        if safe_key in path_params:
            return str(path_params[safe_key])
    return None


def _redact_http_path(path: str, org_id: str) -> str:
    """If ``path`` contains a PHI segment, replace that segment with a hashed
    token. Currently only ``/data-subjects/<phi>`` is recognised — extend
    this list (and the test) as new PHI-bearing routes appear.
    """
    if "/data-subjects/" not in path:
        return path
    prefix, sep, rest = path.partition("/data-subjects/")
    if not sep or not rest:
        return path
    parts = rest.split("/", 1)
    hashed = _hash_phi(parts[0], org_id)
    suffix = "/" + parts[1] if len(parts) > 1 else ""
    return f"{prefix}/data-subjects/{hashed}{suffix}"


def _redact_query_params(qp: dict[str, str]) -> dict[str, str] | None:
    """Allowlist-filter query params. Anything not on
    ``_QUERY_PARAM_ALLOWLIST`` is dropped. Empty dict → ``None`` (so the
    JSON column stores NULL rather than ``{}``)."""
    if not qp:
        return None
    filtered = {k: v for k, v in qp.items() if k in _QUERY_PARAM_ALLOWLIST}
    return filtered or None


def _infer_target_type(request: Request) -> str | None:
    """Best-effort target-type label inferred from the route's path. Lets
    a compliance investigator group review-trail rows by what the reviewer
    was looking at without re-parsing every ``http_path``."""
    path = request.url.path
    if "/data-subjects/" in path:
        return "data_subject"
    if "/actions" in path:
        return "action_record"
    if "/approvals" in path:
        return "approval"
    if "/api-keys" in path:
        return "api_key"
    if "/violations" in path:
        return "policy_violation"
    return None


async def _write_audit_record(ctx: dict[str, Any]) -> None:
    """Persist a ``ComplianceReviewRecord`` from a fresh session.

    We deliberately don't share the route's session — a route-level
    rollback (e.g. a handler that raises before commit) would otherwise
    discard the audit write too. Best-effort: callers catch exceptions
    so the originating response is never blocked on an audit failure.
    """
    from ..database import AsyncSessionLocal

    record = ComplianceReviewRecord(
        org_id=ctx["org_id"],
        membership_id=ctx["membership_id"],
        clerk_user_id=ctx["clerk_user_id"],
        action=ctx["action"],
        target_type=ctx.get("target_type"),
        target_id=ctx.get("target_id"),
        query_params=ctx.get("query_params"),
        response_metadata={"status_code": ctx["status_code"]},
        http_method=ctx["http_method"],
        http_path=ctx["http_path"],
        request_id=ctx.get("request_id"),
        ip_address=ctx.get("ip_address"),
        user_agent=ctx.get("user_agent"),
        occurred_at=ctx["occurred_at"],
    )
    async with AsyncSessionLocal() as audit_session:
        audit_session.add(record)
        await audit_session.commit()


class ComplianceAuditMiddleware(BaseHTTPMiddleware):
    """Captures the REAL ``response.status_code`` after the route runs and
    writes the ``ComplianceReviewRecord`` row.

    The previous implementation used ``BackgroundTasks`` and read the
    request-scoped ``Response`` sentinel. That sentinel only carries the
    status code when the handler explicitly mutated it (rare); when the
    handler returns a dict / Pydantic model, Starlette builds a separate
    ``JSONResponse`` and the sentinel stays at ``None`` → every audit
    recorded ``status_code=200`` regardless of the actual response. The
    middleware approach sees the assembled response on its way back through
    the ASGI stack and reads the true status code.

    Audit failures are caught and logged at WARN. F3 is defense-in-depth —
    we do NOT break the originating request when the audit-side commit
    fails.
    """

    async def dispatch(
        self, request: Request, call_next
    ) -> StarletteResponse:
        # The dep populates request.state.compliance_audit_ctx if it
        # decides to audit. We don't pre-set it here; absence ==
        # "nothing to audit".
        response = await call_next(request)
        ctx = getattr(request.state, _AUDIT_STATE_KEY, None)
        if ctx is not None:
            ctx["status_code"] = response.status_code
            try:
                await _write_audit_record(ctx)
            except Exception as exc:  # noqa: BLE001 — by design
                logger.warning(
                    "Failed to record compliance review action: %s",
                    exc,
                    extra={
                        "clerk_user_id": ctx.get("clerk_user_id"),
                        "path": ctx.get("http_path"),
                    },
                )
        return response


def compliance_review_audit(
    allowed_roles: Iterable[str] | None = None,
    *,
    exclude_path_audit: bool = False,
):
    """Composite dependency: enforce RBAC AND register an audit-of-audit
    context entry for the active request.

    Replaces the old "every route declares both ``Depends(compliance_review_audit())``
    AND ``Depends(require_clerk_role(...))``" pattern. FastAPI's dep-DAG
    dedupes ``require_clerk_role`` within a single request, so routes that
    use this dep get role gating + audit registration in one go.

    Usage::

        @router.get(
            "/v1/dashboard/actions",
            response_model=ActionRecordListResponse,
        )
        async def list_actions(
            ctx: dict = Depends(
                compliance_review_audit(
                    ["admin", "developer", "compliance_reviewer"]
                )
            ),
        ): ...

    ``allowed_roles``: roles permitted to call the route. Default is
    ``admin / developer / compliance_reviewer`` — the broadest read tier.

    ``exclude_path_audit``: when ``True``, the role gate still runs but no
    audit record is written. Use on the review-trail endpoint and other
    self-referential dashboard pages so a compliance_reviewer reading their
    own log doesn't generate fresh log rows on every refresh
    (audit-loop bug — CRITICAL #3).
    """
    allowed = tuple(allowed_roles) if allowed_roles else (
        "admin",
        "developer",
        "compliance_reviewer",
    )
    gate = require_clerk_role(allowed)

    async def _dep(
        request: Request,
        ctx: dict[str, Any] = Depends(gate),
    ) -> dict[str, Any]:
        if exclude_path_audit:
            return ctx
        membership = ctx.get("membership")
        if membership is None or membership.role != "compliance_reviewer":
            return ctx

        org_id = membership.org_id
        audit_data: dict[str, Any] = {
            "org_id": org_id,
            "membership_id": membership.id,
            "clerk_user_id": membership.clerk_user_id,
            "action": _redact_http_path(request.url.path, org_id),
            "target_type": _infer_target_type(request),
            "target_id": _extract_target_id(request, org_id),
            "query_params": _redact_query_params(dict(request.query_params)),
            "http_method": request.method,
            "http_path": _redact_http_path(request.url.path, org_id),
            "request_id": getattr(request.state, "request_id", None),
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "occurred_at": _utcnow_naive(),
            # status_code populated by ComplianceAuditMiddleware after the
            # route returns. We pre-set 0 here as a sentinel so a developer
            # reading a record dump can tell at a glance if the middleware
            # never ran (which would be a bug).
            "status_code": 0,
        }
        # Stash on request.state — middleware reads it after the response
        # is built (which is where the real status_code becomes known).
        setattr(request.state, _AUDIT_STATE_KEY, audit_data)
        return ctx

    return _dep


__all__ = [
    "require_clerk_auth",
    "require_clerk_role",
    "compliance_review_audit",
    "ComplianceAuditMiddleware",
    "maybe_refresh_membership",
]
