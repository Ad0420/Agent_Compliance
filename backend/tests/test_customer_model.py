"""Customer model tests (Phase 1 PR 1).

Verifies the SQLAlchemy model: defaults, UNIQUE/CHECK constraints,
CASCADE-on-org-delete, relationship wiring.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import Customer, Organization


@pytest.mark.asyncio
async def test_customer_defaults(db_session):
    org = Organization(name="test-org-defaults")
    db_session.add(org)
    await db_session.flush()

    customer = Customer(org_id=org.id, tenant_id="cleveland_clinic")
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    assert customer.status == "pending_setup"
    assert customer.baa_status == "missing"
    assert customer.display_name is None
    assert customer.contact_email is None
    assert customer.jurisdictions is None
    assert customer.created_at is not None
    assert customer.updated_at is not None


@pytest.mark.asyncio
async def test_customer_unique_org_tenant(db_session):
    """A duplicate (org_id, tenant_id) must raise IntegrityError."""
    org = Organization(name="test-org-unique")
    db_session.add(org)
    await db_session.flush()

    db_session.add(Customer(org_id=org.id, tenant_id="dup"))
    await db_session.commit()

    db_session.add(Customer(org_id=org.id, tenant_id="dup"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_same_tenant_different_orgs_ok(db_session):
    """The same tenant_id may exist under different orgs — tenancy is
    org-scoped, not global."""
    org1 = Organization(name="org-a")
    org2 = Organization(name="org-b")
    db_session.add_all([org1, org2])
    await db_session.flush()

    db_session.add(Customer(org_id=org1.id, tenant_id="cleveland_clinic"))
    db_session.add(Customer(org_id=org2.id, tenant_id="cleveland_clinic"))
    await db_session.commit()  # no IntegrityError


@pytest.mark.asyncio
async def test_customer_invalid_status_rejected(db_session):
    org = Organization(name="org-status")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        Customer(org_id=org.id, tenant_id="x", status="totally_bogus")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_invalid_baa_status_rejected(db_session):
    org = Organization(name="org-baa-status")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        Customer(org_id=org.id, tenant_id="x", baa_status="wrong_state")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_customer_cascade_on_org_delete(db_session):
    """Hard-deleting an organization must cascade to its customers.

    (The app uses soft-delete on Organization in practice, but the FK
    behaviour matters for ops cleanups and integration tests.)

    SQLite FK enforcement is now wired on every fresh connection via the
    ``connect`` event in conftest.py — no per-test PRAGMA needed.
    """
    org = Organization(name="org-cascade")
    db_session.add(org)
    await db_session.flush()

    db_session.add(Customer(org_id=org.id, tenant_id="c1"))
    db_session.add(Customer(org_id=org.id, tenant_id="c2"))
    await db_session.commit()

    await db_session.execute(
        text("DELETE FROM organizations WHERE id = :id"), {"id": org.id}
    )
    await db_session.commit()

    result = await db_session.execute(
        select(Customer).where(Customer.org_id == org.id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_customer_jurisdictions_json_roundtrip(db_session):
    org = Organization(name="org-jurisdictions")
    db_session.add(org)
    await db_session.flush()

    customer = Customer(
        org_id=org.id,
        tenant_id="multi_state_clinic",
        jurisdictions=["CA", "TX", "NY"],
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    assert customer.jurisdictions == ["CA", "TX", "NY"]


@pytest.mark.asyncio
async def test_customer_organization_relationship(db_session):
    """The Organization.customers back-reference must populate."""
    org = Organization(name="org-rel")
    db_session.add(org)
    await db_session.flush()

    db_session.add(Customer(org_id=org.id, tenant_id="rel_a"))
    db_session.add(Customer(org_id=org.id, tenant_id="rel_b"))
    await db_session.commit()
    org_id = org.id

    # Re-query the org with selectinload so the relationship is eagerly
    # populated (async sessions can't lazy-load on attribute access).
    result = await db_session.execute(
        select(Organization)
        .options(selectinload(Organization.customers))
        .where(Organization.id == org_id)
    )
    loaded = result.scalar_one()
    tenant_ids = {c.tenant_id for c in loaded.customers}
    assert tenant_ids == {"rel_a", "rel_b"}


@pytest.mark.asyncio
async def test_customer_baa_status_accepts_terminated(db_session):
    """Phase 1 PR 1: ``terminated`` is a valid BAA lifecycle state added
    to distinguish a rescinded BAA from one that merely expired."""
    org = Organization(name="org-baa-term")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        Customer(org_id=org.id, tenant_id="x", baa_status="terminated")
    )
    await db_session.commit()  # no IntegrityError


@pytest.mark.asyncio
async def test_customer_updated_at_bumps_on_change(db_session):
    """``onupdate=func.now()`` must bump ``updated_at`` on any column change.

    Pre-fix the column had only ``server_default``, so ``updated_at``
    froze at INSERT and silently broke change tracking. SQLite
    ``CURRENT_TIMESTAMP`` has second-level resolution; sleep > 1s so
    the bump is visible.
    """
    import asyncio

    org = Organization(name="ts-org-upd")
    db_session.add(org)
    await db_session.flush()
    c = Customer(org_id=org.id, tenant_id="t")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    first_updated = c.updated_at

    await asyncio.sleep(1.1)  # SQLite CURRENT_TIMESTAMP is second-resolution

    c.display_name = "Updated Name"
    await db_session.commit()
    await db_session.refresh(c)
    assert c.updated_at > first_updated
