"""Tests for the X-Request-ID middleware."""

import re
import uuid

import pytest


# Loose UUID4 hex shape (32 hex chars). The middleware uses uuid4().hex.
_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


@pytest.mark.asyncio
async def test_response_includes_request_id_header(async_client):
    resp = await async_client.get("/health")
    assert resp.status_code in (200, 503)
    assert "x-request-id" in {k.lower() for k in resp.headers.keys()}
    rid = resp.headers["x-request-id"]
    assert rid  # non-empty


@pytest.mark.asyncio
async def test_generated_request_id_looks_like_uuid4_hex(async_client):
    resp = await async_client.get("/health")
    rid = resp.headers["x-request-id"]
    assert _UUID_HEX_RE.match(rid), (
        f"expected uuid4 hex, got {rid!r}"
    )
    # Sanity: the value should round-trip through uuid.UUID
    uuid.UUID(rid)


@pytest.mark.asyncio
async def test_incoming_request_id_is_echoed(async_client):
    incoming = "client-supplied-correlation-id-123"
    resp = await async_client.get(
        "/health",
        headers={"X-Request-ID": incoming},
    )
    assert resp.headers["x-request-id"] == incoming


@pytest.mark.asyncio
async def test_each_request_gets_a_distinct_id_when_not_supplied(async_client):
    a = await async_client.get("/health")
    b = await async_client.get("/health")
    assert a.headers["x-request-id"] != b.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_id_present_on_authenticated_routes(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "rid_test",
            "action_type": "function_call",
            "agent_name": "test-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_request_id_present_on_error_responses(async_client):
    # Hitting a protected route without auth should still get a request id.
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
    )
    assert resp.status_code in (401, 403, 422)
    assert resp.headers.get("x-request-id")
