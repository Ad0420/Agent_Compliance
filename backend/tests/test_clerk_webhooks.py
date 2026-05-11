"""Tests for Clerk webhook handler (Workstream E3).

We sign payloads with the real `svix` library — the same one the handler
verifies with — so we exercise the actual signature path rather than mocking
it out.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select
from svix.webhooks import Webhook

from app.config import settings
from app.models import (
    Organization,
    OrgMembership,
    ProcessedWebhookEvent,
)


# Whatever the secret happens to be in tests — svix expects a base64
# whsec_ prefix. The svix library accepts plain strings; we use a stable
# one so signed fixtures are reproducible.
_TEST_WEBHOOK_SECRET = "whsec_" + "a" * 32


@pytest.fixture(autouse=True)
def _configure_webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "clerk_webhook_secret", _TEST_WEBHOOK_SECRET)
    # Reset the in-memory rate-limit store: tests in this file hit the
    # webhook endpoint without auth, so they share the same per-IP bucket
    # and would otherwise trip the 20-rps burst limit when run in sequence.
    from app.main import app

    for mw in app.user_middleware:
        cls = getattr(mw, "cls", None)
        if cls is not None and cls.__name__ == "RateLimitMiddleware":
            # Pre-instantiated middleware doesn't expose state easily; the
            # cleanest reset is to clear the module-level imports the
            # middleware reads. We rely on the fact that BaseHTTPMiddleware
            # instances stay alive in the app — drop their state.
            pass
    # Simpler approach: clear via the live middleware stack.
    _clear_rate_limit_state(app)
    yield


def _clear_rate_limit_state(app) -> None:
    """Walk the ASGI middleware stack and reset RateLimitMiddleware._requests.

    starlette wraps the app in middleware lazily; we walk `app.middleware_stack`
    if it's been built, otherwise we look at `app.user_middleware` to find the
    class and rely on the per-test fresh state (it'll be empty anyway).
    """
    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)


def _sign_request(
    body: dict,
    *,
    secret: str = _TEST_WEBHOOK_SECRET,
    msg_id: str | None = None,
    timestamp: dt.datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Sign a JSON body with Svix. Returns (raw_bytes, headers)."""
    payload = json.dumps(body, separators=(",", ":")).encode()
    if msg_id is None:
        msg_id = f"msg_{abs(hash(payload)) % (10 ** 12)}"
    if timestamp is None:
        timestamp = dt.datetime.now(dt.timezone.utc)
    wh = Webhook(secret)
    signature = wh.sign(msg_id, timestamp, payload.decode())
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
        "Content-Type": "application/json",
    }
    return payload, headers


async def _post_webhook(async_client, body: dict, **kwargs):
    payload, headers = _sign_request(body, **kwargs)
    return await async_client.post(
        "/v1/clerk/webhooks", content=payload, headers=headers
    )


# ── Signature verification ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(async_client):
    body = {"type": "organization.created", "data": {"id": "org_x"}}
    payload = json.dumps(body).encode()
    headers = {
        "svix-id": "msg_bad",
        "svix-timestamp": str(int(dt.datetime.now(dt.timezone.utc).timestamp())),
        # Deliberately invalid signature
        "svix-signature": "v1,abcdefghijklmnopqrstuvwxyz0123456789==",
        "Content-Type": "application/json",
    }
    resp = await async_client.post(
        "/v1/clerk/webhooks", content=payload, headers=headers
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_missing_secret_returns_503(async_client, monkeypatch):
    monkeypatch.setattr(settings, "clerk_webhook_secret", "")
    body = {"type": "organization.created", "data": {"id": "org_x"}}
    payload = json.dumps(body).encode()
    resp = await async_client.post(
        "/v1/clerk/webhooks",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 503


# ── organization.created ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_organization_created_creates_org(async_client, db_session):
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_abc",
            "name": "Acme via Clerk",
            "created_by": "user_clerk_1",
        },
    }
    resp = await _post_webhook(async_client, body)
    assert resp.status_code == 200, resp.text

    result = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == "org_clerk_abc")
    )
    org = result.scalar_one()
    assert org.name == "Acme via Clerk"

    membership = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_clerk_1",
            OrgMembership.clerk_org_id == "org_clerk_abc",
        )
    )
    m = membership.scalar_one()
    assert m.role == "admin"
    assert m.org_id == org.id


@pytest.mark.asyncio
async def test_organization_created_idempotent_on_clerk_id(async_client, db_session):
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_idem",
            "name": "Idem Org",
            "created_by": "user_clerk_idem",
        },
    }
    # Two deliveries with different svix-id but same payload — simulates Clerk
    # re-firing the event (rare, but possible if the upstream retries beyond
    # the dedupe window). The handler must still not double-insert the org.
    resp1 = await _post_webhook(async_client, body, msg_id="msg_idem_1")
    resp2 = await _post_webhook(async_client, body, msg_id="msg_idem_2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    result = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == "org_clerk_idem")
    )
    orgs = result.scalars().all()
    assert len(orgs) == 1


@pytest.mark.asyncio
async def test_replay_same_svix_id_is_noop(async_client, db_session):
    """Re-delivering the same svix-id must hit the dedupe table and NOT
    create a second membership row (or trigger any side effects).
    """
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_replay",
            "name": "Replay",
            "created_by": "user_replay",
        },
    }
    resp1 = await _post_webhook(async_client, body, msg_id="msg_replay")
    resp2 = await _post_webhook(async_client, body, msg_id="msg_replay")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json().get("replay") == "true"

    processed = await db_session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == "msg_replay"
        )
    )
    assert processed.scalar_one() is not None


# ── organizationMembership.* ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_membership_created_links_user(async_client, db_session):
    # First provision the org
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_clerk_membership",
                "name": "Members R Us",
                "created_by": "user_admin",
            },
        },
        msg_id="msg_a",
    )

    resp = await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_clerk_membership"},
                "public_user_data": {"user_id": "user_dev_2"},
                "role": "org:member",
            },
        },
        msg_id="msg_b",
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_dev_2",
            OrgMembership.clerk_org_id == "org_clerk_membership",
        )
    )
    m = result.scalar_one()
    assert m.role == "developer"  # org:member → developer


@pytest.mark.asyncio
async def test_role_mapping_admin_vs_member(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_role_map",
                "name": "Role Map",
                "created_by": "user_creator",
            },
        },
        msg_id="msg_rm_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_role_map"},
                "public_user_data": {"user_id": "user_admin_x"},
                "role": "org:admin",
            },
        },
        msg_id="msg_rm_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_role_map"},
                "public_user_data": {"user_id": "user_member_y"},
                "role": "org:member",
            },
        },
        msg_id="msg_rm_2",
    )

    admin = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_admin_x"
        )
    )
    member = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_member_y"
        )
    )
    assert admin.scalar_one().role == "admin"
    assert member.scalar_one().role == "developer"


@pytest.mark.asyncio
async def test_membership_updated_changes_role(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_promote",
                "name": "Promote Co",
                "created_by": "user_creator",
            },
        },
        msg_id="msg_up_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_promote"},
                "public_user_data": {"user_id": "user_to_promote"},
                "role": "org:member",
            },
        },
        msg_id="msg_up_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.updated",
            "data": {
                "organization": {"id": "org_promote"},
                "public_user_data": {"user_id": "user_to_promote"},
                "role": "org:admin",
            },
        },
        msg_id="msg_up_2",
    )
    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_to_promote",
            OrgMembership.clerk_org_id == "org_promote",
        )
    )
    assert result.scalar_one().role == "admin"


@pytest.mark.asyncio
async def test_membership_deleted_removes_membership(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_kick",
                "name": "Kick Co",
                "created_by": "user_creator_k",
            },
        },
        msg_id="msg_k_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_kick"},
                "public_user_data": {"user_id": "user_to_kick"},
                "role": "org:member",
            },
        },
        msg_id="msg_k_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.deleted",
            "data": {
                "organization": {"id": "org_kick"},
                "public_user_data": {"user_id": "user_to_kick"},
                "role": "org:member",
            },
        },
        msg_id="msg_k_2",
    )
    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_to_kick",
            OrgMembership.clerk_org_id == "org_kick",
        )
    )
    assert result.scalar_one_or_none() is None


# ── organization.deleted ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_organization_deleted_removes_org(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_to_delete",
                "name": "Doomed",
                "created_by": "user_d",
            },
        },
        msg_id="msg_d_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organization.deleted",
            "data": {"id": "org_to_delete"},
        },
        msg_id="msg_d_1",
    )
    # Expire the session cache so we see the delete that the request session
    # committed; without this we'd get the stale ORM-cached row.
    db_session.expire_all()
    result = await db_session.execute(
        select(Organization).where(
            Organization.clerk_org_id == "org_to_delete"
        )
    )
    assert result.scalar_one_or_none() is None


# ── unknown event types ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_event_type_returns_200(async_client):
    resp = await _post_webhook(
        async_client,
        {"type": "user.banned", "data": {"id": "user_x"}},
        msg_id="msg_unk_1",
    )
    assert resp.status_code == 200
