"""POST /v1/actions tenant_id validation tests (Phase 1 PR 2 B4).

v1-test-plan.md Phase 1: ``tenant_id="John Doe DOB 1972"`` → 422
(the regex rejects whitespace and slashes); ``tenant_id="cleveland_clinic"``
→ 200.

Phase 1 PR 5 (Stream C item C3) changed the behaviour of the PHI-shape
heuristic from "always reject" (the PR #195 bridge guard) to a
kind-aware split: live keys reject 422, test keys warn + event. The
PHI-shape rejection tests below now exercise a LIVE-key fixture so the
original assertion (PHI shape → 422) still holds. Test-key warning
behaviour is exercised in ``test_actions_phi_heuristic.py``.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.models import (
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from app.services import auth as auth_service
from app.services import baa as baa_service


HEADERS = lambda raw: {"Authorization": f"Bearer {raw}"}


@pytest_asyncio.fixture
async def org_and_live_key(db_session):
    """Org + active BAA + a live API key.

    The live-key BAA gate (Phase 1 PR 4 / C2) blocks every request on a
    live key unless an active+scoped BAA exists for the org. The PHI
    rejection tests below need to bypass that gate so the only failure
    surface left is the PHI heuristic — so we seed an active BAA here.
    """
    from datetime import datetime, timedelta, timezone

    baa_service._reset_baa_freshness_cache_for_tests()

    org = Organization(name="phi-live-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    customer = Customer(org_id=org.id, tenant_id="baa_holder")
    db_session.add(customer)
    await db_session.flush()
    baa = BAAAgreement(
        org_id=org.id,
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
    await db_session.refresh(org)

    raw_key, api_key = await auth_service.generate_api_key(
        db_session, org.id, "phi-live-bearer", ["read", "write"], kind="live"
    )
    yield org, raw_key, api_key
    baa_service._reset_baa_freshness_cache_for_tests()


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
@pytest.mark.parametrize(
    "phi_tenant_id",
    [
        # YYYYMMDD inside an underscored identifier.
        "john_doe_19720314",
        "patient_20001231",
        # MMDDYYYY inside an underscored identifier.
        "jane_03141972",
        # Date with separator: 1972-03-14 / 1972_03_14.
        "patient_1972-03-14",
        "patient_1972_03_14",
        # MM-DD-YYYY with separators.
        "patient_03-14-1972",
        "patient_03_14_1972",
        # SSN with separators (the base regex permits underscores).
        "ssn_123_45_6789",
        # 9 consecutive digits (sanity — base regex would accept this
        # purely-digit form since regex is [A-Za-z0-9_-]{1,64}).
        "id123456789",
    ],
)
async def test_post_action_rejects_phi_shaped_tenant_id(
    async_client, org_and_live_key, phi_tenant_id
):
    """Regression for PR #195's bridge guard families.

    Phase 1 PR 5 replaced the bridge guard with a kind-aware production
    heuristic: live keys still 422-reject for the same family of PHI
    shapes the bridge owned (this is the bridge-guard regression check
    from the PR 5 brief). Test keys now WARN + emit ``phi_shape_warning``
    instead — exercised in ``test_actions_phi_heuristic.py``.

    The structured error code (``phi_shape_in_tenant_id``) is unchanged
    so SDK error mapping (PR #194) keeps working with no SDK-side
    edits."""
    _, raw_key, _ = org_and_live_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": phi_tenant_id,
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # The structured error code must travel — SDK + dashboard error handling
    # depends on it. The flat-envelope handler (backend/app/main.py) lifts
    # dict-typed HTTPException.detail to the top level so ``code`` is at the
    # body root (was nested under ``detail`` before PR #201's review fixes).
    assert body.get("code") == "phi_shape_in_tenant_id", body
    # The PHI value itself must NEVER appear in the error body — that's
    # exactly the data the heuristic was trying to keep out of log sinks.
    import json as _json

    rendered = _json.dumps(body)
    assert phi_tenant_id not in rendered, (
        f"PHI value leaked into error body: {body!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ssn_tenant_id",
    [
        "123-45-6789",  # base regex also rejects (the - is allowed,
                        # but the full shape should match SSN_SEPARATED
                        # before regex applies). Confirms either path
                        # produces 422.
    ],
)
async def test_post_action_rejects_ssn_separator_tenant_id(
    async_client, org_and_live_key, ssn_tenant_id
):
    """Sanity check: SSN-with-separator passes the base regex (digits +
    hyphens) but the live-key PHI heuristic catches it."""
    _, raw_key, _ = org_and_live_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": ssn_tenant_id,
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "safe_tenant_id",
    [
        # Control: corporate-shaped opaque IDs.
        "acme_corp_us_east_2",
        "cleveland_clinic",
        # Control: 4-digit year alone is NOT 8-digit YYYYMMDD.
        "customer_2024",
        # Control: shorter digit run.
        "tenant_42",
        # Control: 8 digits but NOT a plausible date (month=99).
        "rev_99999999",
    ],
)
async def test_post_action_accepts_opaque_tenant_id(
    async_client, org_and_key, safe_tenant_id
):
    """Controls: the bridge guard must NOT reject legitimate opaque
    identifiers. Lean toward false-positive is the brief — but only on
    actual PHI shapes, not on every digit-containing string."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": safe_tenant_id,
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == safe_tenant_id


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
