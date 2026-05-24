"""End-to-end ``POST /v1/gates/evaluate`` integration tests for A2.

Exercises the full evaluator: 3 gates + strictest-wins reduction +
``Approval`` row materialization on ``REQUIRE_HITL``. Uses the same
``async_client`` / ``org_and_key`` fixtures as the Wave 2A contract
tests so the auth surface is consistent.

Each test seeds whatever BAA state it needs (active / expired / none)
and posts a payload designed to trigger zero, one, or multiple gates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Approval, BAAAgreement, BAAScope, Customer
from app.services import baa as baa_service


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _reset_baa_cache():
    """Wipe the in-process BAA freshness cache around each test."""
    baa_service._reset_baa_freshness_cache_for_tests()
    yield
    baa_service._reset_baa_freshness_cache_for_tests()


async def _seed_active_baa(db_session, org_id: str) -> BAAAgreement:
    customer = Customer(org_id=org_id, tenant_id="integration_customer")
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


def _minimal_payload(**overrides):
    base = {
        "agent_name": "scribemd",
        "action_type": "function_call",
        "action_name": "benign_action",
        "authorized_by": "dr_smith",
    }
    base.update(overrides)
    return base


# ── Single-gate paths ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_benign_payload_with_active_baa_returns_allow(
    async_client, org_and_key, db_session
):
    """No gate triggers + BAA active → stale_baa returns ALLOW with reason
    'baa_current'. The reducer picks that single ruling."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effect"] == "allow"
    assert body["gate_name"] == "stale_baa_blocks_action"
    assert body["reason"] == "baa_current"
    assert body["review_id"] is None


@pytest.mark.asyncio
async def test_benign_payload_without_baa_blocks_on_stale_baa(
    async_client, org_and_key
):
    """No BAA on file → stale_baa BLOCKs, even on a totally benign action."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "block"
    assert body["reason"] == "stale_baa"
    assert body["citation"] == "45 CFR 164.502(e)"
    assert body["gate_name"] == "stale_baa_blocks_action"
    assert body["fix_url"] == "/customers"


@pytest.mark.asyncio
async def test_block_fix_url_deep_links_when_tenant_id_present(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(tenant_id="acme_health"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["fix_url"] == "/customers/acme_health"


@pytest.mark.asyncio
async def test_new_diagnosis_with_active_baa_requires_hitl(
    async_client, org_and_key, db_session
):
    """BAA active + diagnosis_create action → REQUIRE_HITL with attending role."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_type="diagnosis_create",
            action_name="add_diagnosis",
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effect"] == "require_hitl"
    assert body["gate_name"] == "new_diagnosis_requires_attending"
    assert body["required_role"] == "attending_physician"
    assert body["citation"] == "42 CFR 482.24(c)(4)(viii)"
    assert body["review_id"] is not None, "evaluator must populate review_id"


@pytest.mark.asyncio
async def test_controlled_substance_with_active_baa_requires_hitl(
    async_client, org_and_key, db_session
):
    """BAA active + OxyContin in input_data → REQUIRE_HITL, dea_authorized."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_name="write_prescription",
            input_data={"medication": "OxyContin"},
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "require_hitl"
    assert body["gate_name"] == "controlled_substance_requires_dea"
    assert body["required_role"] == "dea_authorized"
    assert body["citation"] == "21 CFR 1306.04"
    assert body["review_id"] is not None
    # Generic, not brand, in the surfaced reason_detail.
    assert "oxycodone" in body["reason_detail"]
    assert "OxyContin" not in body["reason_detail"]


# ── Multi-gate reduction paths ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diagnosis_without_baa_blocks_strictest_wins(
    async_client, org_and_key
):
    """Diagnosis + no BAA → both gates trigger; BLOCK beats REQUIRE_HITL."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_type="diagnosis_create",
            action_name="add_diagnosis",
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "block"
    assert body["gate_name"] == "stale_baa_blocks_action"
    # BLOCK wins outright; no HITL approval row should have been created.
    assert body["review_id"] is None


@pytest.mark.asyncio
async def test_controlled_substance_without_baa_blocks_strictest_wins(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_name="write_prescription",
            input_data={"medication": "morphine"},
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "block"
    assert body["gate_name"] == "stale_baa_blocks_action"


@pytest.mark.asyncio
async def test_multi_hitl_tie_break_picks_first_in_pack_order(
    async_client, org_and_key, db_session
):
    """Both diagnosis AND controlled-substance gates require HITL → tie
    broken by pack order; new_diagnosis sits before controlled_substance
    so it wins."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_type="diagnosis_create",
            action_name="add_diagnosis_and_prescribe",
            input_data={
                "icd10": "G89.4",
                "medication": "OxyContin",
            },
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "require_hitl"
    # NewDiagnosisGate is earlier in CLINICAL_SCRIBE_PACK than
    # ControlledSubstanceGate so it wins the tie.
    assert body["gate_name"] == "new_diagnosis_requires_attending"


# ── Approval-row side effect ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_hitl_creates_approval_row_with_context(
    async_client, org_and_key, db_session
):
    """REQUIRE_HITL ruling must persist an Approval row whose context
    carries the gate metadata + original input_data so a reviewer can
    decide without re-querying the agent."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_type="diagnosis_create",
            action_name="add_diagnosis",
            data_subject_id="patient_42",
            input_data={"icd10": "E11.9", "note": "starting metformin"},
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    review_id = body["review_id"]
    assert review_id is not None

    # The Approval row must exist and carry the expected metadata.
    result = await db_session.execute(
        select(Approval).where(Approval.id == review_id)
    )
    approval = result.scalar_one()
    assert approval.org_id == org.id
    assert approval.action_name == "add_diagnosis"
    assert approval.data_subject_id == "patient_42"
    assert approval.risk_tier == "high"
    assert approval.approvers_required == 1
    assert approval.status == "pending"
    # Context dict carries the gate metadata.
    assert approval.context["gate_name"] == "new_diagnosis_requires_attending"
    assert approval.context["required_role"] == "attending_physician"
    assert approval.context["citation"] == "42 CFR 482.24(c)(4)(viii)"
    assert approval.context["reason"] == "new_diagnosis_proposed"
    # Original input_data preserved for the reviewer.
    assert approval.context["original_input_data"]["icd10"] == "E11.9"


@pytest.mark.asyncio
async def test_allow_does_not_create_approval_row(
    async_client, org_and_key, db_session
):
    """ALLOW ruling must NOT touch the approvals table."""
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["effect"] == "allow"

    result = await db_session.execute(
        select(Approval).where(Approval.org_id == org.id)
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_block_does_not_create_approval_row(
    async_client, org_and_key, db_session
):
    """BLOCK ruling (no BAA) must NOT create an Approval row — there is
    no review to schedule on a refusal."""
    org, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(
            action_type="diagnosis_create",
            action_name="add_diagnosis",
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["effect"] == "block"

    result = await db_session.execute(
        select(Approval).where(Approval.org_id == org.id)
    )
    assert result.scalars().first() is None


# ── Permission + validation regressions (re-tested against real evaluator) ──


@pytest.mark.asyncio
async def test_read_only_key_is_forbidden(async_client, org_and_key, db_session):
    """Read-only keys still 403 against the real evaluator."""
    from app.services.auth import generate_api_key

    org, _, _ = org_and_key
    raw_read, _ = await generate_api_key(
        db_session, org.id, "reader", ["read"]
    )
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=_minimal_payload(),
        headers={"Authorization": f"Bearer {raw_read}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_missing_required_field_returns_422(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={"action_type": "x", "action_name": "y", "authorized_by": "z"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 422
