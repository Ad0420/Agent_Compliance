"""Tests for ``GET /v1/customers/{tenant_id}/decisions`` (PR C1.5).

Covers the server-side join introduced to replace C1's client-side
adapter. The C1 frontend tab read ``reasoning.gate_ruling`` /
``reasoning.webhook_delivery`` / ``reasoning.hitl_expires_at`` out of
``ActionRecord`` — keys the backend never wrote. This endpoint joins
``ActionRecord`` ⋈ ``Approval`` ⋈ ``WebhookDelivery`` server-side and
returns the composite shape the dashboard renders directly.

Coverage matrix
---------------

  * 200 happy path with mixed allow / HITL rows
  * 200 empty (customer with no actions yet)
  * 200 pagination (limit=2, offset=2)
  * 200 ordering (sequence_number DESC)
  * 401 (no auth)
  * 403 (read-only key without ``read`` perm — actually require_permission
    grants developer/admin; we use a write-only-style negative case)
  * 404 (tenant_id with no Customer row)
  * 404 (Customer belongs to another org — must not leak)
  * Multi-tenant isolation
  * Ruling field populated from Approval.context
  * webhook_delivery populated for HITL approvals with a delivery
  * hitl_expires_at surfaced only for pending approvals
  * ALLOW (no-approval) actions get ruling=None (documented limitation)
  * Webhook ``pending`` + attempt_count=3 + next_retry_at set → ``retrying``
  * Webhook ``succeeded`` → ``delivered``
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    ActionRecord,
    Approval,
    ChainState,
    Customer,
    Organization,
    WebhookDelivery,
    WebhookSubscription,
)
from app.services.auth import generate_api_key


# ── Helpers ─────────────────────────────────────────────────────────────


async def _make_customer(db_session, *, org_id: str, tenant_id: str) -> Customer:
    customer = Customer(
        org_id=org_id,
        tenant_id=tenant_id,
        display_name=tenant_id,
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


async def _seed_action(
    db_session,
    *,
    org_id: str,
    tenant_id: str,
    sequence_number: int,
    agent_name: str = "scribe-agent",
    action_name: str = "chart_entry",
    action_type: str = "function_call",
    result: str = "success",
    action_timestamp: datetime | None = None,
) -> ActionRecord:
    """Insert an ActionRecord directly without going through the chain.

    Tests don't need full hash-chain validation — the join logic is what
    matters here. We supply unique ``previous_hash`` / ``record_hash``
    placeholders so the UniqueConstraint on (org_id, sequence_number)
    holds without bumping ChainState.
    """
    record = ActionRecord(
        org_id=org_id,
        sequence_number=sequence_number,
        previous_hash=f"prev-{sequence_number}",
        record_hash=f"hash-{sequence_number}",
        agent_name=agent_name,
        action_name=action_name,
        action_type=action_type,
        action_timestamp=action_timestamp or datetime(2026, 5, 24, 12, sequence_number, 0),
        authorized_by="test-suite",
        tenant_id=tenant_id,
        result=result,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def _seed_approval(
    db_session,
    *,
    org_id: str,
    request_record_id: str | None,
    context: dict,
    status: str = "pending",
    expires_at: datetime | None = None,
    action_summary: str | None = None,
) -> Approval:
    approval = Approval(
        org_id=org_id,
        request_record_id=request_record_id,
        requested_by_agent="scribe-agent",
        action_name="chart_entry",
        action_summary=action_summary,
        context=context,
        risk_tier="high",
        approvers_required=1,
        status=status,
        decisions=[],
        requested_at=datetime(2026, 5, 24, 12, 0, 0),
        expires_at=expires_at,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


async def _seed_subscription(
    db_session, *, org_id: str
) -> WebhookSubscription:
    sub = WebhookSubscription(
        org_id=org_id,
        url="https://example.test/hook",
        secret="test-secret",
        event_types=["review.requested"],
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_delivery(
    db_session,
    *,
    org_id: str,
    sub_id: str,
    approval_id: str,
    status: str,
    attempt_count: int = 1,
    next_retry_at: datetime | None = None,
    succeeded_at: datetime | None = None,
    aborted_at: datetime | None = None,
    last_status_code: int | None = None,
    created_at: datetime | None = None,
    event_type: str = "review.requested",
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        subscription_id=sub_id,
        org_id=org_id,
        event_type=event_type,
        payload={"review_id": approval_id},
        status=status,
        attempt_count=attempt_count,
        next_retry_at=next_retry_at,
        succeeded_at=succeeded_at,
        aborted_at=aborted_at,
        last_status_code=last_status_code,
        idempotency_key=f"{approval_id}:{event_type}",
    )
    db_session.add(delivery)
    await db_session.commit()
    await db_session.refresh(delivery)
    if created_at is not None:
        # Override the server_default — useful when seeding multiple
        # deliveries per approval to assert "latest wins".
        delivery.created_at = created_at
        await db_session.commit()
        await db_session.refresh(delivery)
    return delivery


# ── 200 paths ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decisions_happy_path_mixed_rows(
    async_client, org_and_key, db_session
):
    """Five actions, two with approvals + webhook deliveries (one
    delivered, one retrying). Response is correctly shaped per row.
    """
    org, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}
    await _make_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")

    # 5 actions, sequence 1..5 (newest first by sequence_number desc).
    actions = []
    for i in range(1, 6):
        actions.append(
            await _seed_action(
                db_session,
                org_id=org.id,
                tenant_id="cleveland_clinic",
                sequence_number=i,
            )
        )
    # Approval on action #4 (will get webhook delivered).
    approval4 = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=actions[3].id,
        context={
            "gate_name": "new_diagnosis_gate",
            "required_role": "attending_physician",
            "citation": "HIPAA 164.312(b)",
            "reason": "gated",
        },
        status="pending",
        expires_at=datetime(2026, 5, 24, 16, 0, 0),
        action_summary="Reviewer must confirm new diagnosis (CMS).",
    )
    # Approval on action #5 (retrying webhook).
    approval5 = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=actions[4].id,
        context={
            "gate_name": "controlled_substance_gate",
            "required_role": "dea_licensed_physician",
            "citation": "21 CFR 1306.04",
            "reason": "gated",
        },
        status="pending",
        expires_at=datetime(2026, 5, 24, 16, 0, 0),
        action_summary="DEA-licensed physician must approve.",
    )
    sub = await _seed_subscription(db_session, org_id=org.id)
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval4.id,
        status="succeeded",
        attempt_count=1,
        succeeded_at=datetime(2026, 5, 24, 12, 30, 0),
        last_status_code=200,
    )
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval5.id,
        status="pending",
        attempt_count=3,
        next_retry_at=datetime(2026, 5, 24, 13, 0, 0),
        last_status_code=503,
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/decisions", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert body["limit"] == 50
    assert body["offset"] == 0
    decisions = body["decisions"]
    assert len(decisions) == 5
    # Ordered newest first (sequence_number DESC → 5, 4, 3, 2, 1).
    assert [d["sequence_number"] for d in decisions] == [5, 4, 3, 2, 1]

    # Action #5 (first row) — retrying webhook + Ruling.
    row5 = decisions[0]
    assert row5["ruling"] is not None
    assert row5["ruling"]["effect"] == "require_hitl"
    assert row5["ruling"]["required_role"] == "dea_licensed_physician"
    assert row5["ruling"]["gate_name"] == "controlled_substance_gate"
    assert row5["ruling"]["review_id"] == approval5.id
    assert row5["ruling"]["reason_detail"] == "DEA-licensed physician must approve."
    assert row5["webhook_delivery"] is not None
    assert row5["webhook_delivery"]["status"] == "retrying"
    assert row5["webhook_delivery"]["attempt_count"] == 3
    assert row5["webhook_delivery"]["max_attempts"] == 7
    assert row5["webhook_delivery"]["next_retry_at"] is not None
    assert row5["webhook_delivery"]["last_status_code"] == 503
    assert row5["hitl_expires_at"] is not None

    # Action #4 — delivered webhook + Ruling.
    row4 = decisions[1]
    assert row4["ruling"]["gate_name"] == "new_diagnosis_gate"
    assert row4["webhook_delivery"]["status"] == "delivered"
    assert row4["webhook_delivery"]["succeeded_at"] is not None
    assert row4["webhook_delivery"]["last_status_code"] == 200

    # Action #3 (no approval) — ruling/webhook/hitl all None.
    row3 = decisions[2]
    assert row3["ruling"] is None
    assert row3["webhook_delivery"] is None
    assert row3["hitl_expires_at"] is None


@pytest.mark.asyncio
async def test_decisions_empty_customer(
    async_client, org_and_key, db_session
):
    """Customer with zero ActionRecords → empty decisions list."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["decisions"] == []
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_decisions_pagination(
    async_client, org_and_key, db_session
):
    """limit=2&offset=2 returns rows 3-4 in DESC order (so sequences
    3 and 2 if there are 5 rows total)."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    for i in range(1, 6):
        await _seed_action(
            db_session,
            org_id=org.id,
            tenant_id="cleveland_clinic",
            sequence_number=i,
        )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/decisions?limit=2&offset=2",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert [d["sequence_number"] for d in body["decisions"]] == [3, 2]


@pytest.mark.asyncio
async def test_decisions_default_ordering_is_sequence_desc(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="cleveland_clinic")
    for i in [3, 1, 4, 2]:
        await _seed_action(
            db_session,
            org_id=org.id,
            tenant_id="cleveland_clinic",
            sequence_number=i,
        )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [d["sequence_number"] for d in body["decisions"]] == [4, 3, 2, 1]


# ── Auth + scoping ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decisions_requires_auth(async_client, org_and_key, db_session):
    org, _, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")

    resp = await async_client.get("/v1/customers/acme/decisions")
    # No auth header → 401 (require_permission rejects missing bearer).
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_decisions_forbidden_for_write_only_key(
    async_client, org_and_key, db_session
):
    """A key with only ``write`` perm (no ``read``) must not read the
    decisions feed. Mirrors the contract on /v1/actions etc."""
    org, _, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    write_only_raw, _ = await generate_api_key(
        db_session, org.id, "write-only", ["write"]
    )
    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {write_only_raw}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_decisions_404_for_unknown_tenant(
    async_client, org_and_key
):
    """No Customer row → 404 (not an empty 200)."""
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/customers/never_seen/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_decisions_404_when_customer_in_other_org(
    async_client, org_and_key, db_session
):
    """A Customer that exists in a sibling org must NOT be visible —
    cross-org isolation must hold even though tenant_id is a string."""
    _, raw_key, _ = org_and_key

    other = Organization(name="other-org")
    db_session.add(other)
    await db_session.flush()
    db_session.add_all(
        [
            ChainState(org_id=other.id),
            Customer(org_id=other.id, tenant_id="secret_customer"),
        ]
    )
    await db_session.commit()

    resp = await async_client.get(
        "/v1/customers/secret_customer/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_decisions_multi_tenant_isolation(
    async_client, org_and_key, db_session
):
    """Org A's action records for tenant ``acme`` must not leak to org B
    asking for the same tenant_id. We seed actions in BOTH orgs with the
    same tenant_id; org B's key sees only its own row."""
    org_a, _, _ = org_and_key
    # Org A: 1 action for tenant=acme.
    await _make_customer(db_session, org_id=org_a.id, tenant_id="acme")
    await _seed_action(
        db_session,
        org_id=org_a.id,
        tenant_id="acme",
        sequence_number=1,
        action_name="org_a_action",
    )

    # Org B: separate customer + 2 actions for the same tenant_id.
    org_b = Organization(name="org-b")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(ChainState(org_id=org_b.id))
    await db_session.commit()
    await _make_customer(db_session, org_id=org_b.id, tenant_id="acme")
    await _seed_action(
        db_session,
        org_id=org_b.id,
        tenant_id="acme",
        sequence_number=1,
        action_name="org_b_action_1",
    )
    await _seed_action(
        db_session,
        org_id=org_b.id,
        tenant_id="acme",
        sequence_number=2,
        action_name="org_b_action_2",
    )

    raw_b, _ = await generate_api_key(
        db_session, org_b.id, "org-b-key", ["read", "write", "admin"]
    )
    # Org B should see only its own 2 rows.
    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_b}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    names = {d["action_name"] for d in body["decisions"]}
    assert names == {"org_b_action_1", "org_b_action_2"}


# ── Field projection ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ruling_built_from_approval_context(
    async_client, org_and_key, db_session
):
    """Ruling fields come straight off ``Approval.context`` — not from
    ``ActionRecord.reasoning`` (which the backend never writes for this
    purpose; writing into reasoning would break the hash chain)."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    action = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action.id,
        context={
            "gate_name": "controlled_substance_gate",
            "required_role": "dea_licensed_physician",
            "citation": "21 CFR 1306.04",
            "reason": "controlled_substance_schedule_ii",
        },
        action_summary="Reviewer must verify Schedule II prescription.",
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    [decision] = resp.json()["decisions"]
    ruling = decision["ruling"]
    assert ruling["effect"] == "require_hitl"
    assert ruling["gate_name"] == "controlled_substance_gate"
    assert ruling["required_role"] == "dea_licensed_physician"
    assert ruling["citation"] == "21 CFR 1306.04"
    assert ruling["reason"] == "controlled_substance_schedule_ii"
    assert ruling["reason_detail"] == "Reviewer must verify Schedule II prescription."


@pytest.mark.asyncio
async def test_webhook_delivery_populated_for_hitl_with_delivery(
    async_client, org_and_key, db_session
):
    """The most recent ``WebhookDelivery`` for the approval gets surfaced.
    We seed TWO deliveries to confirm the latest (by created_at) wins."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    action = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    approval = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action.id,
        context={"gate_name": "g", "required_role": "r"},
    )
    sub = await _seed_subscription(db_session, org_id=org.id)
    # Older failed delivery (will lose the bucket) — uses
    # review.requested.
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval.id,
        status="aborted",
        attempt_count=7,
        aborted_at=datetime(2026, 5, 24, 11, 0, 0),
        last_status_code=500,
        created_at=datetime(2026, 5, 24, 10, 0, 0),
        event_type="review.requested",
    )
    # Newer successful delivery — review.completed event, distinct
    # idempotency key but same approval_id prefix → the service's
    # latest-wins logic should still pick this one.
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval.id,
        status="succeeded",
        attempt_count=1,
        succeeded_at=datetime(2026, 5, 24, 12, 0, 0),
        last_status_code=200,
        created_at=datetime(2026, 5, 24, 11, 30, 0),
        event_type="review.completed",
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    [decision] = resp.json()["decisions"]
    wd = decision["webhook_delivery"]
    assert wd is not None
    assert wd["status"] == "delivered"
    assert wd["attempt_count"] == 1
    assert wd["last_status_code"] == 200


@pytest.mark.asyncio
async def test_hitl_expires_at_only_surfaced_for_pending(
    async_client, org_and_key, db_session
):
    """``expires_at`` on a pending approval shows in the response;
    a resolved (approved/rejected/expired/cancelled) approval hides it,
    even if the column is non-null."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    # Pending approval — expires_at surfaces.
    action1 = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action1.id,
        context={"gate_name": "g"},
        status="pending",
        expires_at=datetime(2026, 5, 24, 16, 0, 0),
    )
    # Approved approval — expires_at hidden.
    action2 = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=2
    )
    await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action2.id,
        context={"gate_name": "g"},
        status="approved",
        expires_at=datetime(2026, 5, 24, 16, 0, 0),
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    rows = {d["sequence_number"]: d for d in resp.json()["decisions"]}
    assert rows[1]["hitl_expires_at"] is not None
    assert rows[2]["hitl_expires_at"] is None


@pytest.mark.asyncio
async def test_allow_actions_have_null_ruling(
    async_client, org_and_key, db_session
):
    """Documented limitation: actions without an Approval row (i.e.
    ALLOW-path) surface ruling=None. Fixing this needs an out-of-PR
    follow-up (SDK denormalisation or gate_evaluations table)."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    await _seed_action(
        db_session,
        org_id=org.id,
        tenant_id="acme",
        sequence_number=1,
        result="success",
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    [decision] = resp.json()["decisions"]
    assert decision["ruling"] is None
    assert decision["webhook_delivery"] is None
    assert decision["hitl_expires_at"] is None


# ── WebhookDelivery status derivation ───────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_status_pending_with_retries_maps_to_retrying(
    async_client, org_and_key, db_session
):
    """``pending`` + attempt_count > 1 + next_retry_at set → ``retrying``.
    The UI uses ``retrying`` to render the "Retry N/7" badge with a
    countdown to the next attempt."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    action = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    approval = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action.id,
        context={"gate_name": "g"},
    )
    sub = await _seed_subscription(db_session, org_id=org.id)
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval.id,
        status="pending",
        attempt_count=3,
        next_retry_at=datetime(2026, 5, 24, 13, 0, 0),
        last_status_code=502,
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    [decision] = resp.json()["decisions"]
    wd = decision["webhook_delivery"]
    assert wd["status"] == "retrying"
    assert wd["attempt_count"] == 3
    assert wd["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_webhook_status_succeeded_maps_to_delivered(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    action = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    approval = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action.id,
        context={"gate_name": "g"},
    )
    sub = await _seed_subscription(db_session, org_id=org.id)
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval.id,
        status="succeeded",
        attempt_count=1,
        succeeded_at=datetime(2026, 5, 24, 12, 30, 0),
        last_status_code=200,
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    [decision] = resp.json()["decisions"]
    assert decision["webhook_delivery"]["status"] == "delivered"
    assert decision["webhook_delivery"]["succeeded_at"] is not None


@pytest.mark.asyncio
async def test_decisions_offset_past_end_returns_empty_page(
    async_client, org_and_key, db_session
):
    """A page request whose offset is past total returns ``decisions=[]``
    + the correct ``total`` so the UI can render "no rows in this
    slice" without re-querying."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions?limit=10&offset=50",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["decisions"] == []
    assert body["limit"] == 10
    assert body["offset"] == 50


@pytest.mark.asyncio
async def test_decisions_skip_approvals_with_null_request_record_id(
    async_client, org_and_key, db_session
):
    """Approvals whose ``request_record_id`` is NULL (e.g., created via
    POST /v1/approvals directly rather than the HITL materializer) must
    not crash the join. They're simply not surfaced — the feed shows
    only actions, and an approval without a request_record_id has no
    action to attach to."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    # Approval with NO request_record_id — must not crash the
    # request_record_id bucketing logic.
    await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=None,
        context={"gate_name": "orphan_gate"},
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    [decision] = body["decisions"]
    # No approval attaches → ruling stays None.
    assert decision["ruling"] is None


@pytest.mark.asyncio
async def test_webhook_status_aborted_maps_to_aborted(
    async_client, org_and_key, db_session
):
    """``aborted`` (retries exhausted) maps 1:1 to the UI ``aborted``
    state, which renders the red dot + "Retries exhausted" tooltip."""
    org, raw_key, _ = org_and_key
    await _make_customer(db_session, org_id=org.id, tenant_id="acme")
    action = await _seed_action(
        db_session, org_id=org.id, tenant_id="acme", sequence_number=1
    )
    approval = await _seed_approval(
        db_session,
        org_id=org.id,
        request_record_id=action.id,
        context={"gate_name": "g"},
    )
    sub = await _seed_subscription(db_session, org_id=org.id)
    await _seed_delivery(
        db_session,
        org_id=org.id,
        sub_id=sub.id,
        approval_id=approval.id,
        status="aborted",
        attempt_count=7,
        aborted_at=datetime(2026, 5, 24, 13, 0, 0),
        last_status_code=500,
    )

    resp = await async_client.get(
        "/v1/customers/acme/decisions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    [decision] = resp.json()["decisions"]
    assert decision["webhook_delivery"]["status"] == "aborted"
    assert decision["webhook_delivery"]["attempt_count"] == 7
    assert decision["webhook_delivery"]["aborted_at"] is not None
