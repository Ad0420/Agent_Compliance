"""Webhook event tests for Phase 1 PR 3 — Stream B items B3 + B5.

Covers v1-implementation-plan Phase 1 Stream B:
  * B3 — ``new_agent_type_detected`` fires once on first auto-discovery
    of a (customer, agent_type) tuple. Subsequent actions that only
    touch ``last_seen_at`` MUST NOT re-emit (Codex E1: stamp is
    historical).
  * B5 — ``cross_org_tenant_collision`` fires once when an org auto-
    discovers a ``tenant_id`` that already exists under another org.
    The event is delivered to the discovering org ONLY. Payload is
    PHI-safe: just ``org_id``, ``tenant_id``, ``other_org_ids``,
    ``detected_at`` — no display_name / contact / Customer.id from
    the colliding orgs.

Test conventions mirror ``test_webhooks.py`` (mock httpx, flush
asyncio.create_task background work, assert against the captured POST
bodies).
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import (
    ChainState,
    Customer,
    Organization,
    WebhookSubscription,
)
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record


# ── helpers ────────────────────────────────────────────────────────────────


def _ok_mock_client():
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
    """Drain ``asyncio.create_task`` work — mirror of test_webhooks.py helper."""
    for _ in range(100):
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return
        await asyncio.wait(
            pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED
        )


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
        event_types=event_types or ["new_agent_type_detected"],
        is_active=is_active,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


def _envelopes_for(
    mock_client, event_type: str
) -> list[dict]:
    """Return the parsed event envelopes of the given type that were POSTed."""
    out: list[dict] = []
    for call in mock_client.post.await_args_list:
        body = call.kwargs.get("content")
        if not body:
            continue
        envelope = json.loads(body.decode("utf-8"))
        if envelope.get("event_type") == event_type:
            out.append(envelope)
    return out


# ── B3.1: fires once on first auto-discovery, never again ────────────────


@pytest.mark.asyncio
async def test_new_agent_type_detected_fires_once_then_idempotent(
    db_session, org_and_key
):
    """First action with a (tenant_id, action_class) creates the
    CustomerAgent row and fires ``new_agent_type_detected``. A second
    action with the same tuple just touches ``last_seen_at`` and MUST
    NOT re-emit (Codex E1: stamp is historical)."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/agent-type",
        secret="s1",
        event_types=["new_agent_type_detected"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="chart_entry",
            ),
        )
        await _flush_tasks()
        first_round = list(mock_client.post.await_args_list)

        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="chart_entry",
            ),
        )
        await _flush_tasks()

    # Exactly one ``new_agent_type_detected`` across both actions.
    detected = _envelopes_for(mock_client, "new_agent_type_detected")
    assert len(detected) == 1, (
        f"Expected exactly one new_agent_type_detected event, "
        f"got {len(detected)}: {detected}"
    )

    envelope = detected[0]
    assert envelope["org_id"] == org.id

    payload = envelope["data"]
    assert payload["org_id"] == org.id
    assert payload["tenant_id"] == "cleveland_clinic"
    assert payload["agent_name"] == "scribe-agent"
    assert payload["agent_type"] == "chart_entry"
    assert payload["source"] == "auto_discovered"
    assert payload["confidence"] == "high"
    assert payload["customer_id"]
    assert payload["agent_id"]
    assert payload["detected_at"]

    # Sanity: the first round of POSTs already contained the only
    # ``new_agent_type_detected`` event — the second action did not
    # add a new one.
    first_detected = [
        json.loads(c.kwargs["content"].decode("utf-8"))
        for c in first_round
        if json.loads(c.kwargs["content"].decode("utf-8")).get(
            "event_type"
        )
        == "new_agent_type_detected"
    ]
    assert len(first_detected) == 1


# ── B3.2: separate events for separate (customer, agent_type) tuples ─────


@pytest.mark.asyncio
async def test_new_agent_type_detected_per_tuple(db_session, org_and_key):
    """Two distinct tenant_ids with the same agent_name → two events
    (one per Customer). Two distinct action_classes under the same
    tenant → two events (one per CustomerAgent row)."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/per-tuple",
        secret="s2",
        event_types=["new_agent_type_detected"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        # Two different customers → two CustomerAgent rows → two events.
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="chart_entry",
            ),
        )
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="other_clinic",
                action_class="chart_entry",
            ),
        )
        # Same customer, different action_class → second CustomerAgent
        # row under cleveland_clinic → third event.
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="prior_auth_request",
                agent_name="prior-auth-agent",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="prior_auth",
            ),
        )
        await _flush_tasks()

    detected = _envelopes_for(mock_client, "new_agent_type_detected")
    assert len(detected) == 3
    keys = {
        (e["data"]["tenant_id"], e["data"]["agent_type"]) for e in detected
    }
    assert keys == {
        ("cleveland_clinic", "chart_entry"),
        ("other_clinic", "chart_entry"),
        ("cleveland_clinic", "prior_auth"),
    }


# ── B3.3: historical stamping respected — later agent_type change no-op ──


@pytest.mark.asyncio
async def test_new_agent_type_detected_respects_historical_stamp(
    db_session, org_and_key
):
    """First action stamps the CustomerAgent row with the historical
    ``agent_type``. Later actions for the SAME (customer, agent_type)
    must not fire — even if the SDK's later actions arrive with a
    different agent_name or supplemental metadata, the unique
    constraint is on ``(customer_id, agent_type)`` so the row is
    re-used and ``new_agent_type_detected`` stays silent."""
    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/historical",
        secret="s3",
        event_types=["new_agent_type_detected"],
    )

    mock_client = _ok_mock_client()
    with patch("app.services.webhooks.httpx.AsyncClient", return_value=mock_client):
        # First action: stamps agent_type='chart_entry' on the
        # CustomerAgent row.
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-v1",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="chart_entry",
            ),
        )
        # Second action: same action_class, different agent_name. The
        # CustomerAgent row exists already (uq is on customer_id +
        # agent_type), so no row is created — no event fires.
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-v2",
                result="success",
                tenant_id="cleveland_clinic",
                action_class="chart_entry",
            ),
        )
        await _flush_tasks()

    detected = _envelopes_for(mock_client, "new_agent_type_detected")
    assert len(detected) == 1
    # The historical stamp is from the FIRST action.
    assert detected[0]["data"]["agent_name"] == "scribe-v1"
    assert detected[0]["data"]["agent_type"] == "chart_entry"


# ── B5.1: cross_org_tenant_collision delivered to discovering org only ───


@pytest.mark.asyncio
async def test_cross_org_collision_fires_on_discovering_org_only(
    db_session, org_and_key, db_engine
):
    """Org B discovers a tenant_id Org A already owns → Org B's
    subscriber receives the event; Org A's subscriber does NOT.
    Payload contains the colliding org's UUID in ``other_org_ids``."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    org_a, _, _ = org_and_key

    # Build Org B in the same engine.
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as setup:
        org_b = Organization(name="org-b-collision-target")
        setup.add(org_b)
        await setup.flush()
        setup.add(ChainState(org_id=org_b.id))
        await setup.commit()
        org_b_id = org_b.id

    # Org A already owns the tenant_id.
    pre_existing = Customer(
        org_id=org_a.id,
        tenant_id="abridge",
        display_name="Org A's Abridge",
        status="active",
        baa_status="active",
    )
    db_session.add(pre_existing)
    await db_session.commit()

    # Org A subscribed: MUST NOT receive the event.
    await _make_subscription(
        db_session,
        org_a.id,
        url="https://hooks.example.com/org-a",
        secret="sa",
        event_types=["cross_org_tenant_collision"],
    )

    # Org B subscribed: MUST receive the event.
    async with session_factory() as setup_b:
        sub_b = WebhookSubscription(
            org_id=org_b_id,
            url="https://hooks.example.com/org-b",
            secret="sb",
            event_types=["cross_org_tenant_collision"],
        )
        setup_b.add(sub_b)
        await setup_b.commit()

    mock_client = _ok_mock_client()
    # Use Org B's own session for the action (mirrors how a real
    # request would be dispatched — each org has its own session).
    async with session_factory() as session_b:
        with patch(
            "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
        ):
            await build_and_insert_record(
                session_b,
                org_b_id,
                ActionRecordCreate(
                    action_name="chart_entry",
                    agent_name="scribe-agent",
                    result="success",
                    tenant_id="abridge",
                    action_class="chart_entry",
                ),
            )
            await _flush_tasks()

    collision_calls = [
        c
        for c in mock_client.post.await_args_list
        if json.loads(c.kwargs["content"].decode("utf-8")).get("event_type")
        == "cross_org_tenant_collision"
    ]
    # Exactly one — delivered to Org B's URL only.
    assert len(collision_calls) == 1
    assert collision_calls[0].args[0] == "https://hooks.example.com/org-b"

    envelope = json.loads(collision_calls[0].kwargs["content"].decode("utf-8"))
    assert envelope["event_type"] == "cross_org_tenant_collision"
    assert envelope["org_id"] == org_b_id

    payload = envelope["data"]
    assert payload["org_id"] == org_b_id
    assert payload["tenant_id"] == "abridge"
    assert payload["other_org_ids"] == [org_a.id]
    assert payload["detected_at"]


# ── B5.2: PHI-safety — payload contains ONLY the documented fields ───────


@pytest.mark.asyncio
async def test_cross_org_collision_payload_is_phi_safe(
    db_session, org_and_key, db_engine
):
    """The payload MUST contain only ``org_id``, ``tenant_id``,
    ``other_org_ids``, ``detected_at``. No display_name, no contact,
    no Customer.id from the colliding org may leak through."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    org_a, _, _ = org_and_key
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Org A's Customer carries fields that MUST NEVER appear in the
    # cross-org payload.
    leaky = Customer(
        org_id=org_a.id,
        tenant_id="abridge",
        display_name="Cleveland Clinic — Cardiology Pilot",
        contact_email="ops-pii@cleveland-secret.example",
        status="active",
        baa_status="active",
    )
    db_session.add(leaky)
    await db_session.commit()

    async with session_factory() as setup:
        org_b = Organization(name="org-b-phi-check")
        setup.add(org_b)
        await setup.flush()
        setup.add(ChainState(org_id=org_b.id))
        await setup.commit()
        org_b_id = org_b.id

        sub_b = WebhookSubscription(
            org_id=org_b_id,
            url="https://hooks.example.com/org-b-phi",
            secret="sb",
            event_types=["cross_org_tenant_collision"],
        )
        setup.add(sub_b)
        await setup.commit()

    mock_client = _ok_mock_client()
    async with session_factory() as session_b:
        with patch(
            "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
        ):
            await build_and_insert_record(
                session_b,
                org_b_id,
                ActionRecordCreate(
                    action_name="chart_entry",
                    agent_name="scribe-agent",
                    result="success",
                    tenant_id="abridge",
                ),
            )
            await _flush_tasks()

    collision_envelopes = [
        json.loads(c.kwargs["content"].decode("utf-8"))
        for c in mock_client.post.await_args_list
        if json.loads(c.kwargs["content"].decode("utf-8")).get("event_type")
        == "cross_org_tenant_collision"
    ]
    assert len(collision_envelopes) == 1
    payload = collision_envelopes[0]["data"]

    # Strict schema match: ONLY these four keys.
    assert set(payload.keys()) == {
        "org_id",
        "tenant_id",
        "other_org_ids",
        "detected_at",
    }

    # Defensive: even the serialized BODY must not carry Org A's
    # display_name or contact_email anywhere.
    body_str = collision_envelopes[0]
    body_serialized = json.dumps(body_str)
    assert "Cleveland Clinic" not in body_serialized
    assert "cleveland-secret" not in body_serialized
    # Customer.id of Org A must not leak either.
    assert leaky.id not in body_serialized


# ── B5.3: idempotency — second colliding action does not re-emit ─────────


@pytest.mark.asyncio
async def test_cross_org_collision_idempotent(
    db_session, org_and_key, db_engine
):
    """Once Org B has auto-discovered the colliding tenant_id, the
    Customer row exists for Org B too — subsequent actions only touch
    ``last_seen_at`` and MUST NOT re-emit. Mirrors the
    ``new_agent_type_detected`` idempotency contract."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    org_a, _, _ = org_and_key

    # Seed Org A's customer.
    pre_existing = Customer(
        org_id=org_a.id,
        tenant_id="abridge",
        display_name="Org A",
        status="active",
    )
    db_session.add(pre_existing)
    await db_session.commit()

    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as setup:
        org_b = Organization(name="org-b-idempotent")
        setup.add(org_b)
        await setup.flush()
        setup.add(ChainState(org_id=org_b.id))
        await setup.commit()
        org_b_id = org_b.id

        setup.add(
            WebhookSubscription(
                org_id=org_b_id,
                url="https://hooks.example.com/org-b-idem",
                secret="sb",
                event_types=["cross_org_tenant_collision"],
            )
        )
        await setup.commit()

    mock_client = _ok_mock_client()
    async with session_factory() as session_b:
        with patch(
            "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
        ):
            # First action: Customer row created for Org B → event fires.
            await build_and_insert_record(
                session_b,
                org_b_id,
                ActionRecordCreate(
                    action_name="chart_entry",
                    agent_name="scribe-agent",
                    result="success",
                    tenant_id="abridge",
                ),
            )
            # Second action: Customer row already exists for Org B →
            # only last_seen_at advances → no event.
            await build_and_insert_record(
                session_b,
                org_b_id,
                ActionRecordCreate(
                    action_name="chart_entry",
                    agent_name="scribe-agent",
                    result="success",
                    tenant_id="abridge",
                ),
            )
            await _flush_tasks()

    collisions = [
        c
        for c in mock_client.post.await_args_list
        if json.loads(c.kwargs["content"].decode("utf-8")).get("event_type")
        == "cross_org_tenant_collision"
    ]
    assert len(collisions) == 1


# ── B3+B5: delivery failure does not roll back the chain ─────────────────


@pytest.mark.asyncio
async def test_event_delivery_failure_does_not_rollback_chain(
    db_session, org_and_key
):
    """If the webhook endpoint 5xx's (or raises), the chain MUST stay
    intact. ``dispatch_event`` is fire-and-forget — bookkeeping records
    the failure but never propagates an exception."""
    from sqlalchemy import select
    from app.models import ActionRecord, CustomerAgent

    org, _, _ = org_and_key
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/will-fail",
        secret="s",
        event_types=["new_agent_type_detected"],
    )

    # Force the HTTP layer to raise the way a DNS failure or connection
    # reset would.
    failing_client = AsyncMock()
    failing_client.__aenter__ = AsyncMock(return_value=failing_client)
    failing_client.__aexit__ = AsyncMock(return_value=False)
    failing_client.post = AsyncMock(side_effect=RuntimeError("simulated"))

    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=failing_client
    ):
        record = await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="rollback_safe_tenant",
                action_class="chart_entry",
            ),
        )
        await _flush_tasks()

    # Chain advance landed.
    assert record is not None
    assert record.tenant_id == "rollback_safe_tenant"
    stored = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.id == record.id)
        )
    ).scalar_one()
    assert stored.id == record.id

    # Auto-discovery rows landed too (this is the whole point of running
    # dispatch AFTER commit — the audit data must be durable before any
    # delivery attempt).
    customer = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "rollback_safe_tenant")
        )
    ).scalar_one()
    ca = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalar_one()
    assert ca.agent_type == "chart_entry"

    # The failing endpoint was actually called (proving we tried).
    assert failing_client.post.await_count >= 1


# ── B3: unsubscribed orgs see no delivery ────────────────────────────────


@pytest.mark.asyncio
async def test_new_agent_type_detected_no_subscription_no_delivery(
    db_session, org_and_key
):
    """If nobody subscribed to ``new_agent_type_detected``, no HTTP
    call should be made (even though auto-discovery still happens)."""
    from sqlalchemy import select
    from app.models import CustomerAgent

    org, _, _ = org_and_key
    # Subscribed to a different event type — must not receive
    # new_agent_type_detected.
    await _make_subscription(
        db_session,
        org.id,
        url="https://hooks.example.com/other",
        secret="s",
        event_types=["policy.violation"],
    )

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        await build_and_insert_record(
            db_session,
            org.id,
            ActionRecordCreate(
                action_name="chart_entry",
                agent_name="scribe-agent",
                result="success",
                tenant_id="silent_tenant",
                action_class="chart_entry",
            ),
        )
        await _flush_tasks()

    # No POSTs for any event (the only sub is for policy.violation,
    # which didn't fire).
    mock_client.post.assert_not_awaited()

    # But the CustomerAgent row still exists — auto-discovery is not
    # gated on subscriptions.
    customer = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "silent_tenant")
        )
    ).scalar_one()
    ca = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalar_one()
    assert ca.agent_type == "chart_entry"


# ── Subscription endpoint accepts the new event types ────────────────────


@pytest.mark.asyncio
async def test_subscription_endpoint_accepts_new_event_types(
    async_client, org_and_key
):
    """The existing POST /v1/webhooks schema validator pulls from
    ALLOWED_EVENT_TYPES; the new types should pass without any
    schema-level changes."""
    _, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/agent-type-sub",
            "event_types": [
                "new_agent_type_detected",
                "cross_org_tenant_collision",
            ],
            "description": "Auto-discovery signals",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["event_types"]) == {
        "new_agent_type_detected",
        "cross_org_tenant_collision",
    }
