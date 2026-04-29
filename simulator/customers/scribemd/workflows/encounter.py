"""End-to-end encounter pipeline for ScribeMD.

Implements the canonical Use Case 1 flow from `use_cases.md`:

    1. Scribe drafts SOAP note (note_drafter agent)
    2. Orders extractor pulls diagnoses + meds (orders_extractor agent)
    3. If new diagnosis or new med order → Vera request_approval (HITL)
    4. A "physician" approves / rejects / modifies via the dashboard or SDK
    5. On approve → record `chart_commit` action → done
       On reject → record `chart_blocked` action → done

The `physician_callback` lets the demo (Mode A) auto-approve after a
narrated pause and lets the test suite (Mode B) drive a deterministic
decision. In production, a real human approves via the Vera dashboard or
an `/v1/approvals/{id}/decide` API call from the EHR's UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from vera import ApprovalRejectedError, VeraClient

from simulator.customers.scribemd.agents.note_drafter import NoteDrafterAgent
from simulator.customers.scribemd.agents.orders_extractor import OrdersExtractorAgent
from simulator.customers.scribemd.fixtures.encounters import Encounter


# Risk tiers per use_cases.md — high-risk diagnoses always trigger HITL.
RED_FLAG_TERMS = {
    "myocardial infarction",
    "mi",
    "nstemi",
    "stemi",
    "stroke",
    "sepsis",
    "pulmonary embolism",
    "pe",
    "anaphylaxis",
    "pancreatitis",
    "appendicitis",
    "dka",
    "diabetic ketoacidosis",
    "meningitis",
    "cardiac arrest",
    "unstable angina",
}


@dataclass
class EncounterResult:
    encounter_id: str
    note: str
    diagnoses: list[str]
    medication_orders: list[str]
    lab_or_imaging_orders: list[str]
    risk_tier: str
    approval_id: Optional[str]
    approval_status: str  # "approved" | "rejected" | "auto_committed" | "expired"
    chart_committed: bool
    record_ids: list[str]


# A physician callback decides on a pending approval. Returns
# (decision, approver, note) where decision is "approve" | "reject".
PhysicianCallback = Callable[[dict], tuple[str, str, Optional[str]]]


def _classify_risk(diagnoses: list[str], chief_complaint: str) -> str:
    blob = " ".join(diagnoses + [chief_complaint]).lower()
    for term in RED_FLAG_TERMS:
        if term in blob:
            return "critical" if term in {"mi", "stroke", "sepsis", "pe", "stemi", "anaphylaxis", "cardiac arrest"} else "high"
    if diagnoses:
        return "medium"
    return "low"


def _decide_approval_via_api(
    vera: VeraClient,
    approval_id: str,
    decision: str,
    approver: str,
    note: Optional[str] = None,
) -> dict:
    """Decide an approval via Vera's REST API.

    The SDK doesn't yet expose a `decide_approval` helper, so we hit the
    endpoint directly using the client's underlying httpx client.
    """
    payload = {"decision": decision, "approver": approver, "note": note}
    resp = vera._client.post(f"/v1/approvals/{approval_id}/decide", json=payload)
    resp.raise_for_status()
    return resp.json()


def run_encounter(
    *,
    encounter: Encounter,
    drafter: NoteDrafterAgent,
    extractor: OrdersExtractorAgent,
    chart_vera: VeraClient,
    physician_callback: PhysicianCallback,
    approval_timeout_seconds: int = 300,
    on_step: Optional[Callable[[str, dict], None]] = None,
) -> EncounterResult:
    """Run a single encounter end-to-end.

    Each agent owns its own Vera client (and therefore its own `agent_name`
    on the audit chain). `chart_vera` is the client used for the
    request_approval call, the chart_commit, and the chart_blocked record —
    its `agent_name` should be `scribemd-chart-committer` or similar.

    `on_step("step_name", payload)` is called at each milestone — the demo
    CLI uses this to print narrated progress; tests use it to assert
    intermediate state.
    """
    vera = chart_vera

    if on_step is None:
        on_step = lambda *_: None  # noqa: E731

    record_ids: list[str] = []

    # 1. Draft the SOAP note
    on_step(
        "draft_started",
        {"encounter_id": encounter.encounter_id, "patient": encounter.patient.safe_summary()},
    )
    drafted = drafter.draft(
        transcript=encounter.transcript,
        patient_subject_id=encounter.patient.subject_id,
        encounter_id=encounter.encounter_id,
    )
    record_ids.append(drafted["record_id"])
    on_step("draft_complete", drafted)

    # 2. Extract orders
    extracted = extractor.extract(
        note=drafted["note"],
        patient_subject_id=encounter.patient.subject_id,
        encounter_id=encounter.encounter_id,
    )
    record_ids.append(extracted["record_id"])
    on_step("orders_extracted", extracted)

    # 3. Decide HITL: any new diagnosis OR any new med order requires sign-off.
    needs_approval = bool(
        extracted["diagnoses"] or extracted["medication_orders"]
    )
    risk_tier = _classify_risk(extracted["diagnoses"], encounter.chief_complaint)

    if not needs_approval:
        # Note has no orders / new diagnoses — auto-commit (rare, but supported)
        commit = vera.record_action(
            action_name="chart_commit",
            action_type="state_change",
            result="success",
            data_subject_id=encounter.patient.subject_id,
            input_data={
                "encounter_id": encounter.encounter_id,
                "note_record_id": drafted["record_id"],
                "extraction_record_id": extracted["record_id"],
            },
            outcome={"committed": True, "auto_approved": True, "reason": "no_orders_or_diagnoses"},
            reasoning={"hitl_required": False},
        )
        record_ids.append(commit["id"])
        on_step("chart_committed", {"auto": True, "record_id": commit["id"]})
        return EncounterResult(
            encounter_id=encounter.encounter_id,
            note=drafted["note"],
            diagnoses=[],
            medication_orders=[],
            lab_or_imaging_orders=extracted["lab_or_imaging_orders"],
            risk_tier="low",
            approval_id=None,
            approval_status="auto_committed",
            chart_committed=True,
            record_ids=record_ids,
        )

    # 4. Request HITL approval
    approval = vera.request_approval(
        action_name="commit_clinical_note",
        risk_tier=risk_tier,
        action_summary=(
            f"Commit note for encounter {encounter.encounter_id}: "
            f"{len(extracted['diagnoses'])} diagnosis(es), "
            f"{len(extracted['medication_orders'])} med order(s)"
        ),
        data_subject_id=encounter.patient.subject_id,
        context={
            "encounter_id": encounter.encounter_id,
            "patient_mrn": encounter.patient.mrn,
            "diagnoses": extracted["diagnoses"],
            "medication_orders": extracted["medication_orders"],
            "lab_or_imaging_orders": extracted["lab_or_imaging_orders"],
            "note_record_id": drafted["record_id"],
            "extraction_record_id": extracted["record_id"],
        },
        approvers_required=1,
        expires_in_seconds=approval_timeout_seconds,
    )
    on_step(
        "approval_requested",
        {"approval_id": approval["id"], "risk_tier": risk_tier, "context": approval.get("context", {})},
    )

    # 5. Drive the physician callback. In demo mode this auto-approves with
    #    a narrated pause; in CI mode it returns deterministically; in
    #    production a real physician decides via the Vera dashboard.
    decision, approver, note = physician_callback(approval)
    decided = _decide_approval_via_api(vera, approval["id"], decision, approver, note)
    on_step(
        "approval_decided",
        {"approval_id": approval["id"], "decision": decision, "approver": approver},
    )

    # Poll until the approval reaches a terminal state (single-approver setups
    # resolve immediately, but this also handles dual-approver paths).
    try:
        resolved = vera.wait_for_approval(approval["id"], timeout=10.0, poll_interval=0.5)
        approval_status = resolved.get("status", "approved")
    except ApprovalRejectedError as e:
        approval_status = e.approval.get("status", "rejected")

    chart_committed = approval_status == "approved"
    if chart_committed:
        commit = vera.record_action(
            action_name="chart_commit",
            action_type="state_change",
            result="success",
            data_subject_id=encounter.patient.subject_id,
            input_data={
                "encounter_id": encounter.encounter_id,
                "approval_id": approval["id"],
                "approver": approver,
            },
            outcome={
                "committed": True,
                "diagnoses": extracted["diagnoses"],
                "medication_orders": extracted["medication_orders"],
                "lab_or_imaging_orders": extracted["lab_or_imaging_orders"],
            },
            reasoning={"hitl_required": True, "risk_tier": risk_tier},
        )
        record_ids.append(commit["id"])
        on_step("chart_committed", {"auto": False, "record_id": commit["id"]})
    else:
        blocked = vera.record_action(
            action_name="chart_blocked",
            action_type="state_change",
            result="success",
            data_subject_id=encounter.patient.subject_id,
            input_data={
                "encounter_id": encounter.encounter_id,
                "approval_id": approval["id"],
                "approver": approver,
            },
            outcome={"committed": False, "approval_status": approval_status},
            reasoning={"hitl_required": True, "risk_tier": risk_tier},
        )
        record_ids.append(blocked["id"])
        on_step(
            "chart_blocked",
            {"approval_status": approval_status, "record_id": blocked["id"]},
        )

    return EncounterResult(
        encounter_id=encounter.encounter_id,
        note=drafted["note"],
        diagnoses=extracted["diagnoses"],
        medication_orders=extracted["medication_orders"],
        lab_or_imaging_orders=extracted["lab_or_imaging_orders"],
        risk_tier=risk_tier,
        approval_id=approval["id"],
        approval_status=approval_status,
        chart_committed=chart_committed,
        record_ids=record_ids,
    )


# ── Built-in physician callbacks ────────────────────────────────────────────


def auto_approve_callback(delay_seconds: float = 3.0) -> PhysicianCallback:
    """Pause `delay_seconds` (for the screenshare narration), then approve."""

    def cb(approval: dict) -> tuple[str, str, Optional[str]]:
        time.sleep(delay_seconds)
        return ("approve", "Dr. Adams (auto-demo)", "Reviewed and accepted as-is.")

    return cb


def always_reject_callback() -> PhysicianCallback:
    def cb(approval: dict) -> tuple[str, str, Optional[str]]:
        return ("reject", "Dr. Adams (auto-demo)", "Demo: rejecting to show blocked path.")

    return cb
