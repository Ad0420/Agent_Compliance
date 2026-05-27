"""Contract + schema tests for ``POST /v1/gates/evaluate``.

Wave 2A landed the wire shape with a stub evaluator (always ALLOW).
Wave 2B PR A2 replaces the stub with ``CLINICAL_SCRIBE_PACK`` — so
the tests in this module now exercise the contract *around* the real
evaluator without seeding any clinical conditions:

* Auth + permission gating (401, 403)
* Validation (422 on missing fields, malformed tenant_id, empty body)
* Schema round-trip
* Effect enum values
* Per-field size caps mirrored from ``ActionRecord``

Behavioural tests for the three gates and their reduction live in
``test_gates_evaluate_integration.py`` and the per-gate unit modules.
This module deliberately does NOT seed BAAs / diagnoses / controlled
substances — that's the integration suite's job."""

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


def test_gate_evaluate_request_rejects_oversized_input_data():
    """input_data above the 1 MB cap is rejected (mirrors ActionRecord)."""
    # 1.5 MB of ASCII — comfortably over the 1 MB cap once JSON-encoded.
    oversized = {"blob": "x" * 1_500_000}
    with pytest.raises(ValidationError) as exc:
        GateEvaluateRequest(
            agent_name="scribemd",
            action_type="function_call",
            action_name="record_diagnosis",
            authorized_by="dr_smith",
            input_data=oversized,
        )
    assert "input_data" in str(exc.value)


def test_gate_evaluate_request_rejects_oversized_metadata():
    """metadata above the 1 MB cap is rejected (mirrors ActionRecord)."""
    oversized = {"blob": "x" * 1_500_000}
    with pytest.raises(ValidationError) as exc:
        GateEvaluateRequest(
            agent_name="scribemd",
            action_type="function_call",
            action_name="record_diagnosis",
            authorized_by="dr_smith",
            metadata=oversized,
        )
    assert "metadata" in str(exc.value)


# ── API-level tests ─────────────────────────────────────────────────────────
#
# Behavioural coverage of the three gates (stale_baa, new_diagnosis,
# controlled_substance) and their strictest-wins reduction lives in
# ``test_gates_evaluate_integration.py``. This module keeps the
# auth / validation surface tested in isolation.


@pytest.mark.asyncio
async def test_evaluate_without_auth_header_is_unauthorized(async_client):
    """Missing Authorization header → 401 from ``HTTPBearer401``."""
    response = await async_client.post(
        "/v1/gates/evaluate",
        json={
            "agent_name": "scribemd",
            "action_type": "function_call",
            "action_name": "record_diagnosis",
            "authorized_by": "dr_smith",
        },
    )
    # ``HTTPBearer401`` (services.auth) overrides FastAPI's default 403 on
    # missing Authorization with the semantically correct 401.
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


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
