"""Tests for the dev-only org-provisioning endpoint (W1.6).

Closes Phase 2 finding ``v1-register-removed-no-local-replacement``.

Coverage:
  - 201 in dev: org + chain state + admin key created, raw key returned ONCE
  - 201 in dev with ``with_baa=True``: Customer + BAA + Scope also created
  - 404 in production: endpoint hidden, no DB writes
  - 422 on blank name (covers both empty and pure-whitespace)
  - 409 on duplicate name (relies on ``uq_organizations_name`` constraint)
  - Round-trip: minted raw key actually authenticates against /v1/organizations/me
  - ``GET /v1/dev/orgs?name=X`` returns the created org; 404 in production
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings as global_settings
from app.main import app
from app.models import (
    APIKey,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from app.routes.dev import get_settings


@pytest_asyncio.fixture
async def dev_env():
    """Force ``ENVIRONMENT=development`` for the duration of the test.

    The dev router reads settings via the ``get_settings`` dependency,
    which the production binary resolves from the module-level
    ``settings`` singleton. We override the dependency rather than
    mutating the singleton so other tests in the suite that DO depend
    on the real settings value aren't perturbed.
    """

    class _DevSettings:
        environment = "development"
        # Other settings the route never touches — supply just the
        # attribute the dependency cares about.

    app.dependency_overrides[get_settings] = lambda: _DevSettings()
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest_asyncio.fixture
async def prod_env():
    """Force ``ENVIRONMENT=production`` to test the 404-hiding path."""

    class _ProdSettings:
        environment = "production"

    app.dependency_overrides[get_settings] = lambda: _ProdSettings()
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_create_dev_org_returns_201_with_raw_key(
    async_client, db_session, dev_env
):
    resp = await async_client.post(
        "/v1/dev/orgs",
        json={"name": "Acme Local Dev"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Acme Local Dev"
    assert body["org_id"]
    assert body["api_key"].startswith("al_test_"), body["api_key"]
    assert body["api_key_prefix"] == body["api_key"][:12]
    assert body["has_baa"] is False

    # Org, ChainState, and an admin APIKey now exist in the DB.
    org = (
        await db_session.execute(
            select(Organization).where(Organization.id == body["org_id"])
        )
    ).scalar_one()
    assert org.name == "Acme Local Dev"

    chain = (
        await db_session.execute(
            select(ChainState).where(ChainState.org_id == org.id)
        )
    ).scalar_one()
    assert chain.latest_hash == "GENESIS"

    keys = (
        await db_session.execute(
            select(APIKey).where(APIKey.org_id == org.id)
        )
    ).scalars().all()
    assert len(keys) == 1
    assert "admin" in keys[0].permissions
    assert "write" in keys[0].permissions
    assert "read" in keys[0].permissions
    # No BAA seeded when with_baa=False
    baa_count = (
        await db_session.execute(
            select(BAAAgreement).where(BAAAgreement.org_id == org.id)
        )
    ).scalars().all()
    assert baa_count == []


@pytest.mark.asyncio
async def test_create_dev_org_with_baa_seeds_customer_baa_scope(
    async_client, db_session, dev_env
):
    resp = await async_client.post(
        "/v1/dev/orgs",
        json={"name": "BAA Org", "with_baa": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["has_baa"] is True

    org_id = body["org_id"]

    # Placeholder Customer created
    customers = (
        await db_session.execute(
            select(Customer).where(Customer.org_id == org_id)
        )
    ).scalars().all()
    assert len(customers) == 1
    assert customers[0].status == "active"
    assert customers[0].baa_status == "active"

    # Active BAA created
    baas = (
        await db_session.execute(
            select(BAAAgreement).where(BAAAgreement.org_id == org_id)
        )
    ).scalars().all()
    assert len(baas) == 1
    assert baas[0].status == "active"

    # Wildcard scope created
    scopes = (
        await db_session.execute(
            select(BAAScope).where(BAAScope.baa_agreement_id == baas[0].id)
        )
    ).scalars().all()
    assert len(scopes) == 1
    assert scopes[0].is_unrestricted is True


@pytest.mark.asyncio
async def test_create_dev_org_returns_404_in_production(
    async_client, db_session, prod_env
):
    """Production builds must NOT expose this endpoint at all.

    A 404 is intentional (vs. 403): we don't even confirm the path
    exists. Probing attacker sees the same response they'd get for
    ``/v1/does-not-exist``.
    """
    resp = await async_client.post(
        "/v1/dev/orgs", json={"name": "should not create"}
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Not Found"

    # No side effects — no org was created.
    orgs = (
        await db_session.execute(
            select(Organization).where(Organization.name == "should not create")
        )
    ).scalars().all()
    assert orgs == []


@pytest.mark.asyncio
async def test_create_dev_org_rejects_blank_name(async_client, dev_env):
    # Empty string — caught by Pydantic min_length=1
    resp = await async_client.post("/v1/dev/orgs", json={"name": ""})
    assert resp.status_code == 422

    # Pure whitespace — passes pydantic but our handler strips + rejects
    resp = await async_client.post("/v1/dev/orgs", json={"name": "   "})
    assert resp.status_code == 422

    # Too long — caught by Pydantic max_length=255
    resp = await async_client.post("/v1/dev/orgs", json={"name": "x" * 256})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dev_org_duplicate_name_returns_409(
    async_client, dev_env
):
    """Relies on the ``uq_organizations_name`` constraint (W1.6).

    First create succeeds; second create with same name returns 409
    with a structured ``org_name_taken`` envelope.
    """
    first = await async_client.post(
        "/v1/dev/orgs", json={"name": "Duplicate Org"}
    )
    assert first.status_code == 201

    second = await async_client.post(
        "/v1/dev/orgs", json={"name": "Duplicate Org"}
    )
    assert second.status_code == 409
    body = second.json()
    # Flat-envelope handler in main.py lifts dict detail to top level.
    assert body["code"] == "org_name_taken"
    assert "Duplicate Org" in body["detail"]


@pytest.mark.asyncio
async def test_minted_key_authenticates_round_trip(
    async_client, dev_env
):
    """The raw key returned by /v1/dev/orgs should authenticate immediately.

    Round-trips through ``GET /v1/organizations/me``, which requires a
    valid API key with ``read`` permission. This catches regressions
    where the route returns the wrong tier prefix, the wrong hash, or
    forgets to commit the key.
    """
    resp = await async_client.post(
        "/v1/dev/orgs", json={"name": "Round Trip Org"}
    )
    assert resp.status_code == 201
    raw_key = resp.json()["api_key"]
    org_id = resp.json()["org_id"]

    me = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["id"] == org_id
    assert me.json()["name"] == "Round Trip Org"


@pytest.mark.asyncio
async def test_list_dev_orgs_filters_by_name(async_client, dev_env):
    """``GET /v1/dev/orgs?name=X`` returns matching orgs only.

    Used by bootstrap_orgs.py to detect a slug that already has an
    org provisioned before attempting a create.
    """
    await async_client.post("/v1/dev/orgs", json={"name": "Alpha"})
    await async_client.post("/v1/dev/orgs", json={"name": "Beta"})

    # Filter by name
    resp = await async_client.get("/v1/dev/orgs?name=Alpha")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["orgs"]) == 1
    assert body["orgs"][0]["name"] == "Alpha"

    # Unknown name → empty list (not 404)
    resp = await async_client.get("/v1/dev/orgs?name=DoesNotExist")
    assert resp.status_code == 200
    assert resp.json()["orgs"] == []


@pytest.mark.asyncio
async def test_list_dev_orgs_returns_404_in_production(
    async_client, prod_env
):
    """Same 404-hiding rule as the POST endpoint."""
    resp = await async_client.get("/v1/dev/orgs")
    assert resp.status_code == 404
