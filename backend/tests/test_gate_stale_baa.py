"""Unit tests for ``StaleBaaGate`` (Gate 3) — DB-bound.

Exercises the BAA-freshness paths via ``services.baa.is_org_baa_active``
with real DB fixtures. Helpers mirror the seeding pattern in
``test_baa_gate.py`` so the BAA shape is identical to the live-key
gate's expectations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import BAAAgreement, BAAScope, ChainState, Customer, Organization
from app.packs.base import GateContext
from app.packs.clinical.stale_baa import StaleBaaGate
from app.schemas.gate import GateEvaluateRequest, RulingEffect
from app.services import baa as baa_service


GATE = StaleBaaGate()


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ctx(session, org_id: str, **overrides) -> GateContext:
    defaults = dict(
        agent_name="scribemd",
        action_type="function_call",
        action_name="any_action",
        authorized_by="dr_smith",
    )
    defaults.update(overrides)
    req = GateEvaluateRequest(**defaults)
    return GateContext(session=session, org_id=org_id, request=req)


@pytest.fixture(autouse=True)
def _reset_baa_cache():
    """Wipe the per-process BAA freshness cache around every test so
    state from the previous test can't bleed into the assertions."""
    baa_service._reset_baa_freshness_cache_for_tests()
    yield
    baa_service._reset_baa_freshness_cache_for_tests()


async def _make_org(db_session) -> Organization:
    org = Organization(name="stale-baa-test-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _seed_active_baa(db_session, org_id: str) -> BAAAgreement:
    customer = Customer(org_id=org_id, tenant_id="ci_customer")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now,
        )
    )
    await db_session.commit()
    await db_session.refresh(baa)
    return baa


async def _seed_baa_without_scope(db_session, org_id: str) -> BAAAgreement:
    customer = Customer(org_id=org_id, tenant_id="ci_no_scope")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
    )
    db_session.add(baa)
    await db_session.commit()
    await db_session.refresh(baa)
    return baa


async def _seed_expired_baa(db_session, org_id: str) -> BAAAgreement:
    customer = Customer(org_id=org_id, tenant_id="ci_expired")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=1),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now - timedelta(days=400),
        )
    )
    await db_session.commit()
    await db_session.refresh(baa)
    return baa


# ── applies(): always True ──────────────────────────────────────────────────


def test_applies_returns_true_regardless_of_action():
    # Pure structural check — applies() is action-agnostic.
    req = GateEvaluateRequest(
        agent_name="x",
        action_type="anything",
        action_name="anything",
        authorized_by="x",
    )
    ctx = GateContext(session=None, org_id="org", request=req)  # type: ignore[arg-type]
    assert GATE.applies(ctx)


# ── evaluate(): BAA states ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_baa_blocks_with_citation(db_session):
    org = await _make_org(db_session)
    ruling = await GATE.evaluate(_ctx(db_session, org.id))
    assert ruling.effect is RulingEffect.BLOCK
    assert ruling.reason == "stale_baa"
    assert ruling.citation == "45 CFR 164.502(e)"
    assert ruling.gate_name == "stale_baa_blocks_action"
    assert ruling.fix_url == "/customers"


@pytest.mark.asyncio
async def test_active_baa_allows(db_session):
    org = await _make_org(db_session)
    await _seed_active_baa(db_session, org.id)
    ruling = await GATE.evaluate(_ctx(db_session, org.id))
    assert ruling.effect is RulingEffect.ALLOW
    assert ruling.reason == "baa_current"
    assert ruling.gate_name == "stale_baa_blocks_action"


@pytest.mark.asyncio
async def test_baa_without_scope_blocks(db_session):
    """Active BAA with zero BAAScope rows is functionally unenforceable;
    ``is_org_baa_active`` returns False, so the gate BLOCKs."""
    org = await _make_org(db_session)
    await _seed_baa_without_scope(db_session, org.id)
    ruling = await GATE.evaluate(_ctx(db_session, org.id))
    assert ruling.effect is RulingEffect.BLOCK


@pytest.mark.asyncio
async def test_expired_baa_blocks(db_session):
    org = await _make_org(db_session)
    await _seed_expired_baa(db_session, org.id)
    ruling = await GATE.evaluate(_ctx(db_session, org.id))
    assert ruling.effect is RulingEffect.BLOCK


# ── fix_url deep-linking ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fix_url_deep_links_to_tenant_when_present(db_session):
    org = await _make_org(db_session)
    ruling = await GATE.evaluate(_ctx(
        db_session, org.id, tenant_id="acme_health"
    ))
    assert ruling.effect is RulingEffect.BLOCK
    assert ruling.fix_url == "/customers/acme_health"


@pytest.mark.asyncio
async def test_fix_url_falls_back_to_list_when_no_tenant(db_session):
    org = await _make_org(db_session)
    ruling = await GATE.evaluate(_ctx(db_session, org.id))
    assert ruling.fix_url == "/customers"
