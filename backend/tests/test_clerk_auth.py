"""Tests for Clerk JWT verification (Workstream E2).

We don't talk to a real Clerk JWKS endpoint. Instead we generate a fixture
RSA keypair, expose it as a JWKS dict, monkey-patch ``_fetch_jwks`` so the
in-process cache is populated from our fixture, then sign test JWTs with
the private half.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import settings
from app.services import auth as auth_service


# ── Fixtures ──────────────────────────────────────────────────────────────────

_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "test-kid-1"
_OTHER_KID = "test-kid-rotated"


def _pubkey_to_jwk(public_key) -> dict[str, Any]:
    """Convert a cryptography RSA public key into a JWK dict."""
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


@pytest.fixture(scope="module")
def keypair():
    """Generate a primary keypair + a secondary "rotated" keypair.

    Module-scoped so we don't pay the RSA key-gen cost per test.
    """
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = _pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": _TEST_KID, "alg": "RS256", "use": "sig"})

    priv2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk2 = _pubkey_to_jwk(priv2.public_key())
    jwk2.update({"kid": _OTHER_KID, "alg": "RS256", "use": "sig"})

    return {
        "primary_priv": priv,
        "primary_jwk": jwk,
        "secondary_priv": priv2,
        "secondary_jwk": jwk2,
    }


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch):
    """Set Clerk env so verify_clerk_jwt doesn't 503, reset JWKS cache."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()
    yield
    auth_service._reset_jwks_cache_for_tests()


@pytest.fixture
def patched_jwks(monkeypatch, keypair):
    """Patch ``_fetch_jwks`` to return our test JWKS without HTTP. Tracks
    call count so tests can assert caching behavior.
    """
    state = {"calls": 0, "keys": [keypair["primary_jwk"]]}

    async def _fake_fetch(_url: str) -> dict:
        state["calls"] += 1
        return {"keys": list(state["keys"])}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    return state


def _sign(
    priv: rsa.RSAPrivateKey,
    *,
    kid: str = _TEST_KID,
    issuer: str = _TEST_ISSUER,
    audience: str | None = None,
    expires_in: int = 300,
    now: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    iat = now if now is not None else int(time.time())
    claims: dict[str, Any] = {
        "sub": "user_test_123",
        "iss": issuer,
        "iat": iat,
        "exp": iat + expires_in,
        "email": "alice@example.com",
    }
    if audience is not None:
        claims["aud"] = audience
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": kid})


# ── Unit tests for verify_clerk_jwt ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_jwt_succeeds_returns_claims(keypair, patched_jwks):
    token = _sign(keypair["primary_priv"])
    claims = await auth_service.verify_clerk_jwt(token)
    assert claims["sub"] == "user_test_123"
    assert claims["iss"] == _TEST_ISSUER
    assert claims["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_malformed_jwt_returns_401(patched_jwks):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt("not-a-jwt-at-all")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(keypair, patched_jwks):
    from fastapi import HTTPException

    # Signed 600s ago with 300s ttl → expired (well past the 30s leeway).
    token = _sign(
        keypair["primary_priv"],
        now=int(time.time()) - 600,
        expires_in=300,
    )
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    # Generic detail — we deliberately don't leak why server-side.
    assert exc.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_wrong_issuer_returns_401(keypair, patched_jwks):
    from fastapi import HTTPException

    token = _sign(keypair["primary_priv"], issuer="https://evil.example.com")
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_wrong_audience_returns_401_when_audience_configured(
    keypair, patched_jwks, monkeypatch
):
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "clerk_audience", "expected-aud")

    token = _sign(keypair["primary_priv"], audience="some-other-aud")
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_unknown_kid_returns_401_after_refetch(keypair, patched_jwks):
    """A token signed with an unknown kid should trigger a refetch, then 401
    if still unknown. Verifies the refetch path actually runs once."""
    from fastapi import HTTPException

    # Sign with secondary key; JWKS only contains primary.
    token = _sign(keypair["secondary_priv"], kid=_OTHER_KID)
    initial_calls = patched_jwks["calls"]
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"
    # First call: cold cache. Second call: forced refresh on unknown kid.
    assert patched_jwks["calls"] - initial_calls == 2


@pytest.mark.asyncio
async def test_jwks_caching(keypair, patched_jwks):
    """Two valid verifications within TTL should hit the JWKS once."""
    token1 = _sign(keypair["primary_priv"])
    token2 = _sign(keypair["primary_priv"])

    initial = patched_jwks["calls"]
    await auth_service.verify_clerk_jwt(token1)
    after_first = patched_jwks["calls"]
    await auth_service.verify_clerk_jwt(token2)
    after_second = patched_jwks["calls"]

    # First call populated cache; second call must be a hit.
    assert after_first - initial == 1, "first call should populate cache"
    assert after_second - after_first == 0, "second call should hit cache"


@pytest.mark.asyncio
async def test_unconfigured_clerk_returns_503(keypair, patched_jwks, monkeypatch):
    """If CLERK_JWKS_URL is empty, refuse to verify (don't fail open)."""
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "clerk_jwks_url", "")
    auth_service._reset_jwks_cache_for_tests()

    token = _sign(keypair["primary_priv"])
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 503


# ── Integration tests through the FastAPI app ────────────────────────────────


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(async_client):
    resp = await async_client.get("/v1/dashboard/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_me_returns_user_claims(
    async_client, keypair, patched_jwks, db_session
):
    """Post-Phase-4a F1: ``/v1/dashboard/me`` is RBAC-gated, so we need a
    backing membership row before it returns 200."""
    from app.models import ChainState, Organization, OrgMembership

    org = Organization(name="me-test-org", clerk_org_id="org_test")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_test_123",
            clerk_org_id="org_test",
            role="developer",
        )
    )
    await db_session.commit()

    token = _sign(
        keypair["primary_priv"],
        extra_claims={"org_id": "org_test", "first_name": "Alice"},
    )
    resp = await async_client.get(
        "/v1/dashboard/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clerk_user"]["sub"] == "user_test_123"
    assert body["clerk_user"]["email"] == "alice@example.com"
    assert body["clerk_user"]["org_id"] == "org_test"
    assert body["clerk_user"]["first_name"] == "Alice"
    assert body["membership"]["role"] == "developer"


@pytest.mark.asyncio
async def test_dashboard_me_rejects_expired_token(async_client, keypair, patched_jwks):
    token = _sign(
        keypair["primary_priv"],
        now=int(time.time()) - 600,
        expires_in=300,
    )
    resp = await async_client.get(
        "/v1/dashboard/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_existing_v1_actions_route_still_uses_api_key(
    async_client, org_and_key, keypair, patched_jwks
):
    """Sanity: existing API-key-auth routes are NOT affected by the Clerk
    middleware. A Clerk JWT is rejected at /v1/actions; an API key works.
    """
    _, raw_key, _ = org_and_key

    # Clerk JWT should NOT authenticate against API-key route.
    clerk_token = _sign(keypair["primary_priv"])
    resp_jwt = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {clerk_token}"},
    )
    assert resp_jwt.status_code == 401, (
        "API-key route must reject Clerk JWTs; got "
        f"{resp_jwt.status_code}: {resp_jwt.text}"
    )

    # API key still works.
    resp_key = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "split_auth_sanity",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp_key.status_code == 200, resp_key.text


@pytest.mark.asyncio
async def test_api_key_rejected_at_dashboard_route(async_client, org_and_key, patched_jwks):
    """Mirror of the above: API keys can't unlock dashboard routes."""
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/dashboard/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


# ── Adversarial / hardening tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alg_none_jwt_rejected(keypair, patched_jwks):
    """Forged token with `alg: none` and no signature must be rejected.

    Defends against the classic "alg: none" downgrade attack where an
    attacker strips the signature and sets the algorithm to none.
    """
    import base64
    from fastapi import HTTPException

    def _b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    header = {"alg": "none", "typ": "JWT", "kid": _TEST_KID}
    payload = {
        "sub": "evil",
        "iss": _TEST_ISSUER,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    token = f"{_b64(header)}.{_b64(payload)}."  # empty signature segment

    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_alg_hs256_with_rsa_public_key_rejected(keypair, patched_jwks):
    """Algorithm-confusion attack: sign HS256 using the RSA public key as the
    HMAC secret. Verifier must reject because we pin algorithms=["RS256"].
    """
    import base64
    import hashlib
    import hmac
    import json as _json
    from fastapi import HTTPException
    from cryptography.hazmat.primitives import serialization

    pub_pem = keypair["primary_priv"].public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    def _b64(d) -> str:
        if isinstance(d, dict):
            d = _json.dumps(d).encode()
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    header = {"alg": "HS256", "typ": "JWT", "kid": _TEST_KID}
    payload = {
        "sub": "evil",
        "iss": _TEST_ISSUER,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    signing_input = f"{_b64(header)}.{_b64(payload)}".encode()
    sig = hmac.new(pub_pem, signing_input, hashlib.sha256).digest()
    token = f"{signing_input.decode()}.{_b64(sig)}"

    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_unknown_kid_negative_cached(keypair, patched_jwks):
    """A burst of requests with random unknown kids must NOT fan out to a
    JWKS refetch per request. The negative cache + forced-refresh cooldown
    cap refetches to 1 within the cooldown window.
    """
    from fastapi import HTTPException

    initial_calls = patched_jwks["calls"]

    # 100 requests, each with a distinct random unknown kid.
    for i in range(100):
        bad_kid = f"unknown-kid-{i}"
        token = _sign(keypair["secondary_priv"], kid=bad_kid)
        with pytest.raises(HTTPException) as exc:
            await auth_service.verify_clerk_jwt(token)
        assert exc.value.status_code == 401

    # Cold cache populates once (1 call), then the forced-refresh cooldown
    # blocks subsequent forced refetches. Allow at most 2 (cold-fetch + the
    # very first forced refetch before cooldown engages).
    delta = patched_jwks["calls"] - initial_calls
    assert delta <= 2, (
        f"Expected at most 2 JWKS fetches across 100 unknown-kid requests; "
        f"got {delta}. Negative cache or forced-refresh cooldown is broken."
    )


@pytest.mark.asyncio
async def test_azp_validation_when_configured(keypair, patched_jwks, monkeypatch):
    """Tokens with `azp` outside the allow-list are rejected; in-list pass."""
    from fastapi import HTTPException

    monkeypatch.setattr(
        settings, "clerk_authorized_parties", ["https://allowed.com"]
    )

    # Wrong azp → 401
    bad = _sign(
        keypair["primary_priv"],
        extra_claims={"azp": "https://attacker.com"},
    )
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(bad)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"

    # Right azp → claims returned
    good = _sign(
        keypair["primary_priv"],
        extra_claims={"azp": "https://allowed.com"},
    )
    claims = await auth_service.verify_clerk_jwt(good)
    assert claims["azp"] == "https://allowed.com"


@pytest.mark.asyncio
async def test_azp_unset_means_no_check(keypair, patched_jwks, monkeypatch):
    """When the operator hasn't configured an allow-list, any azp passes
    (or no azp at all). Sanity check that we don't break the default path.
    """
    monkeypatch.setattr(settings, "clerk_authorized_parties", None)
    token = _sign(
        keypair["primary_priv"],
        extra_claims={"azp": "https://anywhere.com"},
    )
    claims = await auth_service.verify_clerk_jwt(token)
    assert claims["sub"] == "user_test_123"


# ── Membership freshness re-check (CRITICAL #5 + #6 fix) ─────────────────────


@pytest.mark.asyncio
async def test_stale_membership_refetched_from_clerk(
    async_client, db_session, keypair, patched_jwks, monkeypatch
):
    """Stale local membership (older than the freshness window) MUST trigger
    a Clerk REST lookup. If Clerk says the user has been demoted, the local
    role is updated AND the RBAC check denies the request.
    """
    from app.models import ChainState, Organization, OrgMembership
    from app.middleware import clerk_auth

    # Seed an org + membership marked as 'admin' but stale (10 min old).
    org = Organization(name="stale-org", clerk_org_id="org_stale")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    stale_at = dt.datetime.utcnow() - dt.timedelta(minutes=10)
    membership = OrgMembership(
        org_id=org.id,
        clerk_user_id="user_stale",
        clerk_org_id="org_stale",
        role="admin",
        updated_at=stale_at,
    )
    db_session.add(membership)
    await db_session.commit()

    # Configure freshness check + a fake Clerk REST that reports the user
    # has been demoted to a developer.
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "membership_freshness_seconds", 60)

    fetch_calls = {"n": 0}

    async def _fake_fetch(*, clerk_user_id, clerk_org_id):
        fetch_calls["n"] += 1
        return "developer"

    monkeypatch.setattr(
        clerk_auth, "_fetch_clerk_membership_role", _fake_fetch
    )

    token = _sign(
        keypair["primary_priv"],
        extra_claims={"sub": "user_stale", "org_id": "org_stale"},
    )
    # Override the fixture `sub` claim — _sign sets it to user_test_123
    # by default. Recompose:
    import jwt as _jwt

    iat = int(time.time())
    token = _jwt.encode(
        {
            "sub": "user_stale",
            "iss": _TEST_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": "org_stale",
        },
        keypair["primary_priv"],
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )

    # The route requires admin → user got demoted to developer → 403.
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "x", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert fetch_calls["n"] == 1

    # Backend row got updated to reflect Clerk reality.
    db_session.expire_all()
    refreshed = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_stale"
        )
    )
    row = refreshed.scalar_one()
    assert row.role == "developer"
    # updated_at was bumped forward.
    assert row.updated_at > stale_at


@pytest.mark.asyncio
async def test_fresh_membership_skips_clerk_fetch(
    async_client, db_session, keypair, patched_jwks, monkeypatch
):
    """Cached membership within the freshness window must NOT consult Clerk."""
    from app.models import ChainState, Organization, OrgMembership
    from app.middleware import clerk_auth

    org = Organization(name="fresh-org", clerk_org_id="org_fresh")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_fresh",
            clerk_org_id="org_fresh",
            role="admin",
            updated_at=dt.datetime.utcnow(),  # brand new
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "membership_freshness_seconds", 300)

    async def _explode(**_kwargs):
        raise AssertionError("Clerk fetch should not have been called")

    monkeypatch.setattr(
        clerk_auth, "_fetch_clerk_membership_role", _explode
    )

    import jwt as _jwt

    iat = int(time.time())
    token = _jwt.encode(
        {
            "sub": "user_fresh",
            "iss": _TEST_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": "org_fresh",
        },
        keypair["primary_priv"],
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_clerk_unreachable_uses_cached_role_with_warn(
    async_client, db_session, keypair, patched_jwks, monkeypatch, caplog
):
    """If the Clerk REST call fails, we log WARN and fall back to cached
    role — availability beats consistency for a defense-in-depth check.
    """
    import logging

    import httpx

    from app.models import ChainState, Organization, OrgMembership
    from app.middleware import clerk_auth

    org = Organization(name="warn-org", clerk_org_id="org_warn")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_warn",
            clerk_org_id="org_warn",
            role="admin",
            updated_at=dt.datetime.utcnow() - dt.timedelta(minutes=10),
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "membership_freshness_seconds", 60)

    async def _boom(**_kwargs):
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr(
        clerk_auth, "_fetch_clerk_membership_role", _boom
    )

    import jwt as _jwt

    iat = int(time.time())
    token = _jwt.encode(
        {
            "sub": "user_warn",
            "iss": _TEST_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": "org_warn",
        },
        keypair["primary_priv"],
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )
    with caplog.at_level(logging.WARNING, logger="app.middleware.clerk_auth"):
        resp = await async_client.get(
            "/v1/dashboard/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    assert any(
        "freshness check failed" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_user_kicked_from_org_revokes_access_within_freshness_window(
    async_client, db_session, keypair, patched_jwks, monkeypatch
):
    """CRITICAL #6 closure: a JWT may still be valid for ~60s after the
    user was removed from the Clerk org. The freshness re-check must
    return ``None`` from Clerk (user no longer a member) → 403 + cached
    row deleted.
    """
    from app.models import ChainState, Organization, OrgMembership
    from app.middleware import clerk_auth

    org = Organization(name="kicked-org", clerk_org_id="org_kicked")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_kicked",
            clerk_org_id="org_kicked",
            role="admin",
            updated_at=dt.datetime.utcnow() - dt.timedelta(minutes=10),
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "membership_freshness_seconds", 60)

    async def _no_longer_member(**_kwargs):
        return None  # signal: not in org

    monkeypatch.setattr(
        clerk_auth, "_fetch_clerk_membership_role", _no_longer_member
    )

    import jwt as _jwt

    iat = int(time.time())
    token = _jwt.encode(
        {
            "sub": "user_kicked",
            "iss": _TEST_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": "org_kicked",
        },
        keypair["primary_priv"],
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    # Local membership was deleted.
    db_session.expire_all()
    gone = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_kicked"
        )
    )
    assert gone.scalar_one_or_none() is None
