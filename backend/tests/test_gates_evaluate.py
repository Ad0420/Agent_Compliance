"""Tests for the Phase 2 Wave 2A Ruling contract + POST /v1/gates/evaluate.

Wave 2A scope is the *contract* — the stub evaluator returns ALLOW for
every input. Real gate logic (ClinicalScribePack) ships in Wave 2B
PR A2 and gets its own test module. Tests here cover:

API:
1. 200 minimal payload → ALLOW + reason='no_gates_registered'
2. 200 full payload (tenant_id + input_data) → still ALLOW (stub doesn't
   differentiate)
3. 401 no auth header
4. 403 read-only key → write permission required
5. 422 missing required field (agent_name)
6. 422 invalid tenant_id shape (must match ActionRecord regex)
7. 200 response omits review_id/fix_url/required_role/citation/gate_name

Schema:
8. Ruling round-trips through model_dump → model_validate without losing
   optional None fields
9. RulingEffect accepts the three legal strings and rejects others
10. GateEvaluateRequest defaults input_data and metadata to empty dicts
"""

import pytest
from pydantic import ValidationError

from app.schemas.gate import GateEvaluateRequest, Ruling, RulingEffect
from app.services.auth import generate_api_key


# ── Schema-level tests ──────────────────────────────────────────────────────


def test_ruling_round_trip_preserves_optional_none_fields():
    """Ruling(effect=ALLOW, reason=...) round-trips with optional fields = None."""
    original = Ruling(
        effect=RulingEffect.ALLOW,
        reason="no_gates_registered",
    )
    dumped = original.model_dump()
    revived = Ruling.model_validate(dumped)

    assert revived.effect is RulingEffect.ALLOW
    assert revived.reason == "no_gates_registered"
    # All optional fields are explicitly None — not dropped.
    assert revived.reason_detail is None
    assert revived.citation is None
    assert revived.review_id is None
    assert revived.fix_url is None
    assert revived.required_role is None
    assert revived.gate_name is None


def test_ruling_effect_accepts_legal_strings_and_rejects_others():
    """RulingEffect accepts 'allow' / 'require_hitl' / 'block'; rejects others."""
    assert RulingEffect("allow") is RulingEffect.ALLOW
    assert RulingEffect("require_hitl") is RulingEffect.REQUIRE_HITL
    assert RulingEffect("block") is RulingEffect.BLOCK

    with pytest.raises(ValueError):
        RulingEffect("permit")  # not a legal effect


def test_gate_evaluate_request_defaults_collections():
    """input_data and metadata default to empty dicts when omitted."""
    req = GateEvaluateRequest(
        agent_name="scribemd",
        action_type="function_call",
        action_name="record_diagnosis",
        authorized_by="dr_smith",
    )
    assert req.input_data == {}
    assert req.metadata == {}
    assert req.tenant_id is None
    assert req.data_subject_id is None


# ── API-level tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_minimal_payload_returns_allow(async_client, org_and_key):
    """POST /v1/gates/evaluate with minimal valid payload returns stub ALLOW."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "authorized_by": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effect"] == "allow"
    assert body["reason"] == "no_gates_registered"
    # Stub never populates the routing fields.
    assert body["review_id"] is None
    assert body["fix_url"] is None
    assert body["required_role"] is None
    assert body["citation"] is None
    assert body["gate_name"] is None


@pytest.mark.asyncio
async def test_evaluate_full_payload_still_returns_allow(async_client, org_and_key):
    """tenant_id + populated input_data does not change the stub ruling."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "agent_id": "agent_abc",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "action_description": "Record new diagnosis for visit",
            "tenant_id": "cleveland_clinic",
            "data_subject_id": "patient_42",
            "target_system": "ehr",
            "target_resource": "patients/42/encounters/9",
            "authorized_by": "dr_smith",
            "input_data": {"icd10": "E11.9", "controlled_substance": True},
            "metadata": {"source": "scribe-ui"},
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    body = response.json()
    # The stub is deliberately indifferent to payload contents in Wave 2A.
    assert body["effect"] == "allow"
    assert body["reason"] == "no_gates_registered"


@pytest.mark.asyncio
async def test_evaluate_without_auth_header_is_unauthorized(async_client):
    """Missing Authorization header → 401/403 from HTTPBearer."""
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "authorized_by": "dr_smith",
        },
    )
    # FastAPI's HTTPBearer returns 403 when no credentials are provided;
    # other auth dependencies return 401. Either is "unauthenticated".
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_evaluate_with_read_only_key_is_forbidden(
    async_client, org_and_key, db_session
):
    """A key without 'write' permission is rejected with 403."""
    org, _, _ = org_and_key
    raw_read, _ = await generate_api_key(
        db_session, org.id, "reader-key", ["read"]
    )
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "authorized_by": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_read}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_evaluate_missing_required_field_is_validation_error(
    async_client, org_and_key
):
    """Omitting required agent_name returns 422 validation error."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            # agent_name omitted
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "authorized_by": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 422
    detail = response.json().get("detail")
    assert detail, "Validation error should include a detail list"
    # Pydantic surfaces the missing field name in the error location.
    assert any("agent_name" in str(item) for item in detail)


@pytest.mark.asyncio
async def test_evaluate_invalid_tenant_id_returns_422(async_client, org_and_key):
    """tenant_id with disallowed characters is rejected (mirrors ActionRecord)."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "tenant_id": "John Doe DOB 1972",  # whitespace + PHI-shaped
            "authorized_by": "dr_smith",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # tenant_id must mirror ActionRecord's regex so a value that would
    # be rejected by POST /v1/actions is also rejected by the gate
    # boundary — keeps both layers in lock-step.
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_evaluate_empty_body_is_validation_error(
    async_client, org_and_key
):
    """Empty JSON body → 422 (multiple required fields missing)."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 422
