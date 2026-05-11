"""End-to-end smoke test for E3 + E4 + E5.

Walks the full Clerk → org → membership → API key → action flow that a
new user goes through after Phase 3 ships. If this test passes, the
release is wired correctly end-to-end.

Steps:
  1. POST /v1/clerk/webhooks  organization.created  → backend org exists
  2. POST /v1/clerk/webhooks  organizationMembership.created (admin) →
     membership exists
  3. GET  /v1/dashboard/api-keys  with Clerk JWT (admin) → empty list
  4. POST /v1/dashboard/api-keys  with Clerk JWT → returns raw key
  5. POST /v1/actions  with the raw key → 200, audit record persisted
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
from svix.webhooks import Webhook

from app.config import settings
from app.models import ActionRecord, Organization, OrgMembership
from app.services import auth as auth_service


_TEST_ISSUER = "https://e2e-clerk.example.com"
_TEST_KID = "e2e-kid"
_WEBHOOK_SECRET = "whsec_" + "e" * 32


def _pubkey_to_jwk(public_key) -> dict[str, Any]:
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


@pytest.fixture(scope="module")
def e2e_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = _pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": _TEST_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


@pytest.fixture(autouse=True)
def _configure(monkeypatch, e2e_keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(settings, "clerk_webhook_secret", _WEBHOOK_SECRET)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [e2e_keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    # Reset rate-limit state — webhook + dashboard test runs upstream may
    # have saturated the per-IP bucket.
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


def _sign_webhook(body: dict, msg_id: str) -> tuple[bytes, dict[str, str]]:
    payload = json.dumps(body, separators=(",", ":")).encode()
    ts = dt.datetime.now(dt.timezone.utc)
    wh = Webhook(_WEBHOOK_SECRET)
    signature = wh.sign(msg_id, ts, payload.decode())
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(ts.timestamp())),
        "svix-signature": signature,
        "Content-Type": "application/json",
    }
    return payload, headers


def _sign_jwt(priv, *, sub: str, org_id: str) -> str:
    iat = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "iss": _TEST_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": org_id,
        },
        priv,
        algorithm="RS256",
        headers={"kid": _TEST_KID},
    )


@pytest.mark.asyncio
async def test_full_clerk_to_api_key_to_action_flow(
    async_client, db_session, e2e_keypair
):
    clerk_org_id = "org_e2e_xyz"
    clerk_user_id = "user_e2e_alice"

    # 1. Webhook: organization.created
    payload, headers = _sign_webhook(
        {
            "type": "organization.created",
            "data": {
                "id": clerk_org_id,
                "name": "E2E Acme",
                "created_by": clerk_user_id,
            },
        },
        msg_id="msg_e2e_1",
    )
    r1 = await async_client.post(
        "/v1/clerk/webhooks", content=payload, headers=headers
    )
    assert r1.status_code == 200, r1.text

    # Verify org + admin membership exist
    org_row = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = org_row.scalar_one()
    member_row = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == clerk_user_id,
            OrgMembership.clerk_org_id == clerk_org_id,
        )
    )
    assert member_row.scalar_one().role == "admin"

    # 2. (covered by organization.created above — created_by becomes admin)

    # 3. List API keys via Clerk JWT — initially empty
    token = _sign_jwt(e2e_keypair["priv"], sub=clerk_user_id, org_id=clerk_org_id)
    list_resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json() == []

    # 4. Mint a new API key as the admin user
    mint_resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "e2e-key", "permissions": ["read", "write"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mint_resp.status_code == 200, mint_resp.text
    raw_key = mint_resp.json()["raw_key"]
    assert raw_key.startswith(settings.api_key_prefix)

    # 5. Use the minted API key to record an action — full audit trail unlocked
    action_resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "e2e_first_action",
            "action_type": "function_call",
            "agent_name": "e2e-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert action_resp.status_code == 200, action_resp.text

    # Audit row landed under the backend org we provisioned via webhook
    actions = await db_session.execute(
        select(ActionRecord).where(ActionRecord.org_id == org.id)
    )
    rows = actions.scalars().all()
    assert len(rows) == 1
    assert rows[0].action_name == "e2e_first_action"
