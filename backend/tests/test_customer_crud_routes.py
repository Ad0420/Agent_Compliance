"""Customer CRUD endpoint tests (Phase 1 PR 2, Stream B item B1).

Covers the smoke flow from v1-test-plan.md Phase 1:
    POST action with tenant_id → GET /v1/customers shows 1 row;
    GET /v1/customers/{tenant_id} returns it;
    PATCH display_name persists;
    LIST with ?status=pending_setup includes it;
    LIST with ?status=active excludes it.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Customer


async def _post_action(client, raw_key, *, tenant_id: str | None = "cleveland_clinic"):
    payload = {
        "action_name": "chart_entry",
        "action_type": "function_call",
        "agent_name": "scribe-agent",
        "result": "success",
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return await client.post(
        "/v1/actions",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )


@pytest.mark.asyncio
async def test_customer_crud_smoke(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # POST an action with tenant_id → triggers auto-discovery.
    resp = await _post_action(async_client, raw_key)
    assert resp.status_code == 200, resp.text

    # GET /v1/customers — exactly one row visible.
    list_resp = await async_client.get("/v1/customers", headers=headers)
    assert list_resp.status_code == 200, list_resp.text
    body = list_resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["tenant_id"] == "cleveland_clinic"
    assert item["status"] == "pending_setup"
    assert item["baa_status"] == "missing"
    assert item["display_name"] == "cleveland_clinic"
    assert item["decision_count_30d"] == 0
    assert item["first_seen_at"] is not None
    assert item["last_seen_at"] is not None

    # GET single by tenant_id.
    single = await async_client.get(
        "/v1/customers/cleveland_clinic", headers=headers
    )
    assert single.status_code == 200
    assert single.json()["tenant_id"] == "cleveland_clinic"

    # PATCH display_name persists.
    patched = await async_client.patch(
        "/v1/customers/cleveland_clinic",
        json={"display_name": "Cleveland Clinic", "contact_email": "ops@cc.org"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Cleveland Clinic"
    assert patched.json()["contact_email"] == "ops@cc.org"

    # LIST with ?status=pending_setup includes it.
    pending = await async_client.get(
        "/v1/customers?status=pending_setup", headers=headers
    )
    assert pending.status_code == 200
    assert pending.json()["total"] == 1

    # LIST with ?status=active excludes it.
    active = await async_client.get(
        "/v1/customers?status=active", headers=headers
    )
    assert active.status_code == 200
    assert active.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_customer_404_when_missing(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/customers/never_seen",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_customer_404_when_missing(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/customers/never_seen",
        json={"display_name": "X"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_customer_rejects_status_mutations(
    async_client, org_and_key, db_session
):
    """PR 2 explicitly refuses status / baa_status edits — those land in
    PR 3 (lifecycle) and PR 10 (BAA upload). A silent ignore would let
    operators sidestep the BAA workflow's audit trail."""
    org, raw_key, _ = org_and_key
    db_session.add(
        Customer(org_id=org.id, tenant_id="acme", display_name="acme")
    )
    await db_session.commit()

    resp = await async_client.patch(
        "/v1/customers/acme",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    assert "status" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_customer_validates_email_shape(async_client, org_and_key, db_session):
    org, raw_key, _ = org_and_key
    db_session.add(
        Customer(org_id=org.id, tenant_id="acme", display_name="acme")
    )
    await db_session.commit()

    bad = await async_client.patch(
        "/v1/customers/acme",
        json={"contact_email": "not-an-email"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_list_customers_pagination_and_baa_filter(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Seed three customers — vary baa_status.
    db_session.add_all(
        [
            Customer(org_id=org.id, tenant_id="a", baa_status="missing"),
            Customer(org_id=org.id, tenant_id="b", baa_status="active"),
            Customer(org_id=org.id, tenant_id="c", baa_status="active"),
        ]
    )
    await db_session.commit()

    resp = await async_client.get(
        "/v1/customers?baa_status=active&limit=10", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {it["tenant_id"] for it in body["items"]} == {"b", "c"}

    # Paged: limit=1 returns 1 item, total=3.
    resp = await async_client.get(
        "/v1/customers?limit=1&offset=0", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_customers_org_isolated(
    async_client, org_and_key, db_session
):
    """A Customer in another org must never be visible — both list and
    single-fetch are filtered by org_id."""
    from app.models import ChainState, Organization

    org, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

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

    listed = await async_client.get("/v1/customers", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 0

    single = await async_client.get(
        "/v1/customers/secret_customer", headers=headers
    )
    assert single.status_code == 404
