"""BAA upload endpoint tests (Phase 1 PR 13).

Covers the acceptance gate "one BAA upload completes setup":
    POST /v1/customers/{tenant_id}/baa with a pre-signed document_uri
    → creates BAAAgreement(status='active') + BAAScope(is_unrestricted=True)
    → flips customer.baa_status from 'missing' to 'active'
    → flips customer.status from 'pending_setup' to 'active'
    → invalidates services.baa cache so live-key gate sees the new BAA

Also covers the supporting endpoints added in this PR:
    GET /v1/customers/{tenant_id}/agents — AI Coverage Matrix rows
    GET /v1/customers?with_counts=1 — list with batched decision count rollup
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    BAAAgreement,
    BAAScope,
    Customer,
    CustomerAgent,
)
from app.services import baa as baa_service


async def _post_action(
    client, raw_key, *, tenant_id: str, agent_name: str = "scribe-agent"
):
    return await client.post(
        "/v1/actions",
        json={
            "action_name": "chart_entry",
            "action_type": "function_call",
            "agent_name": agent_name,
            "result": "success",
            "tenant_id": tenant_id,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )


@pytest.mark.asyncio
async def test_baa_upload_flips_customer_status(async_client, org_and_key, db_session):
    """The Phase 1 acceptance-gate scenario.

    Auto-discovery creates a pending_setup customer. Operator uploads a
    BAA with a pre-signed URI. Customer flips to active + baa_status=active
    in a single response.
    """
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Trigger auto-discovery → customer exists in pending_setup state.
    resp = await _post_action(async_client, raw_key, tenant_id="cleveland_clinic")
    assert resp.status_code == 200, resp.text

    pre = (await async_client.get("/v1/customers/cleveland_clinic", headers=headers)).json()
    assert pre["status"] == "pending_setup"
    assert pre["baa_status"] == "missing"

    upload = await async_client.post(
        "/v1/customers/cleveland_clinic/baa",
        json={
            "document_uri": "s3://baa-uploads/cc-2026.pdf",
            "effective_at": "2026-05-01T00:00:00",
            "expires_at": "2027-05-01T00:00:00",
            "is_unrestricted": True,
        },
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["customer_baa_status"] == "active"
    assert body["customer_status"] == "active"
    assert body["agreement_id"]
    assert body["scope_id"]

    # Re-fetch the customer — both status fields persisted.
    post = (await async_client.get("/v1/customers/cleveland_clinic", headers=headers)).json()
    assert post["status"] == "active"
    assert post["baa_status"] == "active"


@pytest.mark.asyncio
async def test_baa_upload_creates_agreement_and_scope_rows(
    async_client, org_and_key, db_session
):
    """Schema artifacts: BAAAgreement(status='active') + BAAScope(is_unrestricted=True)."""
    org, raw_key, _ = org_and_key
    db_session.add(Customer(org_id=org.id, tenant_id="mayo"))
    await db_session.commit()

    upload = await async_client.post(
        "/v1/customers/mayo/baa",
        json={
            "document_uri": "https://example.com/baa/mayo-2026.pdf",
            "is_unrestricted": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert upload.status_code == 201, upload.text

    # Round-trip via the ORM.
    agreements = (
        await db_session.execute(
            __import__("sqlalchemy").select(BAAAgreement).where(
                BAAAgreement.org_id == org.id
            )
        )
    ).scalars().all()
    assert len(agreements) == 1
    agreement = agreements[0]
    assert agreement.status == "active"
    assert agreement.document_uri == "https://example.com/baa/mayo-2026.pdf"

    scopes = (
        await db_session.execute(
            __import__("sqlalchemy").select(BAAScope).where(
                BAAScope.baa_agreement_id == agreement.id
            )
        )
    ).scalars().all()
    assert len(scopes) == 1
    assert scopes[0].is_unrestricted is True


@pytest.mark.asyncio
async def test_baa_upload_invalidates_freshness_cache(
    async_client, org_and_key, db_session
):
    """The PR 10 TODO in services/baa.py: invalidate the org-level cache
    after a successful upload so live-key gates see the new BAA without
    waiting for the 60 s TTL.
    """
    org, raw_key, _ = org_and_key
    db_session.add(Customer(org_id=org.id, tenant_id="stanford"))
    await db_session.commit()

    # Poison the cache with a stale "no active BAA" result.
    baa_service._BAA_FRESHNESS_CACHE[org.id] = (
        __import__("time").monotonic(),
        False,
    )

    upload = await async_client.post(
        "/v1/customers/stanford/baa",
        json={"document_uri": "s3://baa-uploads/stanford.pdf"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert upload.status_code == 201, upload.text

    # The route MUST drop the cached entry. Without the invalidation,
    # next is_org_baa_active() call would return the stale False.
    assert org.id not in baa_service._BAA_FRESHNESS_CACHE


@pytest.mark.asyncio
async def test_baa_upload_org_isolated(async_client, org_and_key, db_session):
    """A BAA upload MUST 404 when the customer belongs to another org."""
    from app.models import ChainState, Organization

    _, raw_key, _ = org_and_key
    other = Organization(name="other-org")
    db_session.add(other)
    await db_session.flush()
    db_session.add_all(
        [
            ChainState(org_id=other.id),
            Customer(org_id=other.id, tenant_id="leaked_customer"),
        ]
    )
    await db_session.commit()

    leaked = await async_client.post(
        "/v1/customers/leaked_customer/baa",
        json={"document_uri": "s3://x/y.pdf"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert leaked.status_code == 404


@pytest.mark.asyncio
async def test_baa_upload_rejects_bad_uri(async_client, org_and_key, db_session):
    org, raw_key, _ = org_and_key
    db_session.add(Customer(org_id=org.id, tenant_id="acme"))
    await db_session.commit()

    bad = await async_client.post(
        "/v1/customers/acme/baa",
        json={"document_uri": "not-a-url"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_baa_upload_rejects_inverted_temporal_range(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    db_session.add(Customer(org_id=org.id, tenant_id="acme"))
    await db_session.commit()

    bad = await async_client.post(
        "/v1/customers/acme/baa",
        json={
            "document_uri": "s3://x/y.pdf",
            "effective_at": "2027-01-01T00:00:00",
            "expires_at": "2026-01-01T00:00:00",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_list_customer_agents_returns_coverage_rows(
    async_client, org_and_key, db_session
):
    """The AI Coverage Matrix endpoint feeds Customer detail's table."""
    _, raw_key, _ = org_and_key

    # POST two actions with distinct action_class values → auto-discovery
    # creates two CustomerAgent rows for one tenant.
    await _post_action(
        async_client, raw_key, tenant_id="cleveland_clinic", agent_name="scribe-a"
    )
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "prior_auth_decision",
            "action_type": "function_call",
            "action_class": "prior_auth",
            "agent_name": "auth-agent",
            "result": "success",
            "tenant_id": "cleveland_clinic",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    for item in body["items"]:
        # Phase 1 placeholders populate as documented.
        assert item["hitl_gate_count"] == 0
        assert item["pdf_included"] is False
        assert item["posture_included"] is False
        # has_capture is True — the ActionRecord we just posted exists.
        assert item["has_capture"] is True
        assert item["coverage"] in ("covered", "partial", "none")


@pytest.mark.asyncio
async def test_list_customer_agents_404_when_missing(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/customers/never_seen/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_actions_filters_by_tenant_id(async_client, org_and_key):
    """The Customer detail page's decisions stream uses ?tenant_id=... to
    scope ActionRecord listings to a single customer."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    await _post_action(async_client, raw_key, tenant_id="alpha")
    await _post_action(async_client, raw_key, tenant_id="alpha")
    await _post_action(async_client, raw_key, tenant_id="beta")

    alpha_resp = await async_client.get(
        "/v1/actions?tenant_id=alpha", headers=headers
    )
    assert alpha_resp.status_code == 200
    body = alpha_resp.json()
    assert body["total"] == 2
    for rec in body["records"]:
        assert rec["tenant_id"] == "alpha"

    beta_resp = await async_client.get(
        "/v1/actions?tenant_id=beta", headers=headers
    )
    assert beta_resp.status_code == 200
    assert beta_resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_customers_with_counts(async_client, org_and_key, db_session):
    """``with_counts=1`` populates ``decision_count_30d`` via a batched
    COUNT(*) and avoids the per-row N+1.
    """
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Two customers, three decisions for one and one for the other.
    await _post_action(async_client, raw_key, tenant_id="alpha")
    await _post_action(async_client, raw_key, tenant_id="alpha")
    await _post_action(async_client, raw_key, tenant_id="alpha")
    await _post_action(async_client, raw_key, tenant_id="beta")

    resp = await async_client.get(
        "/v1/customers?with_counts=1", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    counts = {item["tenant_id"]: item["decision_count_30d"] for item in body["items"]}
    assert counts["alpha"] == 3
    assert counts["beta"] == 1

    # Without with_counts → still zero (cheap path).
    resp = await async_client.get("/v1/customers", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    for item in body["items"]:
        assert item["decision_count_30d"] == 0
