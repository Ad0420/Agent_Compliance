"""Per-route RBAC tests (Workstream F1).

Covers the role matrix from ``mvp-hardening-plan.md``:

    list/view records, approvals, violations, exports, verify  →
        admin, developer, compliance_reviewer
    mint/revoke API keys                                       → admin only
    compliance review-trail                                    → admin,
                                                                  compliance_reviewer

Test shape: parameterized across role tokens + an unauthenticated case.
For each role, we assert that allowed roles get 2xx (or 4xx-but-not-403
when the resource simply doesn't exist) and disallowed roles get 403.
Unauthenticated calls get 401.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.config import settings
from app.models import ChainState, Organization, OrgMembership
from app.services import auth as auth_service
from app.main import app

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


@pytest_asyncio.fixture
async def org_with_members(db_session):
    """Seed a backend org + one membership per backend role."""
    org = Organization(name="rbac-test-org", clerk_org_id="org_rbac_test")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))

    members = {
        "admin": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_admin",
            clerk_org_id="org_rbac_test",
            role="admin",
        ),
        "developer": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_dev",
            clerk_org_id="org_rbac_test",
            role="developer",
        ),
        "compliance_reviewer": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_compliance",
            clerk_org_id="org_rbac_test",
            role="compliance_reviewer",
        ),
    }
    for m in members.values():
        db_session.add(m)
    await db_session.commit()
    await db_session.refresh(org)
    return {
        "org": org,
        "clerk_org_id": "org_rbac_test",
        "users": {
            "admin": "user_admin",
            "developer": "user_dev",
            "compliance_reviewer": "user_compliance",
        },
    }


def _token_for(role: str, keypair, org_with_members) -> str:
    return sign_token(
        keypair["priv"],
        sub=org_with_members["users"][role],
        org_id=org_with_members["clerk_org_id"],
    )


# ── Read tier — all three roles allowed ──────────────────────────────────────


@pytest.mark.parametrize(
    "role,expected_ok",
    [
        ("admin", True),
        ("developer", True),
        ("compliance_reviewer", True),
    ],
)
@pytest.mark.asyncio
async def test_list_actions_rbac(
    async_client, keypair, org_with_members, role, expected_ok
):
    token = _token_for(role, keypair, org_with_members)
    resp = await async_client.get(
        "/v1/dashboard/actions",
        headers={"Authorization": f"Bearer {token}"},
    )
    if expected_ok:
        assert resp.status_code == 200, resp.text
    else:
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_actions_unauthenticated(async_client):
    resp = await async_client.get("/v1/dashboard/actions")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "role",
    ["admin", "developer", "compliance_reviewer"],
)
@pytest.mark.asyncio
async def test_compliance_summary_all_three_roles(
    async_client, keypair, org_with_members, role
):
    token = _token_for(role, keypair, org_with_members)
    resp = await async_client.get(
        "/v1/dashboard/compliance/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ── Write tier — admin only ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "role,expected_status",
    [
        ("admin", 200),
        ("developer", 403),
        ("compliance_reviewer", 403),
    ],
)
@pytest.mark.asyncio
async def test_mint_api_key_rbac(
    async_client, keypair, org_with_members, role, expected_status
):
    token = _token_for(role, keypair, org_with_members)
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": f"rbac-{role}", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == expected_status, resp.text


@pytest.mark.asyncio
async def test_revoke_api_key_only_admin(
    async_client, keypair, org_with_members
):
    admin_token = _token_for("admin", keypair, org_with_members)
    create = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "to-revoke", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 200
    key_id = create.json()["id"]

    for role, expected in [
        ("developer", 403),
        ("compliance_reviewer", 403),
        ("admin", 200),
    ]:
        token = _token_for(role, keypair, org_with_members)
        resp = await async_client.delete(
            f"/v1/dashboard/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == expected, f"role={role}: {resp.text}"


# ── Review-trail tier — admin + compliance_reviewer, developer 403'd ────────


@pytest.mark.parametrize(
    "role,expected_status",
    [
        ("admin", 200),
        ("compliance_reviewer", 200),
        ("developer", 403),
    ],
)
@pytest.mark.asyncio
async def test_review_trail_rbac(
    async_client, keypair, org_with_members, role, expected_status
):
    token = _token_for(role, keypair, org_with_members)
    resp = await async_client.get(
        "/v1/dashboard/compliance/review-trail",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == expected_status, resp.text


@pytest.mark.asyncio
async def test_review_trail_unauthenticated(async_client):
    resp = await async_client.get("/v1/dashboard/compliance/review-trail")
    assert resp.status_code == 401


# ── No active org context — every gated route must 400 ──────────────────────


@pytest.mark.asyncio
async def test_no_org_context_returns_400(async_client, keypair):
    token = sign_token(
        keypair["priv"], sub="user_homeless", org_id=None
    )
    for path in [
        "/v1/dashboard/actions",
        "/v1/dashboard/api-keys",
        "/v1/dashboard/compliance/summary",
        "/v1/dashboard/compliance/review-trail",
    ]:
        resp = await async_client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 400, f"{path}: got {resp.status_code}"
