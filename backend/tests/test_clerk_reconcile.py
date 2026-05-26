"""Unit tests for the membership-reconcile service.

Covers the four cases reconcile must distinguish:

  1. ``CLERK_SECRET_KEY`` unset                → no-op, returns None
  2. Clerk REST says "not a member"            → returns None
  3. Clerk REST says "is a member" + org row missing
                                                → creates Org + ChainState +
                                                  OrgMembership, returns row
  4. Clerk REST says "is a member" + org row exists
                                                → creates OrgMembership only,
                                                  returns row
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.models import ChainState, Organization, OrgMembership
from app.services import clerk_reconcile


_USER = "user_advik"
_ORG = "org_prod_demo"


@pytest.fixture(autouse=True)
def _enable_clerk_secret(monkeypatch):
    """Reconcile bails fast when CLERK_SECRET_KEY is empty. The tests that
    want that path explicitly clear the setting; the rest use a fake."""
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")


@pytest_asyncio.fixture
async def existing_org(db_session):
    org = Organization(name="Prod_Demo", clerk_org_id=_ORG)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


# ── case 1: CLERK_SECRET_KEY unset → no-op ───────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_noop_without_secret_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "")

    result = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert result is None
    # No rows should have been written.
    rows = (
        await db_session.execute(
            select(OrgMembership).where(OrgMembership.clerk_user_id == _USER)
        )
    ).scalars().all()
    assert rows == []


# ── case 2: Clerk REST says "not a member" → returns None ────────────────────


@pytest.mark.asyncio
async def test_reconcile_returns_none_when_clerk_says_not_a_member(
    db_session, monkeypatch, existing_org
):
    async def _not_member(*, clerk_user_id, clerk_org_id):
        return None  # Clerk: 404 or empty memberships list

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _not_member
    )

    result = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert result is None
    rows = (
        await db_session.execute(
            select(OrgMembership).where(OrgMembership.clerk_user_id == _USER)
        )
    ).scalars().all()
    assert rows == []


# ── case 3: Clerk says member, Org row missing → create both ─────────────────


@pytest.mark.asyncio
async def test_reconcile_creates_org_and_membership_when_both_missing(
    db_session, monkeypatch
):
    async def _is_admin(*, clerk_user_id, clerk_org_id):
        return "org:admin"

    async def _org_name(clerk_org_id):
        return "Prod_Demo"

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _is_admin
    )
    monkeypatch.setattr(clerk_reconcile, "_fetch_org_name", _org_name)

    result = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert result is not None
    assert result.role == "admin"
    assert result.clerk_user_id == _USER
    assert result.clerk_org_id == _ORG

    # Organization row materialized.
    org = (
        await db_session.execute(
            select(Organization).where(Organization.clerk_org_id == _ORG)
        )
    ).scalar_one()
    assert org.name == "Prod_Demo"
    assert org.id == result.org_id

    # ChainState row materialized.
    chain = (
        await db_session.execute(
            select(ChainState).where(ChainState.org_id == org.id)
        )
    ).scalar_one_or_none()
    assert chain is not None


# ── case 4: Clerk says member, Org row exists → membership only ──────────────


@pytest.mark.asyncio
async def test_reconcile_creates_only_membership_when_org_exists(
    db_session, monkeypatch, existing_org
):
    async def _is_developer(*, clerk_user_id, clerk_org_id):
        return "org:member"

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _is_developer
    )

    # Should NOT call _fetch_org_name because the org row already exists.
    # If it does, the test fails loudly.
    async def _explode(_):
        raise AssertionError("Org-name fetch must not run when org row exists")

    monkeypatch.setattr(clerk_reconcile, "_fetch_org_name", _explode)

    result = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert result is not None
    assert result.role == "developer"
    assert result.org_id == existing_org.id

    # Org row count unchanged (no duplicate).
    orgs = (
        await db_session.execute(
            select(Organization).where(Organization.clerk_org_id == _ORG)
        )
    ).scalars().all()
    assert len(orgs) == 1


# ── idempotency: second call is a no-op upsert ───────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_is_idempotent_on_repeat_call(
    db_session, monkeypatch, existing_org
):
    async def _is_admin(*, clerk_user_id, clerk_org_id):
        return "org:admin"

    monkeypatch.setattr(
        clerk_reconcile, "_fetch_user_role_in_org", _is_admin
    )

    first = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    second = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert first.id == second.id
    rows = (
        await db_session.execute(
            select(OrgMembership).where(OrgMembership.clerk_user_id == _USER)
        )
    ).scalars().all()
    assert len(rows) == 1


# ── Clerk REST transport failure → fail closed ───────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_returns_none_on_clerk_transport_error(
    db_session, monkeypatch, existing_org
):
    import httpx

    async def _boom(*, clerk_user_id, clerk_org_id):
        raise httpx.ConnectTimeout("simulated")

    monkeypatch.setattr(clerk_reconcile, "_fetch_user_role_in_org", _boom)

    result = await clerk_reconcile.reconcile_membership_from_clerk(
        db_session, clerk_user_id=_USER, clerk_org_id=_ORG
    )
    assert result is None
