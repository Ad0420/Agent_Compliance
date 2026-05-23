"""CustomerAgent model tests (Phase 1 PR 1).

Particular focus on Codex E1: ``agent_type`` is the HISTORICAL stamp.
Changing Agent metadata later (or even deleting the Agent row) must NOT
rewrite past compliance coverage — so the agent_id FK is SET NULL and
the row survives Agent deletion.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Agent, Customer, CustomerAgent, Organization


def _now() -> datetime:
    """Tz-naive UTC ``datetime`` matching how the app writes ``DateTime`` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_customer_agent_basic_create(db_session, make_org_and_customer):
    org, customer = await make_org_and_customer("ca-basic")
    now = _now()

    ca = CustomerAgent(
        customer_id=customer.id,
        agent_type="scribe",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(ca)
    await db_session.commit()
    await db_session.refresh(ca)

    assert ca.agent_type == "scribe"
    assert ca.source == "auto_discovered"
    assert ca.confidence == "high"
    assert ca.status == "active"
    assert ca.agent_id is None  # auto-discovery may stamp before Agent exists


@pytest.mark.asyncio
async def test_customer_agent_unique_per_customer_and_type(db_session, make_org_and_customer):
    org, customer = await make_org_and_customer("ca-unique")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    await db_session.commit()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_agent_same_type_different_customers_ok(db_session, make_org_and_customer):
    """Two different customers may each have a CustomerAgent of type
    'scribe' — uniqueness is (customer_id, agent_type), not just agent_type."""
    org1, customer1 = await make_org_and_customer("ca-multi-1")
    org2, customer2 = await make_org_and_customer("ca-multi-2")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer1.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.add(
        CustomerAgent(
            customer_id=customer2.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    await db_session.commit()  # no IntegrityError


@pytest.mark.asyncio
async def test_customer_agent_invalid_source_rejected(db_session, make_org_and_customer):
    org, customer = await make_org_and_customer("ca-src")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
            source="psychic_reveal",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_agent_invalid_confidence_rejected(db_session, make_org_and_customer):
    org, customer = await make_org_and_customer("ca-conf")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
            confidence="extremely_certain",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_agent_invalid_status_rejected(db_session, make_org_and_customer):
    org, customer = await make_org_and_customer("ca-stat")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
            status="ghosted",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_agent_set_null_on_agent_delete(db_session, make_org_and_customer):
    """Codex E1: deleting the Agent row must NULL the agent_id FK but
    keep the CustomerAgent row intact (historical coverage preserved)."""
    org, customer = await make_org_and_customer("ca-agentdel")
    agent = Agent(org_id=org.id, name="scribe-agent-1")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    now = _now()
    ca = CustomerAgent(
        customer_id=customer.id,
        agent_id=agent.id,
        agent_type="scribe",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(ca)
    await db_session.commit()
    ca_id = ca.id

    await db_session.execute(
        text("DELETE FROM agents WHERE id = :id"), {"id": agent.id}
    )
    await db_session.commit()
    # Drop cached ORM state so the next SELECT actually hits the DB —
    # otherwise we re-read the pre-delete agent_id from the session cache.
    db_session.expire_all()

    # Row survives, agent_id is NULL.
    result = await db_session.execute(
        select(CustomerAgent).where(CustomerAgent.id == ca_id)
    )
    survivor = result.scalar_one()
    assert survivor.agent_id is None
    assert survivor.agent_type == "scribe"  # historical stamp preserved


@pytest.mark.asyncio
async def test_customer_agent_cascade_on_customer_delete(db_session, make_org_and_customer):
    """Deleting the Customer cascades to CustomerAgent rows."""
    org, customer = await make_org_and_customer("ca-custdel")
    now = _now()

    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="scribe",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="receptionist",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    await db_session.commit()

    await db_session.execute(
        text("DELETE FROM customers WHERE id = :id"), {"id": customer.id}
    )
    await db_session.commit()

    result = await db_session.execute(
        select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_customer_agent_type_normalized(db_session, make_org_and_customer):
    """The ``@validates('agent_type')`` hook lowercases + strips. Without
    it, ``'scribe'``, ``'Scribe'``, and ``'scribe '`` would all bypass
    the unique constraint and create three rows for the same logical type.
    """
    org, customer = await make_org_and_customer("ca-norm")
    now = _now()
    ca = CustomerAgent(
        customer_id=customer.id,
        agent_type="  Scribe  ",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(ca)
    await db_session.commit()
    await db_session.refresh(ca)
    assert ca.agent_type == "scribe"

    # Second insert with the same logical type but different casing must
    # now hit the unique constraint.
    db_session.add(
        CustomerAgent(
            customer_id=customer.id,
            agent_type="SCRIBE",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
