"""POST /v1/actions tenant_id validation tests (Phase 1 PR 2 B4).

v1-test-plan.md Phase 1: ``tenant_id="John Doe DOB 1972"`` → 422
(the regex rejects whitespace and slashes); ``tenant_id="cleveland_clinic"``
→ 200.
"""
from __future__ import annotations

import pytest


HEADERS = lambda raw: {"Authorization": f"Bearer {raw}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_tenant_id",
    [
        "John Doe DOB 1972",  # spaces + digits → 422
        "foo/bar",            # slash
        "foo.bar",            # dot
        "foo bar",            # space
        "a" * 65,             # too long
        "résumé",             # non-ASCII
        "foo;bar",            # semicolon
    ],
)
async def test_post_action_rejects_malformed_tenant_id(
    async_client, org_and_key, bad_tenant_id
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": bad_tenant_id,
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail")
    # FastAPI returns a list of validation errors — flatten + check.
    flat = str(detail)
    assert "tenant_id" in flat


@pytest.mark.asyncio
async def test_post_action_accepts_valid_tenant_id(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": "cleveland_clinic",
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == "cleveland_clinic"


@pytest.mark.asyncio
async def test_post_action_omitting_tenant_id_still_works(async_client, org_and_key):
    """Backward-compat: existing SDK pilots that don't send tenant_id
    must keep working — the field is optional."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] is None


@pytest.mark.asyncio
async def test_post_action_promoted_columns_stored_in_db(
    async_client, org_and_key, db_session
):
    """Regression for PR #191's ship-blocker: tenant_id / domain /
    action_class must actually be persisted to the indexed columns,
    not silently dropped."""
    from sqlalchemy import select
    from app.models import ActionRecord

    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "chart_entry",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": "cleveland_clinic",
            "domain": "clinical",
            "action_class": "chart_entry",
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.id == resp.json()["id"]
            )
        )
    ).scalar_one()
    assert row.tenant_id == "cleveland_clinic"
    assert row.domain == "clinical"
    assert row.action_class == "chart_entry"


@pytest.mark.asyncio
async def test_hash_changes_when_promoted_fields_set(async_client, org_and_key):
    """Two records that differ only in tenant_id/domain/action_class
    must produce different hashes — proves the fields participate in
    the chain.

    Inverse to the legacy frozen-digest test: a record with ALL three
    fields NULL still hashes identically to the pre-Phase-1 baseline
    (covered by test_hash_regression.test_legacy_record_hash_matches_frozen_digest)."""
    _, raw_key, _ = org_and_key

    bare = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "ping",
            "agent_name": "scribe",
            "result": "success",
        },
        headers=HEADERS(raw_key),
    )
    populated = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "ping",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": "abridge",
            "domain": "clinical",
            "action_class": "chart_entry",
        },
        headers=HEADERS(raw_key),
    )
    assert bare.status_code == 200
    assert populated.status_code == 200
    assert bare.json()["record_hash"] != populated.json()["record_hash"]
