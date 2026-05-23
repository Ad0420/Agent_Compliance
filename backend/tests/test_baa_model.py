"""BAAAgreement + BAAScope model tests (Phase 1 PR 1)."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import BAAAgreement, BAAScope, Customer, Organization


async def _make_customer(db_session, name: str) -> tuple[Organization, Customer]:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    cust = Customer(org_id=org.id, tenant_id=f"{name}_t")
    db_session.add(cust)
    await db_session.commit()
    await db_session.refresh(cust)
    return org, cust


@pytest.mark.asyncio
async def test_baa_agreement_default_status_draft(db_session):
    org, cust = await _make_customer(db_session, "baa-defaults")

    baa = BAAAgreement(org_id=org.id, customer_id=cust.id)
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    assert baa.status == "draft"
    assert baa.document_uri is None
    assert baa.effective_at is None
    assert baa.expires_at is None
    assert baa.signed_at is None


@pytest.mark.asyncio
async def test_baa_agreement_invalid_status_rejected(db_session):
    org, cust = await _make_customer(db_session, "baa-bad-status")

    db_session.add(
        BAAAgreement(org_id=org.id, customer_id=cust.id, status="unsigned")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_baa_scope_json_roundtrip(db_session):
    """Codex E2: covered_services + covered_agent_types must round-trip
    as JSON arrays cleanly so Phase 2 gate checks can read them."""
    org, cust = await _make_customer(db_session, "baa-scope-json")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    scope = BAAScope(
        baa_agreement_id=baa.id,
        covered_services=["chart_entry", "scheduling"],
        covered_agent_types=["scribe", "receptionist"],
        granted_at=datetime.utcnow(),
    )
    db_session.add(scope)
    await db_session.commit()
    await db_session.refresh(scope)

    assert scope.covered_services == ["chart_entry", "scheduling"]
    assert scope.covered_agent_types == ["scribe", "receptionist"]


@pytest.mark.asyncio
async def test_baa_scope_cascade_on_agreement_delete(db_session):
    """Deleting a BAAAgreement must cascade to its scopes."""
    org, cust = await _make_customer(db_session, "baa-cascade-scope")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    now = datetime.utcnow()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["x"],
            covered_agent_types=["y"],
            granted_at=now,
        )
    )
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["a"],
            covered_agent_types=["b"],
            granted_at=now,
        )
    )
    await db_session.commit()
    baa_id = baa.id

    await db_session.execute(text("PRAGMA foreign_keys = ON"))
    await db_session.execute(
        text("DELETE FROM baa_agreements WHERE id = :id"), {"id": baa_id}
    )
    await db_session.commit()
    db_session.expire_all()

    result = await db_session.execute(
        select(BAAScope).where(BAAScope.baa_agreement_id == baa_id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_baa_agreement_cascade_on_customer_delete(db_session):
    """Deleting a Customer must cascade to BAAAgreements (and via that
    cascade, to BAAScopes)."""
    org, cust = await _make_customer(db_session, "baa-cust-cascade")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="draft")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["s"],
            covered_agent_types=["a"],
            granted_at=datetime.utcnow(),
        )
    )
    await db_session.commit()
    cust_id = cust.id

    await db_session.execute(text("PRAGMA foreign_keys = ON"))
    await db_session.execute(
        text("DELETE FROM customers WHERE id = :id"), {"id": cust_id}
    )
    await db_session.commit()
    db_session.expire_all()

    bagm = await db_session.execute(
        select(BAAAgreement).where(BAAAgreement.customer_id == cust_id)
    )
    assert bagm.scalars().all() == []
    scopes = await db_session.execute(select(BAAScope))
    assert scopes.scalars().all() == []
