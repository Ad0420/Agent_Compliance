"""Tests for /v1/dashboard/api-keys (Workstream E4).

We re-use the JWT signing setup from ``test_clerk_auth.py`` so we exercise
the real ``require_clerk_role`` dependency end-to-end. Memberships are
inserted directly via the test session to isolate from the webhook code path.
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import settings
from app.models import APIKey, Organization, OrgMembership, ChainState
from app.services import auth as auth_service


_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "dash-kid-1"


def _pubkey_to_jwk(public_key) -> dict[str, Any]:
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = _pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": _TEST_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    # Reset the in-memory rate-limit store so tests in this file don't
    # trip the per-IP burst limit when run after the webhook test suite.
    from app.main import app

    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)
    yield
    auth_service._reset_jwks_cache_for_tests()


def _sign(
    priv,
    *,
    sub: str,
    org_id: str,
    expires_in: int = 300,
) -> str:
    iat = int(time.time())
    claims = {
        "sub": sub,
        "iss": _TEST_ISSUER,
        "iat": iat,
        "exp": iat + expires_in,
        "org_id": org_id,
    }
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": _TEST_KID})


@pytest_asyncio.fixture
async def clerk_org(db_session):
    """Provision a backend Organization linked to a Clerk org, with admin
    and developer memberships ready for the test JWTs to reference."""
    org = Organization(name="dash-test-org", clerk_org_id="org_clerk_dash")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))

    admin = OrgMembership(
        org_id=org.id,
        clerk_user_id="user_admin",
        clerk_org_id="org_clerk_dash",
        role="admin",
    )
    dev = OrgMembership(
        org_id=org.id,
        clerk_user_id="user_dev",
        clerk_org_id="org_clerk_dash",
        role="developer",
    )
    db_session.add_all([admin, dev])
    await db_session.commit()
    await db_session.refresh(org)
    return {
        "org": org,
        "clerk_org_id": "org_clerk_dash",
        "admin_user_id": "user_admin",
        "dev_user_id": "user_dev",
    }


def _admin_token(keypair, clerk_org):
    return _sign(
        keypair["priv"],
        sub=clerk_org["admin_user_id"],
        org_id=clerk_org["clerk_org_id"],
    )


def _dev_token(keypair, clerk_org):
    return _sign(
        keypair["priv"],
        sub=clerk_org["dev_user_id"],
        org_id=clerk_org["clerk_org_id"],
    )


# ── list ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_keys_as_admin_works(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []  # empty list, no keys yet


@pytest.mark.asyncio
async def test_list_keys_as_developer_works(async_client, keypair, clerk_org):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_keys_unauthenticated_returns_401(async_client):
    resp = await async_client.get("/v1/dashboard/api-keys")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_keys_no_org_context_returns_400(async_client, keypair):
    # Token without org_id claim
    iat = int(time.time())
    token = jwt.encode(
        {"sub": "user_homeless", "iss": _TEST_ISSUER, "iat": iat, "exp": iat + 300},
        keypair["priv"],
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_keys_non_member_returns_403(async_client, keypair, clerk_org):
    # Valid token but user has no membership row in this org
    token = _sign(
        keypair["priv"],
        sub="user_stranger",
        org_id=clerk_org["clerk_org_id"],
    )
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── create ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_key_as_admin_works(async_client, keypair, clerk_org, db_session):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "prod-key", "permissions": ["read", "write"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "raw_key" in body
    assert body["raw_key"].startswith(settings.api_key_prefix)
    assert body["key_prefix"] == body["raw_key"][:12]
    assert body["name"] == "prod-key"

    # Key actually persisted under the org
    result = await db_session.execute(
        select(APIKey).where(APIKey.id == body["id"])
    )
    api_key = result.scalar_one()
    assert api_key.org_id == clerk_org["org"].id


@pytest.mark.asyncio
async def test_create_key_as_developer_returns_403(async_client, keypair, clerk_org):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "shouldnt-work", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_returns_raw_key_only_once(async_client, keypair, clerk_org):
    """The raw key is shown ONCE on POST; a subsequent GET must NOT include
    it (only the prefix is returned in the list response)."""
    token = _admin_token(keypair, clerk_org)
    create = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "once-only", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 200
    raw_key = create.json()["raw_key"]
    list_resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    keys = list_resp.json()
    serialised = json.dumps(keys)
    assert raw_key not in serialised, "raw key leaked in list endpoint!"


# ── revoke ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_key_as_admin_works(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    create = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "to-revoke", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = create.json()["id"]
    resp = await async_client.delete(
        f"/v1/dashboard/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Revoking twice fails with 400
    resp2 = await async_client.delete(
        f"/v1/dashboard/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_revoke_key_as_developer_returns_403(async_client, keypair, clerk_org):
    admin_token = _admin_token(keypair, clerk_org)
    create = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "dev-cant-revoke", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    key_id = create.json()["id"]

    dev_token = _dev_token(keypair, clerk_org)
    resp = await async_client.delete(
        f"/v1/dashboard/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 403


# ── X-Request-ID propagation (Phase 1 contract) ──────────────────────────────


@pytest.mark.asyncio
async def test_request_id_in_response(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "x-request-id" in {k.lower() for k in resp.headers.keys()}
