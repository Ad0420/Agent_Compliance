"""Customer + CustomerAgent auto-discovery tests (Phase 1 PR 2 B2).

Covers the v1-test-plan.md rows:
  * Auto-discover happy path
  * Auto-discover idempotency
  * Auto-discover transactional
  * CustomerAgent agent_type historical stamping
  * Cross-org tenant_id collision logged
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from app.models import (
    Agent,
    Customer,
    CustomerAgent,
    Organization,
    ChainState,
)


HEADERS = lambda raw: {"Authorization": f"Bearer {raw}"}


async def _post(client, raw, *, tenant_id, action_class=None, agent_name="scribe-agent"):
    payload = {
        "action_name": "chart_entry",
        "action_type": "function_call",
        "agent_name": agent_name,
        "result": "success",
        "tenant_id": tenant_id,
    }
    if action_class is not None:
        payload["action_class"] = action_class
    return await client.post("/v1/actions", json=payload, headers=HEADERS(raw))


@pytest.mark.asyncio
async def test_auto_discover_happy_path(async_client, org_and_key, db_session):
    """First SDK call with a new tenant_id creates the Customer row,
    creates the CustomerAgent row, and stamps agent_type from
    action_class."""
    org, raw_key, _ = org_and_key

    resp = await _post(
        async_client, raw_key, tenant_id="cleveland_clinic",
        action_class="chart_entry",
    )
    assert resp.status_code == 200, resp.text

    customer = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "cleveland_clinic")
        )
    ).scalar_one()
    assert customer.org_id == org.id
    assert customer.status == "pending_setup"
    assert customer.baa_status == "missing"
    assert customer.display_name == "cleveland_clinic"
    assert customer.first_seen_at is not None
    assert customer.last_seen_at is not None

    ca = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalar_one()
    assert ca.source == "auto_discovered"
    assert ca.confidence == "high"
    assert ca.status == "active"
    # action_class flowed through into the historical agent_type stamp.
    assert ca.agent_type == "chart_entry"
    assert ca.agent_id is not None


@pytest.mark.asyncio
async def test_auto_discover_unclassified_when_no_action_class(
    async_client, org_and_key, db_session
):
    """Per X4: unknown action classes land as ``unclassified`` rather
    than silently creating new coverage categories."""
    _, raw_key, _ = org_and_key
    resp = await _post(async_client, raw_key, tenant_id="acme_health")
    assert resp.status_code == 200

    ca = (
        await db_session.execute(
            select(CustomerAgent).join(Customer).where(
                Customer.tenant_id == "acme_health"
            )
        )
    ).scalar_one()
    assert ca.agent_type == "unclassified"


@pytest.mark.asyncio
async def test_auto_discover_idempotent_customer_and_customer_agent(
    async_client, org_and_key, db_session
):
    """Second action with same (tenant_id, action_class) must not
    duplicate Customer/CustomerAgent — both rows just advance
    last_seen_at."""
    _, raw_key, _ = org_and_key

    first = await _post(
        async_client, raw_key, tenant_id="cleveland_clinic",
        action_class="chart_entry",
    )
    assert first.status_code == 200
    customer_before = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "cleveland_clinic")
        )
    ).scalar_one()
    last_seen_before = customer_before.last_seen_at
    ca_before = (
        await db_session.execute(
            select(CustomerAgent).where(
                CustomerAgent.customer_id == customer_before.id
            )
        )
    ).scalar_one()
    ca_last_seen_before = ca_before.last_seen_at

    second = await _post(
        async_client, raw_key, tenant_id="cleveland_clinic",
        action_class="chart_entry",
    )
    assert second.status_code == 200

    # Exactly one Customer row.
    customers = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "cleveland_clinic")
        )
    ).scalars().all()
    assert len(customers) == 1

    # Exactly one CustomerAgent row.
    cas = (
        await db_session.execute(
            select(CustomerAgent).where(
                CustomerAgent.customer_id == customers[0].id
            )
        )
    ).scalars().all()
    assert len(cas) == 1

    # last_seen_at advanced (or stayed equal — same-clock case).
    await db_session.refresh(customers[0])
    await db_session.refresh(cas[0])
    assert customers[0].last_seen_at >= last_seen_before
    assert cas[0].last_seen_at >= ca_last_seen_before


@pytest.mark.asyncio
async def test_auto_discover_different_action_class_creates_second_customer_agent(
    async_client, org_and_key, db_session
):
    """The unique constraint is (customer_id, agent_type), so a second
    action with a DIFFERENT action_class under the same tenant must
    create a second CustomerAgent row — that's the AI Coverage Matrix
    surfacing a new agent_type."""
    _, raw_key, _ = org_and_key

    await _post(async_client, raw_key, tenant_id="acme", action_class="chart_entry")
    await _post(async_client, raw_key, tenant_id="acme", action_class="prior_auth")

    customer = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "acme")
        )
    ).scalar_one()
    cas = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalars().all()
    assert {c.agent_type for c in cas} == {"chart_entry", "prior_auth"}


@pytest.mark.asyncio
async def test_customer_agent_historical_stamp_not_rewritten(
    async_client, org_and_key, db_session
):
    """Codex E1: if a CustomerAgent already exists, subsequent actions
    must NEVER rewrite agent_id or agent_type. Only last_seen_at moves."""
    org, raw_key, _ = org_and_key

    await _post(
        async_client, raw_key, tenant_id="cleveland_clinic",
        action_class="chart_entry", agent_name="scribe-v1",
    )

    customer = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "cleveland_clinic")
        )
    ).scalar_one()
    ca_original = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalar_one()
    original_agent_id = ca_original.agent_id
    original_agent_type = ca_original.agent_type

    # Same action_class but a different agent_name → a new Agent row is
    # created. The CustomerAgent stamp is on (customer_id, agent_type)
    # so the second action's agent_id must NOT replace the original.
    await _post(
        async_client, raw_key, tenant_id="cleveland_clinic",
        action_class="chart_entry", agent_name="scribe-v2",
    )

    cas = (
        await db_session.execute(
            select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
        )
    ).scalars().all()
    assert len(cas) == 1
    await db_session.refresh(cas[0])
    assert cas[0].agent_id == original_agent_id
    assert cas[0].agent_type == original_agent_type


@pytest.mark.asyncio
async def test_auto_discover_transactional_rollback(
    org_and_key, db_session, monkeypatch
):
    """If the ActionRecord insert path errors after auto-discovery, the
    Customer / CustomerAgent rows MUST roll back too — no orphan
    placeholder rows.

    Drives the service layer directly (no HTTP) and monkeypatches
    ``session.commit`` to raise on the FIRST call — that's the chain
    write inside ``build_and_insert_record``. Because every model
    insert in that function is on the same session, the failure must
    drop Customer + CustomerAgent along with the ActionRecord.
    """
    from app.schemas.action import ActionRecordCreate
    from app.services.chain import build_and_insert_record

    org, _, _ = org_and_key

    original_commit = db_session.commit
    call_count = {"n": 0}

    async def fake_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated chain commit failure")
        return await original_commit()

    monkeypatch.setattr(db_session, "commit", fake_commit)

    payload = ActionRecordCreate(
        action_name="x",
        agent_name="scribe-agent",
        result="success",
        tenant_id="rollback_tenant",
        action_class="chart_entry",
    )

    with pytest.raises(RuntimeError):
        await build_and_insert_record(db_session, org.id, payload)

    # Roll back the failed transaction so subsequent queries on this
    # session see a clean state — the production code path's caller
    # (FastAPI's request dependency) handles this automatically via the
    # session context manager.
    await db_session.rollback()

    leftover = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "rollback_tenant")
        )
    ).scalar_one_or_none()
    assert leftover is None, (
        "Customer row survived a rolled-back ActionRecord insert — "
        "auto-discovery is leaking placeholder rows."
    )


@pytest.mark.asyncio
async def test_cross_org_tenant_id_collision_logs_warning(
    async_client, org_and_key, db_session, caplog
):
    """Two orgs auto-discovering the same tenant_id must produce two
    separate Customer rows (org isolation), and the second creation
    must log a warning. The webhook event is deferred to PR 3."""
    org_a, raw_key_a, _ = org_and_key

    # Org B with its own API key.
    from app.models import APIKey
    from app.services.auth import generate_api_key

    org_b = Organization(name="other-org-collision")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(ChainState(org_id=org_b.id))
    await db_session.commit()
    raw_key_b, _ = await generate_api_key(
        db_session, org_b.id, "b-key", ["read", "write", "admin"]
    )

    # Org A discovers `abridge`.
    first = await _post(async_client, raw_key_a, tenant_id="abridge")
    assert first.status_code == 200

    caplog.set_level(logging.WARNING, logger="app.services.chain")

    # Org B fires action with same tenant_id.
    second = await _post(async_client, raw_key_b, tenant_id="abridge")
    assert second.status_code == 200

    # Two separate Customer rows.
    customers = (
        await db_session.execute(
            select(Customer).where(Customer.tenant_id == "abridge")
        )
    ).scalars().all()
    assert len(customers) == 2
    assert {c.org_id for c in customers} == {org_a.id, org_b.id}

    # Warning was logged.
    collision_logs = [
        r for r in caplog.records
        if "cross-org tenant_id collision" in r.getMessage()
    ]
    assert collision_logs, (
        "Expected a cross-org collision warning but saw none. Logs: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_auto_discover_customer_integrity_error_preserves_action_record(
    org_and_key, db_session, monkeypatch
):
    """Regression test for PR #195 review — silent ActionRecord loss.

    Before the fix, the Customer IntegrityError handler called
    ``session.rollback()``, which blew away the entire outer transaction
    (chain_state SELECT FOR UPDATE row, Agent row, AND the freshly-added
    ActionRecord). Execution continued, the chain advanced, and the
    final commit landed ONLY the chain-state advance + touched
    Customer's last_seen_at — the ActionRecord was silently lost.

    After the fix (begin_nested SAVEPOINT), the IntegrityError rolls
    back ONLY the failed Customer insert; the outer transaction
    (including the ActionRecord) is preserved.

    We simulate the race by inserting the colliding Customer row before
    calling build_and_insert_record. The auto-discovery's INSERT then
    hits a unique-violation on (org_id, tenant_id), the SAVEPOINT rolls
    back, the handler re-reads the existing row, and the ActionRecord
    still commits.
    """
    from sqlalchemy import select as _select
    from app.models import ActionRecord
    from app.schemas.action import ActionRecordCreate
    from app.services.chain import build_and_insert_record

    org, _, _ = org_and_key

    # Pre-insert the Customer that will collide with auto-discovery.
    pre_existing = Customer(
        org_id=org.id,
        tenant_id="collision_tenant",
        display_name="operator_set_name",  # operator already renamed it
        status="active",
        baa_status="active",
    )
    db_session.add(pre_existing)
    await db_session.commit()

    # The trick: force the auto-discovery to BELIEVE no Customer exists,
    # then collide at flush time. We monkeypatch the initial SELECT inside
    # _auto_discover_customer_and_agent to return None on first call.
    import app.services.chain as chain_mod

    original_execute = db_session.execute
    call_state = {"customer_select_seen": False}

    async def patched_execute(stmt, *args, **kwargs):
        # Detect the SELECT Customer WHERE org_id=? AND tenant_id=? at
        # the top of _auto_discover_customer_and_agent and lie about it
        # ONCE — the IntegrityError handler's re-read SELECT must still
        # see the real row.
        try:
            stmt_str = str(stmt)
        except Exception:
            stmt_str = ""
        if (
            not call_state["customer_select_seen"]
            and "FROM customers" in stmt_str
            and "tenant_id" in stmt_str
            and "org_id" in stmt_str
        ):
            call_state["customer_select_seen"] = True

            class _EmptyResult:
                def scalar_one_or_none(self):
                    return None

                def scalar_one(self):  # pragma: no cover
                    raise AssertionError("unreachable")

                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                    return _S()

            return _EmptyResult()
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", patched_execute)

    payload = ActionRecordCreate(
        action_name="x",
        agent_name="scribe-agent",
        result="success",
        tenant_id="collision_tenant",
        action_class="chart_entry",
    )

    record = await build_and_insert_record(db_session, org.id, payload)
    assert record is not None
    assert record.tenant_id == "collision_tenant"

    # Lift the patch — verify the ActionRecord actually landed.
    monkeypatch.setattr(db_session, "execute", original_execute)

    stored = (
        await db_session.execute(
            _select(ActionRecord).where(ActionRecord.id == record.id)
        )
    ).scalar_one_or_none()
    assert stored is not None, (
        "ActionRecord was silently lost when Customer IntegrityError "
        "handler ran — begin_nested() SAVEPOINT regression."
    )
    assert stored.tenant_id == "collision_tenant"

    # The pre-existing Customer's display_name must NOT have been
    # rewritten — auto-discovery only touches last_seen_at on existing rows.
    existing = (
        await db_session.execute(
            _select(Customer).where(Customer.tenant_id == "collision_tenant")
        )
    ).scalar_one()
    assert existing.display_name == "operator_set_name"


@pytest.mark.asyncio
async def test_no_tenant_id_no_auto_discovery(
    async_client, org_and_key, db_session
):
    """A POST without tenant_id must NOT create a Customer or
    CustomerAgent row (backward-compat for SDK pilots that haven't
    upgraded yet)."""
    _, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "ping",
            "action_type": "function_call",
            "agent_name": "no-tenant-agent",
            "result": "success",
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200

    customers = (
        await db_session.execute(select(Customer))
    ).scalars().all()
    assert customers == []
    cas = (
        await db_session.execute(select(CustomerAgent))
    ).scalars().all()
    assert cas == []
