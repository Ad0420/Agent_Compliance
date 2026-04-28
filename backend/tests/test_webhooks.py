"""Tests for webhook subscriptions: API surface, dispatch, signing, retries.

Covers (cross-referenced to phase-2C task spec):

1.  POST /v1/webhooks returns secret once; GET /v1/webhooks and
    GET /v1/webhooks/{id} never return the secret.
2.  POST /v1/webhooks with invalid url scheme -> 422.
3.  POST /v1/webhooks with empty event_types -> 422.
4.  POST /v1/webhooks with unknown event type -> 422.
5.  POST /v1/webhooks/{id}/rotate returns a new secret; old secret no
    longer signs valid signatures.
6.  DELETE /v1/webhooks/{id} removes the row.
7.  Non-admin key gets 403.
8.  Cross-org isolation: org A cannot see org B's webhooks.
9.  Delivery test: action triggering a policy fires `policy.violation`
    delivery with the right URL, headers, and body.
10. HMAC signature is verifiable end-to-end.
11. No matching subscription -> no httpx calls.
12. Inactive subscription -> no httpx calls.
13. Non-2xx response -> consecutive_failures increments.
14. 20 consecutive failures -> subscription auto-disabled.
15. Approval lifecycle -> approval.requested + approval.resolved fired.
"""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models import (
    APIKey,
    ChainState,
    Organization,
    Policy,
    WebhookSubscription,
)
from app.schemas.action import ActionRecordCreate
from app.schemas.approval import ApprovalCreate, ApprovalDecision
from app.services.approvals import (
    decide_approval,
    cancel_approval,
    request_approval,
)
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record
from app.services.webhooks import (
    ALLOWED_EVENT_TYPES,
    AUTO_DISABLE_AFTER_FAILURES,
    _canonical_body,
    compute_signature,
    dispatch_event,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _ok_mock_client():
    """Build an httpx.AsyncClient mock that returns 200 on every POST."""
    response = MagicMock()
    response.status_code = 200
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


def _err_mock_client(status_code: int = 500):
    response = MagicMock()
    response.status_code = status_code
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


async def _flush_tasks():
    """Yield enough times for asyncio.create_task'd coroutines to run."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _make_subscription(
    session,
    org_id: str,
    *,
    url: str = "https://hooks.example.com/in",
    secret: str = "test-secret",
    event_types: list[str] | None = None,
    is_active: bool = True,
) -> WebhookSubscription:
    sub = WebhookSubscription(
        org_id=org_id,
        url=url,
        secret=secret,
        event_types=event_types or ["policy.violation"],
        is_active=is_active,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


# ── 1. Create returns secret once; list/get never expose it ────────────────


@pytest.mark.asyncio
async def test_create_webhook_returns_secret_once(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/in",
            "event_types": ["policy.violation"],
            "description": "Slack pager",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "secret" in body
    assert body["secret"]
    assert body["url"] == "https://hooks.example.com/in"
    assert body["event_types"] == ["policy.violation"]
    sub_id = body["id"]

    list_resp = await async_client.get(
        "/v1/webhooks", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["webhooks"]
    assert len(items) == 1
    assert "secret" not in items[0]

    get_resp = await async_client.get(
        f"/v1/webhooks/{sub_id}", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert get_resp.status_code == 200
    assert "secret" not in get_resp.json()


# ── 2/3/4. Validation errors ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_webhook_invalid_scheme_rejected(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={"url": "ftp://bad.example.com", "event_types": ["policy.violation"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_webhook_empty_event_types_rejected(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={"url": "https://x.example.com", "event_types": []},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_webhook_unknown_event_type_rejected(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://x.example.com",
            "event_types": ["completely.bogus"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


# ── 5. Rotate secret ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotate_secret_changes_signing(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    create_resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/rot",
            "event_types": ["policy.violation"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    sub_id = body["id"]
    old_secret = body["secret"]

    rotate_resp = await async_client.post(
        f"/v1/webhooks/{sub_id}/rotate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert rotate_resp.status_code == 200
    new_secret = rotate_resp.json()["secret"]
    assert new_secret != old_secret

    # The old secret must no longer match a signature produced with the new one.
    payload = {"event_id": "x", "event_type": "policy.violation",
               "org_id": "o", "occurred_at": "now", "data": {}}
    body_bytes = _canonical_body(payload)
    new_sig = compute_signature(new_secret, body_bytes)
    old_sig = compute_signature(old_secret, body_bytes)
    assert new_sig != old_sig


# ── 6. Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_webhook_removes_row(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/del",
            "event_types": ["policy.violation"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    sub_id = resp.json()["id"]

    del_resp = await async_client.delete(
        f"/v1/webhooks/{sub_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert del_resp.status_code == 200

    miss = await async_client.get(
        f"/v1/webhooks/{sub_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert miss.status_code == 404


# ── 7. Non-admin key is forbidden ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_webhooks(async_client, org_and_key, db_session):
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "writer-only", ["read", "write"])

    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://x.example.com",
            "event_types": ["policy.violation"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403

    list_resp = await async_client.get(
        "/v1/webhooks", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert list_resp.status_code == 403


# ── 8. Cross-org isolation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_isolation(async_client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org_a = Organization(name="webhook-org-a")
        org_b = Organization(name="webhook-org-b")
        session.add_all([org_a, org_b])
        await session.flush()
        session.add_all([ChainState(org_id=org_a.id), ChainState(org_id=org_b.id)])
        await session.commit()
        org_a_id, org_b_id = org_a.id, org_b.id
        key_a, _ = await generate_api_key(session, org_a_id, "a-admin", ["read", "write", "admin"])
        key_b, _ = await generate_api_key(session, org_b_id, "b-admin", ["read", "write", "admin"])

    # Org A creates a webhook
    resp_a = await async_client.post(
        "/v1/webhooks",
        json={"url": "https://a.example.com", "event_types": ["policy.violation"]},
        headers={"Authorization": f"Bearer {key_a}"},
    )
    assert resp_a.status_code == 200
    sub_id = resp_a.json()["id"]

    # Org B cannot see, fetch, or delete it
    list_b = await async_client.get(
        "/v1/webhooks", headers={"Authorization": f"Bearer {key_b}"}
    )
    assert list_b.status_code == 200
    assert list_b.json()["webhooks"] == []

    get_b = await async_client.get(
        f"/v1/webhooks/{sub_id}", headers={"Authorization": f"Bearer {key_b}"}
    )
    assert get_b.status_code == 404

    del_b = await async_client.delete(
        f"/v1/webhooks/{sub_id}", headers={"Authorization": f"Bearer {key_b}"}
    )
    assert del_b.status_code == 404


# ── 9. Delivery test on policy violation ────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_violation_dispatches_webhook(db_session, org_and_key):
    org, _, _ = org_and_key

    # Active policy that fires for unknown agents.
    policy = Policy(
        org_id=org.id,
        name="Unknown agent guard",
        condition_type="unknown_agent",
        condition_params={},
        action="flag",
        severity="high",
        is_active=True,
    )
    db_session.add(policy)
    await db_session.commit()

    secret = "topsecret"
    sub = await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/violations",
        secret=secret,
        event_types=["policy.violation"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="loan_decision",
                agent_name="ghost-agent",
                result="success",
            ),
        )
        await _flush_tasks()

    assert mock_client.post.await_count >= 1
    call = mock_client.post.await_args_list[0]
    assert call.args[0] == "https://hooks.example.com/violations"
    headers = call.kwargs["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Vera-Event"] == "policy.violation"
    assert headers["User-Agent"].startswith("Vera-Webhooks/")
    assert headers["X-Vera-Signature"].startswith("sha256=")

    body_bytes = call.kwargs["content"]
    envelope = json.loads(body_bytes.decode("utf-8"))
    assert envelope["event_type"] == "policy.violation"
    assert envelope["org_id"] == org.id
    data = envelope["data"]
    assert data["policy_name"] == "Unknown agent guard"
    assert data["condition_type"] == "unknown_agent"
    assert data["severity"] == "high"
    assert data["record_id"]


# ── 10. HMAC signature is verifiable end-to-end ─────────────────────────────


@pytest.mark.asyncio
async def test_signature_is_verifiable(db_session, org_and_key):
    org, _, _ = org_and_key
    secret = "shared-secret-1234"
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/sig",
        secret=secret,
        event_types=["policy.violation"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        await dispatch_event(
            db_session,
            org.id,
            "policy.violation",
            {"policy_name": "p", "condition_type": "c", "severity": "low",
             "context": {}, "record_id": "r"},
        )
        await _flush_tasks()

    assert mock_client.post.await_count == 1
    call = mock_client.post.await_args
    body_bytes = call.kwargs["content"]
    sent_sig = call.kwargs["headers"]["X-Vera-Signature"]

    # Recompute on the receiving side.
    expected = (
        "sha256="
        + hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    )
    assert hmac.compare_digest(sent_sig, expected)


# ── 11. No matching sub -> no calls ────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_matching_subscription_no_calls(db_session, org_and_key):
    org, _, _ = org_and_key
    # Subscribed to approval events only.
    await _make_subscription(
        db_session,
        org.id,
        event_types=["approval.requested"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        await dispatch_event(
            db_session, org.id, "policy.violation", {"foo": "bar"}
        )
        await _flush_tasks()

    mock_client.post.assert_not_awaited()


# ── 12. Inactive sub -> no calls ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_subscription_skipped(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        event_types=["policy.violation"],
        is_active=False,
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        await dispatch_event(
            db_session, org.id, "policy.violation", {"x": 1}
        )
        await _flush_tasks()

    mock_client.post.assert_not_awaited()


# ── 13. Non-2xx -> consecutive_failures increments ─────────────────────────


@pytest.mark.asyncio
async def test_non_2xx_increments_consecutive_failures(db_engine, org_and_key):
    """A 5xx response must mark the delivery failed and bump consecutive_failures."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    org, _, _ = org_and_key

    # Use a single session_factory bound to the shared in-memory engine for
    # both seeding and assertion. The patched AsyncSessionLocal points to
    # the same factory so the bookkeeping write is visible afterwards.
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as setup:
        sub = WebhookSubscription(
            org_id=org.id,
            url="https://hooks.example.com/seed",
            secret="s",
            event_types=["policy.violation"],
        )
        setup.add(sub)
        await setup.commit()
        await setup.refresh(sub)
        sub_id = sub.id

    mock_client = _err_mock_client(500)
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.webhooks.AsyncSessionLocal", session_factory):
        async with session_factory() as request_sess:
            await dispatch_event(
                request_sess, org.id, "policy.violation", {"x": 1}
            )
        await _flush_tasks()

    async with session_factory() as verify:
        refreshed = await verify.get(WebhookSubscription, sub_id)
        assert refreshed.consecutive_failures == 1
        assert refreshed.last_delivery_status == "failure"
        assert refreshed.is_active is True


# ── 14. Auto-disable after 20 consecutive failures ─────────────────────────


@pytest.mark.asyncio
async def test_auto_disable_after_threshold_failures(db_engine, org_and_key):
    """Hitting AUTO_DISABLE_AFTER_FAILURES consecutive failures flips is_active off."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    org, _, _ = org_and_key
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as setup:
        sub = WebhookSubscription(
            org_id=org.id,
            url="https://hooks.example.com/almost-dead",
            secret="s",
            event_types=["policy.violation"],
            consecutive_failures=AUTO_DISABLE_AFTER_FAILURES - 1,
        )
        setup.add(sub)
        await setup.commit()
        await setup.refresh(sub)
        sub_id = sub.id

    mock_client = _err_mock_client(503)
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.webhooks.AsyncSessionLocal", session_factory):
        async with session_factory() as request_sess:
            await dispatch_event(
                request_sess, org.id, "policy.violation", {"x": 1}
            )
        await _flush_tasks()

    async with session_factory() as verify:
        refreshed = await verify.get(WebhookSubscription, sub_id)
        assert refreshed.consecutive_failures == AUTO_DISABLE_AFTER_FAILURES
        assert refreshed.is_active is False


# ── 15. Approval lifecycle fires both events ───────────────────────────────


@pytest.mark.asyncio
async def test_approval_lifecycle_fires_request_and_resolve(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        event_types=["approval.requested", "approval.resolved"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        approval = await request_approval(
            db_session,
            org.id,
            ApprovalCreate(
                agent_name="loan-bot",
                action_name="approve_loan",
                action_summary="Approve loan",
                data_subject_id="user_a",
                context={"amount": 100},
                risk_tier="high",
                approvers_required=1,
            ),
        )
        await _flush_tasks()

        await decide_approval(
            db_session,
            org.id,
            approval.id,
            ApprovalDecision(decision="approve", approver="alice@example.com"),
        )
        await _flush_tasks()

    seen_events = [
        json.loads(call.kwargs["content"].decode("utf-8"))["event_type"]
        for call in mock_client.post.await_args_list
    ]
    assert "approval.requested" in seen_events
    assert "approval.resolved" in seen_events


# ── Bonus: cancelled approval fires approval.cancelled ─────────────────────


@pytest.mark.asyncio
async def test_cancel_approval_fires_cancelled(db_session, org_and_key):
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        event_types=["approval.cancelled"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        approval = await request_approval(
            db_session,
            org.id,
            ApprovalCreate(
                agent_name="loan-bot",
                action_name="approve_loan",
                action_summary="Approve loan",
                data_subject_id="user_b",
                context={},
                risk_tier="low",
                approvers_required=1,
            ),
        )
        await _flush_tasks()
        await cancel_approval(db_session, org.id, approval.id, canceller="ops@example.com")
        await _flush_tasks()

    seen_events = [
        json.loads(call.kwargs["content"].decode("utf-8"))["event_type"]
        for call in mock_client.post.await_args_list
    ]
    assert "approval.cancelled" in seen_events


# ── Bonus: ALLOWED_EVENT_TYPES is the documented set ───────────────────────


def test_allowed_event_types_is_complete():
    assert ALLOWED_EVENT_TYPES == frozenset(
        {
            "policy.violation",
            "approval.requested",
            "approval.resolved",
            "approval.cancelled",
            "chain.tampered",
        }
    )


# ── Bonus: canonical body is sorted + compact ──────────────────────────────


def test_canonical_body_is_deterministic():
    a = _canonical_body({"b": 2, "a": 1, "data": {"y": 0, "x": 1}})
    b = _canonical_body({"a": 1, "b": 2, "data": {"x": 1, "y": 0}})
    assert a == b
    # Compact separators (no spaces).
    assert b" " not in a
