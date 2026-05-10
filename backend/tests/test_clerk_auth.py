"""Tests for Clerk JWT verification (Workstream E2).

We don't talk to a real Clerk JWKS endpoint. Instead we generate a fixture
RSA keypair, expose it as a JWKS dict, monkey-patch ``_fetch_jwks`` so the
in-process cache is populated from our fixture, then sign test JWTs with
the private half.
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

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

    # Signed 600s ago with 300s ttl → expired.
    token = _sign(
        keypair["primary_priv"],
        now=int(time.time()) - 600,
        expires_in=300,
    )
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_wrong_issuer_returns_401(keypair, patched_jwks):
    from fastapi import HTTPException

    token = _sign(keypair["primary_priv"], issuer="https://evil.example.com")
    with pytest.raises(HTTPException) as exc:
        await auth_service.verify_clerk_jwt(token)
    assert exc.value.status_code == 401
    assert "issuer" in exc.value.detail.lower()


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
    assert "audience" in exc.value.detail.lower()


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
    assert "kid" in exc.value.detail.lower()
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
async def test_dashboard_me_returns_user_claims(async_client, keypair, patched_jwks):
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
