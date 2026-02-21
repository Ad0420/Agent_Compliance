"""Integration tests for all API endpoints."""

import pytest
import pytest_asyncio

from app.services.auth import generate_api_key


# ── Actions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_action(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "test_action",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_name"] == "test_action"
    assert data["sequence_number"] == 1
    assert data["previous_hash"] == "GENESIS"


@pytest.mark.asyncio
async def test_create_action_batch(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions/batch",
        json={
            "records": [
                {"action_name": f"batch_{i}", "action_type": "function_call",
                 "agent_name": "test-agent", "result": "success"}
                for i in range(3)
            ]
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3


@pytest.mark.asyncio
async def test_list_actions(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    # Create an action first
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "list_test",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["records"]) >= 1


@pytest.mark.asyncio
async def test_get_action(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    create_resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "get_test",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    record_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/v1/actions/{record_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == record_id


@pytest.mark.asyncio
async def test_get_action_not_found(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/actions/nonexistent-id",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


# ── Agents ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_agent(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/agents",
        json={"name": "test-agent", "description": "A test agent"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-agent"


@pytest.mark.asyncio
async def test_list_agents(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_agent_not_found(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/agents/nonexistent-id",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


# ── Verification ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_chain(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/verify",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "is_valid" in data


@pytest.mark.asyncio
async def test_verify_single_record(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    # Create a record first
    create_resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "verify_single",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    record_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/v1/verify/{record_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["record_hash_valid"] is True
    assert data["chain_link_valid"] is True


# ── Checkpoints ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_checkpoint(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    # Need at least one record
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "checkpoint_test",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.post(
        "/v1/verify/checkpoints",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "signature" in data
    assert data["sequence_at_checkpoint"] >= 1


@pytest.mark.asyncio
async def test_list_checkpoints(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/verify/checkpoints",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "checkpoints" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_verify_checkpoints(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    # Create a record and checkpoint first
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "verify_cp_test",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    await async_client.post(
        "/v1/verify/checkpoints",
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.post(
        "/v1/verify/checkpoints/verify",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "all_valid" in data
    assert "total_checked" in data


# ── Organizations ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_organization(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations",
        json={"name": "new-test-org"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-test-org"


@pytest.mark.asyncio
async def test_get_current_organization(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-org"


# ── API Keys ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_api_key(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/api-keys",
        json={"name": "new-key", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "raw_key" in data
    assert data["name"] == "new-key"


@pytest.mark.asyncio
async def test_list_api_keys(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_revoke_api_key(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    # Create a key to revoke
    create_resp = await async_client.post(
        "/v1/api-keys",
        json={"name": "to-revoke", "permissions": ["read"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    key_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/v1/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "API key revoked"


# ── Auth error cases ───────────────────────────────────────


@pytest.mark.asyncio
async def test_401_for_missing_key(async_client):
    resp = await async_client.get("/v1/actions")
    assert resp.status_code == 403  # HTTPBearer returns 403 for missing token


@pytest.mark.asyncio
async def test_401_for_invalid_key(async_client):
    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": "Bearer invalid_key_12345"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_403_for_insufficient_permissions(async_client, org_and_key, db_session):
    org, _, _ = org_and_key
    # Create a read-only key
    raw_key, _ = await generate_api_key(
        db_session, org.id, "read-only", ["read"]
    )

    # Try to create an action (requires write)
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "forbidden",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


# ── Health ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(async_client):
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
