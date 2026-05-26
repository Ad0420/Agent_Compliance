import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Header, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import APIKey, OrgMembership
from .iam import IamTier, tier_from_claims

logger = logging.getLogger(__name__)

security = HTTPBearer()

# ── Clerk JWT verification ────────────────────────────────────────────────────
# In-process JWKS cache. Keyed by `kid` → loaded RSA public key. Refreshed when
# either (a) TTL has elapsed or (b) we encounter an unknown kid (key rotation).
_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}
_JWKS_TTL_SECONDS = 3600

# Single-flight lock for JWKS fetch. Without it, a burst of requests with a
# cold cache fan out to N concurrent JWKS HTTP requests; with it, the first
# request fetches and the rest wait for the populated cache.
_JWKS_FETCH_LOCK = asyncio.Lock()

# Negative cache for unknown kids. Without a negative cache, an attacker
# spamming random kids forces one outbound JWKS HTTP per request. TTL is
# short (60s) so legitimate key rotation isn't blocked for long.
_UNKNOWN_KID_CACHE: dict[str, float] = {}
_UNKNOWN_KID_TTL_SECONDS = 60.0

# Global cooldown on forced JWKS refresh (defense-in-depth alongside the
# negative kid cache). Even if an attacker rotates kids faster than 60s,
# we still cap forced refetches to once every 30s.
_LAST_FORCED_REFRESH: float = 0.0
_FORCED_REFRESH_COOLDOWN_SECONDS = 30.0

# Clock-skew leeway. Industry-standard 30s slack on `exp` and `iat`.
_JWT_LEEWAY_SECONDS = 30


async def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch a JWKS document over HTTPS. Separated for ease of testing."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        return resp.json()


async def get_jwks_keys(force_refresh: bool = False) -> dict[str, Any]:
    """Return cached map of `kid` → RSA public key. Fetches on miss/expiry.

    Single-flight: under burst load the lock collapses concurrent fetches
    into one outbound HTTP. Other callers wait on the lock and read the
    populated cache when they enter the critical section.

    Raises HTTPException(503) if `CLERK_JWKS_URL` is unconfigured — refusing to
    silently accept tokens beats failing open.
    """
    if not settings.clerk_jwks_url:
        logger.warning("CLERK_JWKS_URL is not configured — refusing to verify Clerk JWTs")
        raise HTTPException(
            status_code=503,
            detail="Clerk auth is not configured on this server",
        )

    # Fast path: cache is fresh and populated, no force-refresh requested.
    # Avoid taking the lock so the common case stays uncontended.
    now = time.time()
    cache_fresh = (now - _JWKS_CACHE["fetched_at"]) < _JWKS_TTL_SECONDS
    if not force_refresh and cache_fresh and _JWKS_CACHE["keys"]:
        return _JWKS_CACHE["keys"]

    async with _JWKS_FETCH_LOCK:
        # Re-check inside the lock: a peer may have populated the cache while
        # we were waiting for the lock. If so, return without re-fetching.
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
        # A successful refresh likely surfaces previously-rotated kids; clear
        # the negative cache so legitimate clients aren't held back.
        _UNKNOWN_KID_CACHE.clear()
        return keys


def _reject(reason: str, request_id: str | None = None) -> HTTPException:
    """Build a generic 401 while logging the specific reason server-side.

    Returning a generic ``Unauthorized`` to the client avoids handing
    attackers an oracle ("malformed header" vs "bad signature" vs "wrong
    issuer" vs "kid not in JWKS") that helps them craft tokens. The
    server-side log keeps the detail for operators, correlated by
    request_id where available.
    """
    extra = {"request_id": request_id} if request_id else {}
    logger.info("Clerk JWT rejected: %s", reason, extra=extra)
    return HTTPException(status_code=401, detail="Unauthorized")


async def verify_clerk_jwt(
    token: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Verify a Clerk-issued RS256 JWT and return its claims.

    Raises HTTPException(401) on any verification failure, HTTPException(503)
    if Clerk auth is not configured.

    The caller may pass ``request_id`` so 401-rejection logs correlate
    with the request log line emitted by ``RequestIDMiddleware``.
    """
    global _LAST_FORCED_REFRESH

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _reject(f"malformed header: {exc}", request_id) from exc

    # Reject `alg: none` and any non-RS256 algorithm at the header level.
    # `jwt.decode` with explicit ``algorithms=["RS256"]`` already rejects
    # these, but doing it here avoids a JWKS lookup for obvious garbage.
    alg = unverified_header.get("alg")
    if alg != "RS256":
        raise _reject(f"unsupported alg: {alg!r}", request_id)

    kid = unverified_header.get("kid")
    if not kid:
        raise _reject("missing kid header", request_id)

    # Negative cache check: short-circuit known-bad kids without refetching
    # JWKS. An attacker spamming random kids would otherwise force one
    # outbound HTTP per request.
    now = time.time()
    cached_at = _UNKNOWN_KID_CACHE.get(kid)
    if cached_at is not None and (now - cached_at) < _UNKNOWN_KID_TTL_SECONDS:
        raise _reject(f"kid {kid!r} in negative cache", request_id)

    keys = await get_jwks_keys()
    key = keys.get(kid)
    if key is None:
        # Cache miss — refetch once in case Clerk rotated keys, but only if
        # we haven't done a forced refresh recently (defense-in-depth: even
        # if an attacker rotates kids faster than the negative-cache TTL,
        # we still cap forced refetches).
        now = time.time()
        if (now - _LAST_FORCED_REFRESH) < _FORCED_REFRESH_COOLDOWN_SECONDS:
            _UNKNOWN_KID_CACHE[kid] = now
            raise _reject(
                f"unknown kid {kid!r}; forced-refresh on cooldown",
                request_id,
            )

        _LAST_FORCED_REFRESH = now
        keys = await get_jwks_keys(force_refresh=True)
        key = keys.get(kid)
        if key is None:
            _UNKNOWN_KID_CACHE[kid] = time.time()
            raise _reject(f"unknown kid {kid!r} after refetch", request_id)

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "options": {"require": ["exp", "iat"]},
        # 30s leeway on `exp`/`iat`/`nbf` for clock-skew tolerance.
        "leeway": _JWT_LEEWAY_SECONDS,
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
        raise _reject("expired", request_id) from exc
    except jwt.InvalidIssuerError as exc:
        raise _reject("invalid issuer", request_id) from exc
    except jwt.InvalidAudienceError as exc:
        raise _reject("invalid audience", request_id) from exc
    except jwt.PyJWTError as exc:
        raise _reject(f"signature verification failed: {exc}", request_id) from exc

    # `azp` validation. Clerk session tokens carry `azp` (authorized party /
    # frontend origin) rather than `aud`. If the operator has configured an
    # allow-list of authorized parties, enforce it. This is the check Clerk
    # explicitly recommends in their backend-handling docs:
    # https://clerk.com/docs/backend-requests/handling/manual-jwt
    authorized_parties = settings.clerk_authorized_parties
    if authorized_parties:
        azp = claims.get("azp")
        if azp not in authorized_parties:
            raise _reject(
                f"azp {azp!r} not in authorized_parties allow-list",
                request_id,
            )

    return claims


def _reset_jwks_cache_for_tests() -> None:
    """Test-only helper. Wipes the JWKS cache so tests are isolated."""
    global _LAST_FORCED_REFRESH
    _JWKS_CACHE["fetched_at"] = 0.0
    _JWKS_CACHE["keys"] = {}
    _UNKNOWN_KID_CACHE.clear()
    _LAST_FORCED_REFRESH = 0.0


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def generate_api_key(
    session: AsyncSession, org_id: str, name: str, permissions: list[str],
    expires_at=None,
    kind: str = "test",
) -> tuple[str, APIKey]:
    """Generate a new API key. Returns (raw_key, api_key_model).

    ``kind`` defaults to ``'test'`` so legacy callers (and existing tests)
    keep producing sandbox keys without code changes. Phase 1 PR 4
    (Stream C item C1) wires the dashboard create endpoint to plumb
    ``kind`` from the request body — BAA-gating is enforced at the
    route layer BEFORE this function runs, so we don't re-check here.
    The raw key prefix differentiates the tiers (``al_test_*`` vs
    ``al_live_*``) so engineers can tell at a glance what tier a leaked
    key belongs to. This matches the convention Stripe/Plaid/Resend use.
    """
    if kind not in ("test", "live"):
        # Belt-and-braces: the create endpoint's Pydantic schema
        # already restricts ``kind`` to the literal set, but other
        # call sites (tests, bootstrap scripts) bypass the schema.
        raise ValueError(f"invalid kind: {kind!r}; must be 'test' or 'live'")

    # Tier-aware raw key prefix so engineers can tell at a glance whether
    # a leaked key is sandbox or production. Stripe, Plaid, and Resend all
    # follow this convention. The 12-char ``key_prefix`` we store in the DB
    # picks up the tier suffix automatically.
    raw_key = f"{settings.api_key_prefix}{kind}_" + secrets.token_urlsafe(32)
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
        kind=kind,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    # Phase 3 Wave 3A.b — auto-promote checkpoint cadence on first live
    # key. Done after the key is committed so an UPDATE failure can't
    # roll back the key creation. Idempotent on the org row (skips if
    # already 'hourly' or 'disabled' — operators who explicitly chose
    # 'disabled' aren't second-guessed here). Lazy import to keep this
    # module's import surface narrow.
    if kind == "live":
        from .checkpoint_cadence import (
            maybe_promote_org_to_hourly_cadence,
        )
        try:
            await maybe_promote_org_to_hourly_cadence(session, org_id)
        except Exception:
            # Promotion is a UX improvement, not a correctness gate —
            # an unexpected error here must NOT cause the live-key
            # creation to look failed to the caller. Log + continue.
            logger.warning(
                "checkpoint cadence auto-promotion failed for org %s",
                org_id, exc_info=True,
            )

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


# Clerk role → effective backend permissions. The legacy API-key model stored
# an explicit permissions list (["read"], ["read", "write"], ["read", "write",
# "admin"]); Clerk sessions carry a role string instead. This table lets a
# Clerk session pass the same `require_permission("read")` gates that legacy
# API keys hit, without changing every route handler.
_CLERK_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"read", "write", "admin"}),
    "developer": frozenset({"read", "write"}),
    "compliance_reviewer": frozenset({"read"}),
}


class _NoActiveOrgError(Exception):
    """Clerk JWT verified but the session has no active org context."""


async def _authenticate_clerk_session(
    session: AsyncSession, raw_token: str
) -> tuple[str, frozenset[str]] | None:
    """Verify a Clerk JWT and resolve to (org_id, effective_permissions).

    Returns None if verification fails or the user has no backend membership
    (caller raises generic 401). Raises ``_NoActiveOrgError`` if the JWT is
    valid but lacks an ``org_id`` claim, so the caller can map that to a
    400 to match the convention used in ``middleware/clerk_auth.py``.

    Defense-in-depth (matches ``middleware/clerk_auth.py:require_clerk_role``):
    when the cached ``OrgMembership`` row is older than
    ``settings.membership_freshness_seconds``, re-check the user's role
    against Clerk's REST API. Closes the "stale admin" / "still-valid JWT
    after kick" gap (PR #164 audit, CRITICAL #5 + #6) on the dual-auth
    /v1/* path too.
    """
    # Import lazily to avoid a circular import — middleware/clerk_auth.py
    # imports from services.auth, so we resolve maybe_refresh_membership
    # at call time rather than at module load.
    from ..middleware.clerk_auth import maybe_refresh_membership

    try:
        claims = await verify_clerk_jwt(raw_token)
    except HTTPException:
        logger.info("Clerk session rejected: JWT verification failed")
        return None
    clerk_user_id = claims.get("sub")
    clerk_org_id = claims.get("org_id")
    if not clerk_user_id:
        logger.info("Clerk session rejected: JWT missing 'sub' claim")
        return None
    if not clerk_org_id:
        logger.info(
            "Clerk session rejected: no active organization (user=%s)",
            clerk_user_id,
        )
        raise _NoActiveOrgError()
    membership = await get_membership_for_clerk_user(
        session,
        clerk_user_id=clerk_user_id,
        clerk_org_id=clerk_org_id,
    )
    if membership is None:
        logger.info(
            "Clerk session rejected: no backend membership (user=%s org=%s)",
            clerk_user_id,
            clerk_org_id,
        )
        return None
    refreshed = await maybe_refresh_membership(
        session,
        membership,
        clerk_user_id=clerk_user_id,
        clerk_org_id=clerk_org_id,
    )
    if refreshed is None:
        # Clerk reports the user was kicked from the org. Treat as
        # no-membership; caller raises 401 (generic to avoid info leak).
        logger.info(
            "Clerk session rejected: membership revoked upstream (user=%s org=%s)",
            clerk_user_id,
            clerk_org_id,
        )
        return None
    perms = _CLERK_ROLE_PERMISSIONS.get(refreshed.role, frozenset())
    return refreshed.org_id, perms


@dataclass
class AuthContext:
    """Resolved auth context — caller identity + IAM tier.

    Wave 3A.c. Routes that need to know whether the caller is a Vera staff
    member (so they can redact PHI + write an audit-log row) depend on
    ``require_permission_with_context`` and receive this dataclass.
    Existing routes that don't need the tier continue using
    ``require_permission``, which still returns the legacy
    ``(org_id, api_key)`` tuple — no API break.

    Fields:
      * ``org_id``    — Customer Organization the request reads/writes
                        against. For staff sessions this comes from the
                        ``X-Org-Id`` header (the customer whose ticket
                        the staff member is responding to); for customer
                        sessions it's resolved from the API key or
                        Clerk OrgMembership.
      * ``api_key``   — APIKey ORM row for API-key callers; ``None`` for
                        Clerk-authenticated callers.
      * ``tier``      — ``IamTier.CUSTOMER`` (default) or
                        ``IamTier.STAFF_READ_ONLY`` (Vera-internal Clerk
                        session). STAFF_FULL is reserved for v2.
      * ``staff_id``  — Clerk user ID of the staff member; ``None`` for
                        customer callers. Required to write
                        ``staff_audit_log`` rows.
    """

    org_id: str
    api_key: Optional[APIKey]
    tier: IamTier
    staff_id: Optional[str] = None

    @property
    def is_staff(self) -> bool:
        return self.tier in (IamTier.STAFF_READ_ONLY, IamTier.STAFF_FULL)


def require_permission(permission: str):
    """Returns a dependency that checks for a specific permission.

    Accepts EITHER a legacy API-key Bearer (``al_*``) OR a Clerk session JWT.
    The SDK keeps using API keys; the dashboard uses Clerk. Both resolve to
    the same ``(org_id, permissions)`` shape, so existing route handlers don't
    need to know which auth method was used.

    Return tuple is ``(org_id, api_key)`` where ``api_key`` is ``None`` for
    Clerk-authenticated requests. Route handlers that need the APIKey row
    (e.g. for audit-log labels) must handle the ``None`` case.

    Phase 1 PR 4 (Stream C item C2) layers a BAA freshness gate on the
    API-key path: when the caller presents an ``api_key.kind == 'live'``
    bearer, the dependency verifies the org has at least one active+scoped
    BAA before returning. Sandbox keys (``kind='test'``) bypass the gate,
    and Clerk humans browsing the dashboard bypass it entirely so an
    operator can still upload the BAA that unblocks their own org.
    """
    # Import locally to avoid a top-level circular: services.baa needs the
    # ORM models which already import this module transitively. Resolving
    # at call time keeps the import graph clean.
    from .baa import is_org_baa_active

    async def _check(
        credentials: HTTPAuthorizationCredentials = Security(security),
        session: AsyncSession = Depends(get_db),
    ) -> tuple[str, APIKey | None]:
        raw = credentials.credentials
        # Legacy API-key path: tokens start with our own prefix (e.g.
        # ``al_live_``). Anything else we treat as a Clerk JWT candidate.
        if raw.startswith(settings.api_key_prefix):
            api_key = await authenticate_request(session, raw)
            if api_key is None:
                raise HTTPException(
                    status_code=401, detail="Invalid or revoked API key"
                )
            if permission not in api_key.permissions:
                raise HTTPException(
                    status_code=403,
                    detail=f"API key lacks '{permission}' permission",
                )
            # Live-key BAA gate. SDK PR #194 wired ``code='baa_expired'`` →
            # ``PolicyBlock`` defensively; this is the activation moment.
            # Response shape MUST stay in lockstep with the SDK mapping:
            # ``{"code": "baa_expired", "detail": ..., "fix_url": ...}``.
            # Sandbox keys (``kind='test'``) bypass — that's the whole point
            # of the sandbox tier.
            if api_key.kind == "live":
                baa_active = await is_org_baa_active(session, api_key.org_id)
                if not baa_active:
                    # PHI-safety: we deliberately do NOT echo the BAA's
                    # ``document_uri`` or any other agreement field here.
                    # The dashboard can fetch the active BAA via the
                    # customers surface if it needs the document link.
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "baa_expired",
                            "detail": (
                                "Live API keys require an active Business "
                                "Associate Agreement on file for your "
                                "organization."
                            ),
                            "fix_url": "/customers",
                        },
                    )
            return api_key.org_id, api_key

        try:
            clerk_result = await _authenticate_clerk_session(session, raw)
        except _NoActiveOrgError:
            # Match the 400 convention in middleware/clerk_auth.py:323 so
            # frontends can distinguish "user-fixable, pick an org" from
            # "session invalid, re-auth".
            raise HTTPException(
                status_code=400,
                detail="No active organization in Clerk session",
            )
        if clerk_result is None:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session"
            )
        org_id, perms = clerk_result
        if permission not in perms:
            raise HTTPException(
                status_code=403,
                detail=f"Session role lacks '{permission}' permission",
            )
        return org_id, None
    return _check


async def _resolve_clerk_staff_context(
    session: AsyncSession,
    raw_token: str,
    *,
    requested_org_id: Optional[str],
) -> Optional[AuthContext]:
    """Verify a Clerk JWT and check if it represents a Vera-staff session.

    Returns:
      * ``AuthContext(tier=STAFF_READ_ONLY)`` if the JWT verifies AND the
        claims indicate a staff session.
      * ``None`` if the JWT verifies but the session is a regular customer
        session (caller falls through to the customer-tier path).

    Raises HTTPException on JWT verification failure (same shape as the
    customer path so the response is consistent).

    The staff caller MUST pass an ``X-Org-Id`` header identifying which
    customer org's data they're requesting. Without it, we 400 — staff
    can't read "their own org" because the Vera-internal staff org has
    no compliance data.
    """
    try:
        claims = await verify_clerk_jwt(raw_token)
    except HTTPException:
        return None
    tier = tier_from_claims(claims, settings.clerk_staff_org_id or None)
    if tier == IamTier.CUSTOMER:
        return None
    # Staff session. Resolve the target customer org from the X-Org-Id
    # header. We refuse to default to anything — staff queries must be
    # explicit about which customer they're accessing (the audit log
    # then captures which customer was read).
    if not requested_org_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "staff_org_id_required",
                "detail": (
                    "Vera staff sessions must specify an X-Org-Id header "
                    "identifying the customer organization to access."
                ),
            },
        )
    staff_id = claims.get("sub")
    if not staff_id:
        raise HTTPException(
            status_code=401, detail="Invalid or expired session"
        )
    return AuthContext(
        org_id=requested_org_id,
        api_key=None,
        tier=tier,
        staff_id=staff_id,
    )


def require_permission_with_context(permission: str):
    """Dependency factory returning an ``AuthContext`` for the request.

    Wave 3A.c. The drop-in replacement for ``require_permission`` when a
    route needs IAM tier info (to redact PHI + write a staff audit row).

    Behavior:
      * API-key bearer → ``AuthContext(tier=CUSTOMER, api_key=<row>)``.
        Permission gate enforced the same as ``require_permission``.
      * Customer Clerk session → ``AuthContext(tier=CUSTOMER, api_key=None)``.
      * Vera-staff Clerk session (org_id matches
        ``settings.clerk_staff_org_id`` OR JWT has ``org_role=vera_staff``):
        ``AuthContext(tier=STAFF_READ_ONLY, staff_id=<sub>, org_id=<from
        X-Org-Id header>)``. Staff are read-only — any non-``read``
        permission request 403s.

    The new dependency lives alongside ``require_permission``; existing
    routes are unchanged. Routes opting into the staff-tier flow swap
    to this one + use ``ctx.tier`` to drive ``redact_*`` calls.
    """
    from .baa import is_org_baa_active

    async def _check(
        credentials: HTTPAuthorizationCredentials = Security(security),
        session: AsyncSession = Depends(get_db),
        x_org_id: Optional[str] = Header(default=None, alias="X-Org-Id"),
    ) -> AuthContext:
        raw = credentials.credentials

        # ── API-key path: always CUSTOMER tier ─────────────────────────
        if raw.startswith(settings.api_key_prefix):
            api_key = await authenticate_request(session, raw)
            if api_key is None:
                raise HTTPException(
                    status_code=401, detail="Invalid or revoked API key"
                )
            if permission not in api_key.permissions:
                raise HTTPException(
                    status_code=403,
                    detail=f"API key lacks '{permission}' permission",
                )
            if api_key.kind == "live":
                baa_active = await is_org_baa_active(session, api_key.org_id)
                if not baa_active:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "baa_expired",
                            "detail": (
                                "Live API keys require an active Business "
                                "Associate Agreement on file for your "
                                "organization."
                            ),
                            "fix_url": "/customers",
                        },
                    )
            return AuthContext(
                org_id=api_key.org_id,
                api_key=api_key,
                tier=IamTier.CUSTOMER,
            )

        # ── Clerk path: branch on staff vs customer ──────────────────
        # Try the staff path first — if the JWT verifies and the claims
        # indicate staff, we route through the staff branch (which honours
        # X-Org-Id). Otherwise fall through to the customer branch.
        staff_ctx = await _resolve_clerk_staff_context(
            session, raw, requested_org_id=x_org_id
        )
        if staff_ctx is not None:
            # Staff is read-only at v1. Any non-read permission demand
            # rejects with 403 so the same dependency can guard both
            # GET and write routes without per-route branching.
            if permission != "read":
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "staff_read_only",
                        "detail": (
                            "Vera staff sessions are read-only in this "
                            "tier. Write operations require a customer "
                            "credential."
                        ),
                    },
                )
            return staff_ctx

        try:
            clerk_result = await _authenticate_clerk_session(session, raw)
        except _NoActiveOrgError:
            raise HTTPException(
                status_code=400,
                detail="No active organization in Clerk session",
            )
        if clerk_result is None:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session"
            )
        org_id, perms = clerk_result
        if permission not in perms:
            raise HTTPException(
                status_code=403,
                detail=f"Session role lacks '{permission}' permission",
            )
        return AuthContext(
            org_id=org_id,
            api_key=None,
            tier=IamTier.CUSTOMER,
        )

    return _check


def require_staff_or_customer_admin():
    """Dependency: allow Vera staff (read-only) OR customer-admin (full
    rights on the org). Used by the staff audit-log endpoint which must
    work for both:

      * The staff member checking their own activity history.
      * The customer admin checking which Vera engineers touched their
        org's data.

    Returns the same ``AuthContext`` shape as
    ``require_permission_with_context``. Staff sessions DO satisfy the
    gate (no extra 403). Customer sessions must hold the ``admin``
    permission — API-key admin or Clerk-session admin role.
    """
    from .baa import is_org_baa_active

    async def _check(
        credentials: HTTPAuthorizationCredentials = Security(security),
        session: AsyncSession = Depends(get_db),
        x_org_id: Optional[str] = Header(default=None, alias="X-Org-Id"),
    ) -> AuthContext:
        raw = credentials.credentials

        # API-key path — must be admin.
        if raw.startswith(settings.api_key_prefix):
            api_key = await authenticate_request(session, raw)
            if api_key is None:
                raise HTTPException(
                    status_code=401, detail="Invalid or revoked API key"
                )
            if "admin" not in api_key.permissions:
                raise HTTPException(
                    status_code=403,
                    detail="API key lacks 'admin' permission",
                )
            # Live-key BAA gate — same as require_permission. Keeps
            # behaviour parity so an expired BAA can't read the audit log
            # either.
            if api_key.kind == "live":
                baa_active = await is_org_baa_active(session, api_key.org_id)
                if not baa_active:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "baa_expired",
                            "detail": (
                                "Live API keys require an active Business "
                                "Associate Agreement on file for your "
                                "organization."
                            ),
                            "fix_url": "/customers",
                        },
                    )
            return AuthContext(
                org_id=api_key.org_id,
                api_key=api_key,
                tier=IamTier.CUSTOMER,
            )

        # Clerk path — staff bypass the admin gate; customer admin must
        # match the admin role.
        staff_ctx = await _resolve_clerk_staff_context(
            session, raw, requested_org_id=x_org_id
        )
        if staff_ctx is not None:
            return staff_ctx

        try:
            clerk_result = await _authenticate_clerk_session(session, raw)
        except _NoActiveOrgError:
            raise HTTPException(
                status_code=400,
                detail="No active organization in Clerk session",
            )
        if clerk_result is None:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session"
            )
        org_id, perms = clerk_result
        if "admin" not in perms:
            raise HTTPException(
                status_code=403,
                detail="Session role lacks 'admin' permission",
            )
        return AuthContext(
            org_id=org_id,
            api_key=None,
            tier=IamTier.CUSTOMER,
        )

    return _check


async def get_membership_for_clerk_user(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    clerk_org_id: str,
) -> OrgMembership | None:
    """Look up the OrgMembership row for a (Clerk user, Clerk org) pair.

    Helper used by Clerk-authenticated dashboard routes that need to resolve
    the active session's user to a backend org + role. Returns ``None`` if
    the user has no membership in the given Clerk org.
    """
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == clerk_user_id,
            OrgMembership.clerk_org_id == clerk_org_id,
        )
    )
    return result.scalar_one_or_none()
