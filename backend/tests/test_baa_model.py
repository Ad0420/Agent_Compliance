"""BAAAgreement + BAAScope model tests (Phase 1 PR 1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import BAAAgreement, BAAScope, Customer, Organization


def _now() -> datetime:
    """Return tz-naive UTC ``datetime`` consistent with how the app writes
    ``DateTime`` columns. Replaces deprecated ``datetime.utcnow()``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_baa_agreement_default_status_draft(db_session, make_org_and_customer):
    org, cust = await make_org_and_customer("baa-defaults")

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
async def test_baa_agreement_invalid_status_rejected(db_session, make_org_and_customer):
    org, cust = await make_org_and_customer("baa-bad-status")

    db_session.add(
        BAAAgreement(org_id=org.id, customer_id=cust.id, status="unsigned")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_baa_scope_json_roundtrip(db_session, make_org_and_customer):
    """Codex E2: covered_services + covered_agent_types must round-trip
    as JSON arrays cleanly so Phase 2 gate checks can read them."""
    org, cust = await make_org_and_customer("baa-scope-json")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    scope = BAAScope(
        baa_agreement_id=baa.id,
        covered_services=["chart_entry", "scheduling"],
        covered_agent_types=["scribe", "receptionist"],
        granted_at=_now(),
    )
    db_session.add(scope)
    await db_session.commit()
    await db_session.refresh(scope)

    assert scope.covered_services == ["chart_entry", "scheduling"]
    assert scope.covered_agent_types == ["scribe", "receptionist"]


@pytest.mark.asyncio
async def test_baa_scope_cascade_on_agreement_delete(db_session, make_org_and_customer):
    """Deleting a BAAAgreement must cascade to its scopes."""
    org, cust = await make_org_and_customer("baa-cascade-scope")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    now = _now()
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
async def test_baa_agreement_cascade_on_customer_delete(db_session, make_org_and_customer):
    """Deleting a Customer must cascade to BAAAgreements (and via that
    cascade, to BAAScopes)."""
    org, cust = await make_org_and_customer("baa-cust-cascade")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="draft")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["s"],
            covered_agent_types=["a"],
            granted_at=_now(),
        )
    )
    await db_session.commit()
    cust_id = cust.id

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


@pytest.mark.asyncio
async def test_baa_agreement_rejects_inverted_dates(db_session, make_org_and_customer):
    """The ``ck_baa_temporal_order`` CHECK constraint rejects ``effective_at
    > expires_at`` when both are populated. Guards against ops-typo BAAs."""
    org, cust = await make_org_and_customer("baa-inverted")
    db_session.add(
        BAAAgreement(
            org_id=org.id,
            customer_id=cust.id,
            effective_at=datetime(2030, 1, 1),
            expires_at=datetime(2025, 1, 1),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_baa_scope_granted_at_defaults_to_now_when_omitted(
    db_session, make_org_and_customer
):
    """Regression: production ``baa_scopes`` inserts were failing with
    ``null value in column "granted_at" violates not-null constraint``
    whenever the row was built without supplying ``granted_at``.

    The model column should now carry ``server_default=func.now()`` (matching
    the sibling ``created_at``), so a BAAScope constructed without
    ``granted_at`` persists with a DB-supplied timestamp instead of crashing
    the transaction.

    Payload shape matches the failing row from the prod logs (narrow scope,
    ``is_unrestricted=False``)."""
    org, cust = await make_org_and_customer("baa-granted-at-default")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)

    before = _now()
    scope = BAAScope(
        baa_agreement_id=baa.id,
        covered_services=["chart_entry", "triage", "prescribe"],
        covered_agent_types=["scribe", "triage", "prior_auth"],
        is_unrestricted=False,
        # NOTE: granted_at deliberately omitted — that's the prod failure
        # mode this regression test covers.
    )
    db_session.add(scope)
    await db_session.commit()
    await db_session.refresh(scope)

    assert scope.granted_at is not None
    # The DB default should be applied at insert time, so the value lands
    # at-or-after `before` (allowing for slight clock skew).
    assert scope.granted_at >= before.replace(microsecond=0)


@pytest.mark.asyncio
async def test_baa_scope_is_unrestricted_default_false(db_session, make_org_and_customer):
    """New BAAScope rows default to is_unrestricted=False (the strict
    enumerated semantics). Legacy backfill to True lands in PR 4/5."""
    org, cust = await make_org_and_customer("baa-unr")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="active")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)
    s = BAAScope(
        baa_agreement_id=baa.id,
        covered_services=["x"],
        covered_agent_types=["y"],
        granted_at=_now(),
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    assert s.is_unrestricted is False


@pytest.mark.asyncio
async def test_baa_agreement_updated_at_bumps_on_change(
    db_session, make_org_and_customer
):
    """``onupdate=func.now()`` must bump ``updated_at`` on any column change.

    SQLite ``CURRENT_TIMESTAMP`` has second-level resolution; sleep > 1s
    so the bump is observable in the assertion.
    """
    import asyncio

    org, cust = await make_org_and_customer("baa-upd")
    baa = BAAAgreement(org_id=org.id, customer_id=cust.id, status="draft")
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)
    first_updated = baa.updated_at

    await asyncio.sleep(1.1)  # SQLite CURRENT_TIMESTAMP is second-resolution

    baa.status = "active"
    await db_session.commit()
    await db_session.refresh(baa)
    assert baa.updated_at > first_updated
