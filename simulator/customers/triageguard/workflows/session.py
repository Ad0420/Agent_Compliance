"""End-to-end triage session pipeline for TriageGuard.

Implements Use Case 3 from `use_cases.md`:

    1. Patient describes symptoms.
    2. TriageClassifier returns initial level.
    3. RedFlagDetector evaluates the same narrative.
    4. Decision logic:
         - if red-flag fires AND classifier said self_care/virtual_visit:
             → request_approval (HITL gate); nurse confirms or escalates
         - else: auto-route at AI's level
    5. Final routed/routing_blocked record committed.

`nurse_callback` lets the demo (Mode A) auto-decide after a narrated
pause and lets the test suite drive deterministic decisions. In
production, the on-call RN decides via the dashboard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from vera import ApprovalRejectedError, VeraClient

from simulator.customers.triageguard.agents.red_flag_detector import (
    RedFlagDetectorAgent,
)
from simulator.customers.triageguard.agents.triage_classifier import (
    TriageClassifierAgent,
)
from simulator.customers.triageguard.fixtures.sessions import TriageFixture


_LOW_ACUITY = {"self_care", "virtual_visit"}
_VALID_LEVELS = {"self_care", "virtual_visit", "urgent_care", "ER"}


@dataclass
class SessionResult:
    session_id: str
    initial_level: str
    final_level: str
    classifier_reasoning: str
    red_flag_fired: bool
    red_flag_terms: list[str]
    recommended_override: Optional[str]
    risk_tier: str
    approval_id: Optional[str]
    nurse_status: str  # "confirm" | "escalate" | "auto" | "auto_escalated_timeout" | "expired"
    routing_committed: bool
    record_ids: list[str]


# A nurse callback returns (decision, nurse, note) where decision is
# "confirm" | "escalate".
NurseCallback = Callable[[dict], tuple[str, str, Optional[str]]]


def _classify_risk(*, classifier_level: str, flagged: bool, final_level: str) -> str:
    """Map (classifier, red_flag, final) → risk_tier."""
    if flagged and final_level == "ER":
        return "critical"
    if flagged and classifier_level in _LOW_ACUITY:
        return "high"
    if classifier_level in {"urgent_care", "virtual_visit"}:
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

    Mirrors ScribeMD's helper. We send `approve` for nurse `confirm` and
    `reject` for nurse `escalate` so Vera's approval state machine sees
    the same shape it does for any other HITL gate — TriageGuard's
    domain semantics layer on top.
    """
    api_decision = "approve" if decision == "confirm" else "reject"
    payload = {"decision": api_decision, "approver": approver, "note": note}
    resp = vera._client.post(f"/v1/approvals/{approval_id}/decide", json=payload)
    resp.raise_for_status()
    return resp.json()


def run_session(
    *,
    fixture: TriageFixture,
    classifier: TriageClassifierAgent,
    detector: RedFlagDetectorAgent,
    routing_vera: VeraClient,
    nurse_callback: NurseCallback,
    review_timeout_seconds: int = 300,
    on_step: Optional[Callable[[str, dict], None]] = None,
) -> SessionResult:
    """Run a single triage session end-to-end.

    Each agent owns its own Vera client (own `agent_name` on the chain).
    `routing_vera` is the client used for the request_approval call,
    the routed (success) record, and the routing_blocked (failure)
    record — its `agent_name` should be `triageguard-routing-committer`.

    `on_step("event_name", payload)` is the runner's hook to fan events
    onto the SSE bus and persist them.
    """
    if on_step is None:
        on_step = lambda *_: None  # noqa: E731

    record_ids: list[str] = []

    # 1. Patient session starts
    on_step(
        "session_started",
        {
            "session_id": fixture.session_id,
            "patient": fixture.patient.safe_summary(),
        },
    )

    # 2. Classifier
    classified = classifier.classify(
        symptoms=fixture.symptoms,
        patient_subject_id=fixture.patient.subject_id,
        session_id=fixture.session_id,
    )
    record_ids.append(classified["record_id"])
    on_step("triage_classified", classified)

    initial_level = classified["level"]

    # 3. Red-flag detector
    flagged_result = detector.evaluate(
        symptoms=fixture.symptoms,
        classifier_level=initial_level,
        patient_subject_id=fixture.patient.subject_id,
        session_id=fixture.session_id,
    )
    record_ids.append(flagged_result["record_id"])
    on_step("red_flag_evaluated", flagged_result)

    red_flag_fired = flagged_result["flagged"]
    recommended_override = flagged_result["recommended_override"]

    # 4. Decision logic
    needs_review = red_flag_fired and initial_level in _LOW_ACUITY

    if not needs_review:
        # Auto-route at AI's level.
        final_level = initial_level
        risk_tier = _classify_risk(
            classifier_level=initial_level,
            flagged=red_flag_fired,
            final_level=final_level,
        )
        commit = routing_vera.record_action(
            action_name="route_patient",
            action_type="state_change",
            result="success",
            data_subject_id=fixture.patient.subject_id,
            input_data={
                "session_id": fixture.session_id,
                "classifier_record_id": classified["record_id"],
                "red_flag_record_id": flagged_result["record_id"],
            },
            outcome={
                "final_level": final_level,
                "auto": True,
                "red_flag_fired": red_flag_fired,
            },
            reasoning={
                "hitl_required": False,
                "risk_tier": risk_tier,
                "decision_path": "auto_route",
            },
        )
        record_ids.append(commit["id"])
        on_step(
            "routed",
            {
                "final_level": final_level,
                "auto": True,
                "record_id": commit["id"],
                "risk_tier": risk_tier,
            },
        )
        return SessionResult(
            session_id=fixture.session_id,
            initial_level=initial_level,
            final_level=final_level,
            classifier_reasoning=classified["reasoning"],
            red_flag_fired=red_flag_fired,
            red_flag_terms=flagged_result["terms"],
            recommended_override=recommended_override,
            risk_tier=risk_tier,
            approval_id=None,
            nurse_status="auto",
            routing_committed=True,
            record_ids=record_ids,
        )

    # HITL gate
    risk_tier_pre = _classify_risk(
        classifier_level=initial_level,
        flagged=True,
        # Worst-case assumption pre-decision so the approval surfaces with
        # the right urgency. We re-compute final risk after the decision.
        final_level=recommended_override or "urgent_care",
    )

    approval = routing_vera.request_approval(
        action_name="route_patient",
        risk_tier=risk_tier_pre,
        action_summary=(
            f"Triage session {fixture.session_id}: classifier said "
            f"{initial_level!r}; red-flag detector fired "
            f"({len(flagged_result['terms'])} term(s)); recommended "
            f"override {recommended_override!r}. Nurse review required."
        ),
        data_subject_id=fixture.patient.subject_id,
        context={
            "session_id": fixture.session_id,
            "patient_mrn": fixture.patient.mrn,
            "classifier_level": initial_level,
            "classifier_reasoning": classified["reasoning"],
            "red_flag_terms": flagged_result["terms"],
            "red_flag_reasoning": flagged_result["reasoning"],
            "recommended_override": recommended_override,
            "classifier_record_id": classified["record_id"],
            "red_flag_record_id": flagged_result["record_id"],
        },
        approvers_required=1,
        expires_in_seconds=review_timeout_seconds,
    )
    on_step(
        "nurse_review_requested",
        {
            "approval_id": approval["id"],
            "risk_tier": risk_tier_pre,
            "context": approval.get("context", {}),
        },
    )

    # Drive the nurse callback. In demo mode this auto-decides with a
    # narrated pause; in tests it returns deterministically.
    decision, nurse, decision_note = nurse_callback(approval)
    decided = _decide_approval_via_api(
        routing_vera, approval["id"], decision, nurse, decision_note
    )
    on_step(
        "nurse_decided",
        {
            "approval_id": approval["id"],
            "decision": decision,
            "nurse": nurse,
        },
    )

    # Poll until terminal
    try:
        resolved = routing_vera.wait_for_approval(
            approval["id"], timeout=10.0, poll_interval=0.5
        )
        approval_status = resolved.get("status", "approved")
    except ApprovalRejectedError as e:
        # Vera maps "reject" → rejected; we use that for nurse `escalate`.
        approval_status = e.approval.get("status", "rejected")

    if decision == "confirm":
        nurse_status = "confirm"
        final_level = initial_level
    elif decision == "escalate":
        nurse_status = "escalate"
        final_level = recommended_override or "urgent_care"
    else:
        nurse_status = "expired"
        final_level = recommended_override or "urgent_care"

    risk_tier = _classify_risk(
        classifier_level=initial_level,
        flagged=True,
        final_level=final_level,
    )

    if final_level not in _VALID_LEVELS:
        # Defense in depth — should never happen given upstream validation.
        final_level = "urgent_care"

    routed = True
    if approval_status in ("approved", "rejected"):
        commit = routing_vera.record_action(
            action_name="route_patient",
            action_type="state_change",
            result="success",
            data_subject_id=fixture.patient.subject_id,
            input_data={
                "session_id": fixture.session_id,
                "approval_id": approval["id"],
                "nurse": nurse,
            },
            outcome={
                "final_level": final_level,
                "auto": False,
                "nurse_status": nurse_status,
                "red_flag_fired": True,
            },
            reasoning={
                "hitl_required": True,
                "risk_tier": risk_tier,
                "decision_path": "nurse_review",
            },
        )
        record_ids.append(commit["id"])
        on_step(
            "routed",
            {
                "final_level": final_level,
                "auto": False,
                "record_id": commit["id"],
                "risk_tier": risk_tier,
                "nurse_status": nurse_status,
            },
        )
    else:
        # Approval expired or otherwise terminal-without-decision
        blocked = routing_vera.record_action(
            action_name="routing_blocked",
            action_type="state_change",
            result="success",
            data_subject_id=fixture.patient.subject_id,
            input_data={
                "session_id": fixture.session_id,
                "approval_id": approval["id"],
            },
            outcome={
                "approval_status": approval_status,
                "final_level": None,
            },
            reasoning={
                "hitl_required": True,
                "risk_tier": risk_tier,
                "decision_path": "blocked",
            },
        )
        record_ids.append(blocked["id"])
        on_step(
            "routing_blocked",
            {"approval_status": approval_status, "record_id": blocked["id"]},
        )
        routed = False

    return SessionResult(
        session_id=fixture.session_id,
        initial_level=initial_level,
        final_level=final_level,
        classifier_reasoning=classified["reasoning"],
        red_flag_fired=True,
        red_flag_terms=flagged_result["terms"],
        recommended_override=recommended_override,
        risk_tier=risk_tier,
        approval_id=approval["id"],
        nurse_status=nurse_status,
        routing_committed=routed,
        record_ids=record_ids,
    )


# ── Built-in nurse callbacks (handy for the demo CLI) ──────────────────────


def auto_confirm_callback(delay_seconds: float = 3.0) -> NurseCallback:
    def cb(approval: dict) -> tuple[str, str, Optional[str]]:
        time.sleep(delay_seconds)
        return ("confirm", "Nurse Rivera, RN (auto-demo)", "Reviewed; AI level looks right.")

    return cb


def auto_escalate_callback(delay_seconds: float = 3.0) -> NurseCallback:
    def cb(approval: dict) -> tuple[str, str, Optional[str]]:
        time.sleep(delay_seconds)
        return ("escalate", "Nurse Rivera, RN (auto-demo)", "Red flags warrant higher acuity.")

    return cb
