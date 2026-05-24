"""Unit tests for ``NewDiagnosisGate`` (Gate 1).

Exercises the trigger surface (action_type, action_name regex panel,
input_data ICD-10 / diagnosis_code field), the deny patterns, and the
final ``Ruling`` shape. No DB; the gate is purely structural over the
``GateEvaluateRequest``.
"""

from __future__ import annotations

import pytest

from app.packs.base import GateContext
from app.packs.clinical.new_diagnosis import NewDiagnosisGate
from app.schemas.gate import GateEvaluateRequest, RulingEffect


GATE = NewDiagnosisGate()


def _ctx(**overrides) -> GateContext:
    defaults = dict(
        agent_name="scribemd",
        action_type="function_call",
        action_name="benign_action",
        authorized_by="dr_smith",
    )
    defaults.update(overrides)
    req = GateEvaluateRequest(**defaults)
    # ``session`` and ``org_id`` are unused by NewDiagnosisGate.
    return GateContext(session=None, org_id="org_test", request=req)  # type: ignore[arg-type]


# ── applies(): action_type triggers ──────────────────────────────────────────


def test_applies_action_type_diagnosis_create():
    assert GATE.applies(_ctx(action_type="diagnosis_create"))


def test_applies_action_type_problem_list_add():
    assert GATE.applies(_ctx(action_type="problem_list_add"))


def test_applies_action_type_condition_create():
    assert GATE.applies(_ctx(action_type="condition_create"))


def test_action_type_is_case_insensitive():
    assert GATE.applies(_ctx(action_type="DIAGNOSIS_CREATE"))


# ── applies(): action_name regex panel ───────────────────────────────────────


@pytest.mark.parametrize("name", [
    "add_diagnosis",
    "add diagnosis",
    "create new diagnosis",
    "record_diagnosis",
    "Note Diagnosis",
    "enter new_diagnosis",
    "add_to_problem_list",
    "icd10 assign",
    "icd-10 code add",
    "ICD_10_assign",
    "diagnose",
    "diagnosed",
])
def test_applies_action_name_matches_positive_patterns(name):
    assert GATE.applies(_ctx(action_name=name)), f"{name!r} should trigger"


def test_action_name_is_case_insensitive():
    assert GATE.applies(_ctx(action_name="Record Diagnosis"))


# ── applies(): deny patterns ─────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "undiagnose",
    "undiagnosed",
    "differential_diagnosis_review",
    "differential diagnosis",
    "rule_out_diagnosis",
    "rule out sepsis",
])
def test_deny_patterns_short_circuit(name):
    assert not GATE.applies(_ctx(action_name=name)), (
        f"{name!r} should NOT trigger (deny pattern)"
    )


def test_deny_pattern_overrides_diagnosis_action_type():
    """An action_type that would trigger is vetoed when action_name says
    "differential" — the action is reasoning, not a chart entry."""
    assert not GATE.applies(_ctx(
        action_type="diagnosis_create",
        action_name="differential_diagnosis_review",
    ))


# ── applies(): input_data ICD-10 trigger ─────────────────────────────────────


def test_applies_icd10_field_present_with_value():
    assert GATE.applies(_ctx(input_data={"icd10": "E11.9"}))


def test_applies_camel_case_icd10_key():
    assert GATE.applies(_ctx(input_data={"ICD-10": "E11.9"}))


def test_applies_diagnosis_code_field():
    assert GATE.applies(_ctx(input_data={"diagnosis_code": "J18.9"}))


def test_applies_primary_diagnosis_code_field():
    assert GATE.applies(_ctx(input_data={"primary_diagnosis_code": "I10"}))


def test_empty_icd_value_does_not_trigger():
    """An ICD-10 field with empty string is not a real diagnosis."""
    assert not GATE.applies(_ctx(input_data={"icd10": ""}))


def test_whitespace_only_icd_value_does_not_trigger():
    assert not GATE.applies(_ctx(input_data={"icd10": "   "}))


def test_none_icd_value_does_not_trigger():
    assert not GATE.applies(_ctx(input_data={"icd10": None}))


# ── applies(): benign actions don't trigger ──────────────────────────────────


def test_applies_returns_false_for_unrelated_action():
    assert not GATE.applies(_ctx(
        action_type="patient_lookup",
        action_name="get_patient_summary",
    ))


def test_applies_returns_false_when_input_data_keys_unrelated():
    assert not GATE.applies(_ctx(input_data={"weight_kg": 70, "bp": "120/80"}))


# ── evaluate(): ruling shape ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_returns_require_hitl_with_attending_role():
    ruling = await GATE.evaluate(_ctx(action_type="diagnosis_create"))
    assert ruling.effect is RulingEffect.REQUIRE_HITL
    assert ruling.required_role == "attending_physician"


@pytest.mark.asyncio
async def test_evaluate_cites_cms_regulation():
    ruling = await GATE.evaluate(_ctx(action_type="diagnosis_create"))
    assert ruling.citation == "42 CFR 482.24(c)(4)(viii)"


@pytest.mark.asyncio
async def test_evaluate_sets_gate_name_and_reason():
    ruling = await GATE.evaluate(_ctx(action_type="diagnosis_create"))
    assert ruling.gate_name == "new_diagnosis_requires_attending"
    assert ruling.reason == "new_diagnosis_proposed"


@pytest.mark.asyncio
async def test_evaluate_review_id_is_none():
    """The gate itself never sets review_id — the evaluator does that
    after creating the Approval row."""
    ruling = await GATE.evaluate(_ctx(action_type="diagnosis_create"))
    assert ruling.review_id is None


@pytest.mark.asyncio
async def test_evaluate_reason_detail_does_not_echo_phi():
    """The ruling text must never contain ICD codes, patient IDs, or
    other input_data fields. PHI lives in Approval.context, not in the
    public Ruling."""
    ruling = await GATE.evaluate(_ctx(
        action_type="diagnosis_create",
        data_subject_id="patient_12345",
        input_data={"icd10": "E11.9", "patient_name": "Jane Doe"},
    ))
    detail = ruling.reason_detail or ""
    assert "E11.9" not in detail
    assert "patient_12345" not in detail
    assert "Jane Doe" not in detail
