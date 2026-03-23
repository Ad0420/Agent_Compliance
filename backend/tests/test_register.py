"""Tests for the self-serve registration endpoint POST /v1/register."""

import pytest


# ── Happy path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_creates_org_and_returns_key(async_client):
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "Acme Corp"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["org_name"] == "Acme Corp"
    assert "org_id" in data
    assert "api_key" in data
    assert "key_prefix" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_register_key_starts_with_prefix(async_client):
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "prefix-test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_key"].startswith("al_live_")
    assert data["key_prefix"] == data["api_key"][:12]


@pytest.mark.asyncio
async def test_register_requires_no_auth(async_client):
    """Register must succeed with no Authorization header at all."""
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "no-auth-org"},
        # Deliberately no headers=
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_key_is_immediately_usable(async_client):
    """The returned API key must work immediately for authenticated requests."""
    reg = await async_client.post(
        "/v1/register",
        json={"org_name": "usable-key-org"},
    )
    assert reg.status_code == 200
    api_key = reg.json()["api_key"]

    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "usable-key-org"


@pytest.mark.asyncio
async def test_register_key_has_admin_permissions(async_client):
    """Default key from registration must have read, write, and admin permissions."""
    reg = await async_client.post(
        "/v1/register",
        json={"org_name": "admin-perm-org"},
    )
    assert reg.status_code == 200
    api_key = reg.json()["api_key"]

    # Admin permission: can list API keys
    resp = await async_client.get(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200

    # Write permission: can record an action
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "first_action",
            "action_type": "decision",
            "agent_name": "my-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_chain_state_initialized(async_client):
    """Chain state must start at sequence 0 / GENESIS for a new org."""
    reg = await async_client.post(
        "/v1/register",
        json={"org_name": "chain-init-org"},
    )
    assert reg.status_code == 200
    api_key = reg.json()["api_key"]

    # First action must get sequence_number = 1, previous_hash = GENESIS
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "genesis_action",
            "action_type": "function_call",
            "agent_name": "agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sequence_number"] == 1
    assert data["previous_hash"] == "GENESIS"


@pytest.mark.asyncio
async def test_register_org_name_is_stripped(async_client):
    """Leading/trailing whitespace in org_name must be stripped."""
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "  Trimmed Name  "},
    )
    assert resp.status_code == 200
    assert resp.json()["org_name"] == "Trimmed Name"


@pytest.mark.asyncio
async def test_register_multiple_orgs_are_independent(async_client):
    """Registering twice creates two separate orgs with different IDs and keys."""
    r1 = await async_client.post("/v1/register", json={"org_name": "org-one"})
    r2 = await async_client.post("/v1/register", json={"org_name": "org-two"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    d1, d2 = r1.json(), r2.json()
    assert d1["org_id"] != d2["org_id"]
    assert d1["api_key"] != d2["api_key"]

    # Each key only sees its own org
    me1 = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {d1['api_key']}"},
    )
    me2 = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {d2['api_key']}"},
    )
    assert me1.json()["name"] == "org-one"
    assert me2.json()["name"] == "org-two"


# ── Input validation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_register_empty_name_rejected(async_client):
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_whitespace_only_name_rejected(async_client):
    """A name of only whitespace becomes empty after strip() and must be rejected."""
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "   "},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_name_too_long_rejected(async_client):
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": "x" * 201},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_body_rejected(async_client):
    resp = await async_client.post("/v1/register", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_null_name_rejected(async_client):
    resp = await async_client.post(
        "/v1/register",
        json={"org_name": None},
    )
    assert resp.status_code == 422
