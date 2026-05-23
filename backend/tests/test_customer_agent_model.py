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


async def _make_org_and_customer(db_session, name: str) -> tuple[Organization, Customer]:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    customer = Customer(org_id=org.id, tenant_id=f"{name}_tenant")
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return org, customer


@pytest.mark.asyncio
async def test_customer_agent_basic_create(db_session):
    org, customer = await _make_org_and_customer(db_session, "ca-basic")
    now = datetime.utcnow()

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
async def test_customer_agent_unique_per_customer_and_type(db_session):
    org, customer = await _make_org_and_customer(db_session, "ca-unique")
    now = datetime.utcnow()

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
async def test_customer_agent_same_type_different_customers_ok(db_session):
    """Two different customers may each have a CustomerAgent of type
    'scribe' — uniqueness is (customer_id, agent_type), not just agent_type."""
    org1, customer1 = await _make_org_and_customer(db_session, "ca-multi-1")
    org2, customer2 = await _make_org_and_customer(db_session, "ca-multi-2")
    now = datetime.utcnow()

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
async def test_customer_agent_invalid_source_rejected(db_session):
    org, customer = await _make_org_and_customer(db_session, "ca-src")
    now = datetime.utcnow()

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
async def test_customer_agent_invalid_confidence_rejected(db_session):
    org, customer = await _make_org_and_customer(db_session, "ca-conf")
    now = datetime.utcnow()

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
async def test_customer_agent_invalid_status_rejected(db_session):
    org, customer = await _make_org_and_customer(db_session, "ca-stat")
    now = datetime.utcnow()

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
async def test_customer_agent_set_null_on_agent_delete(db_session):
    """Codex E1: deleting the Agent row must NULL the agent_id FK but
    keep the CustomerAgent row intact (historical coverage preserved)."""
    org, customer = await _make_org_and_customer(db_session, "ca-agentdel")
    agent = Agent(org_id=org.id, name="scribe-agent-1")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    now = datetime.utcnow()
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

    await db_session.execute(text("PRAGMA foreign_keys = ON"))
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
async def test_customer_agent_cascade_on_customer_delete(db_session):
    """Deleting the Customer cascades to CustomerAgent rows."""
    org, customer = await _make_org_and_customer(db_session, "ca-custdel")
    now = datetime.utcnow()

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

    await db_session.execute(text("PRAGMA foreign_keys = ON"))
    await db_session.execute(
        text("DELETE FROM customers WHERE id = :id"), {"id": customer.id}
    )
    await db_session.commit()

    result = await db_session.execute(
        select(CustomerAgent).where(CustomerAgent.customer_id == customer.id)
    )
    assert result.scalars().all() == []
