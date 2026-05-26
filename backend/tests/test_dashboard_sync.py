"""Integration tests for POST /v1/dashboard/sync-membership.

Exercises the route end-to-end via the real Clerk JWT dependency, with
the Clerk REST API monkey-patched out at the function boundary. Verifies:

  * No bearer token → 401
  * Token without org_id → 400
  * Reconcile succeeds → 200 + membership row in DB
  * Reconcile says "not a member" → 404, no row written
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
from app.models import ChainState, Organization, OrgMembership
from app.services import auth as auth_service
from app.services import clerk_reconcile


_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "sync-kid-1"
_USER = "user_advik"
_ORG = "org_prod_demo"


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
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)

    # Reset the in-memory rate-limit store.
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


def _sign(priv, *, sub: str, org_id: str | None) -> str:
    iat = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": _TEST_ISSUER,
        "iat": iat,
        "exp": iat + 300,
    }
    if org_id is not None:
        claims["org_id"] = org_id
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": _TEST_KID})


@pytest.mark.asyncio
async def test_sync_unauthenticated_returns_401(async_client):
    resp = await async_client.post("/v1/dashboard/sync-membership")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sync_without_org_id_claim_returns_400(async_client, keypair):
    token = _sign(keypair["priv"], sub=_USER, org_id=None)
    resp = await async_client.post(
        "/v1/dashboard/sync-membership",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sync_creates_membership_when_clerk_confirms_member(
    async_client, keypair, monkeypatch, db_session
):
    async def _is_admin(*, clerk_user_id, clerk_org_id):
        assert clerk_user_id == _USER
        assert clerk_org_id == _ORG
        return "org:admin"

    async def _org_name(clerk_org_id):
        return "Prod_Demo"

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _is_admin
    )
    monkeypatch.setattr(clerk_reconcile, "_fetch_org_name", _org_name)

    token = _sign(keypair["priv"], sub=_USER, org_id=_ORG)
    resp = await async_client.post(
        "/v1/dashboard/sync-membership",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "synced", "role": "admin"}

    # Row visible in a fresh session.
    membership = (
        await db_session.execute(
            select(OrgMembership).where(
                OrgMembership.clerk_user_id == _USER,
                OrgMembership.clerk_org_id == _ORG,
            )
        )
    ).scalar_one_or_none()
    assert membership is not None
    assert membership.role == "admin"


@pytest.mark.asyncio
async def test_sync_returns_404_when_clerk_says_not_a_member(
    async_client, keypair, monkeypatch, db_session
):
    async def _not_member(*, clerk_user_id, clerk_org_id):
        return None

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _not_member
    )

    token = _sign(keypair["priv"], sub=_USER, org_id=_ORG)
    resp = await async_client.post(
        "/v1/dashboard/sync-membership",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

    rows = (
        await db_session.execute(
            select(OrgMembership).where(OrgMembership.clerk_user_id == _USER)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_auth_path_reconciles_missing_membership(
    async_client, keypair, monkeypatch, db_session
):
    """The whole point of fix #1: hitting a regular Clerk-RBAC route with
    a valid JWT but no membership row should self-heal via reconcile and
    return 200, not 403."""

    async def _is_admin(*, clerk_user_id, clerk_org_id):
        return "org:admin"

    async def _org_name(clerk_org_id):
        return "Prod_Demo"

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _is_admin
    )
    monkeypatch.setattr(clerk_reconcile, "_fetch_org_name", _org_name)

    token = _sign(keypair["priv"], sub=_USER, org_id=_ORG)
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 with an empty list — the org was just provisioned, no keys yet.
    # Without reconcile this would be 403 ("Not a member of this organization").
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
