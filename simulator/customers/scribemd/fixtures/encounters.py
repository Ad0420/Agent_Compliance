"""Synthetic visit transcripts. Each encounter pairs a patient profile with
a clinician transcript that the scribe agent will turn into a SOAP note.

These are intentionally crafted to land on different policy outcomes:
  - `acute_pancreatitis`  → new high-risk diagnosis + new med orders → HITL fires
  - `routine_followup`    → low risk, possibly auto-approve in some configs
  - `chest_pain`          → red-flag symptom set → critical risk tier
"""

from __future__ import annotations

from dataclasses import dataclass

from simulator.shared.fixtures.patients import Patient, make_patient


@dataclass
class Encounter:
    encounter_id: str
    patient: Patient
    visit_type: str  # "office" | "urgent" | "telehealth"
    chief_complaint: str
    transcript: str
    expected_risk: str  # "low" | "medium" | "high" | "critical" — for assertions in B-mode


def acute_pancreatitis_encounter() -> Encounter:
    patient = make_patient(seed=1001)
    transcript = (
        "PHYSICIAN: How long have you had the pain?\n"
        "PATIENT: Started yesterday after dinner. Sharp, in my upper belly, "
        "going through to my back. Worse when I lie down. I've thrown up twice.\n"
        "PHYSICIAN: Any fever, chills?\n"
        "PATIENT: Felt warm last night. No chills.\n"
        "PHYSICIAN: Drinking history?\n"
        "PATIENT: A few beers most nights. More on weekends.\n"
        "PHYSICIAN: Tender to palpation in the epigastrium, guarding present. "
        "No rebound. Bowel sounds hypoactive. Going to send labs — lipase, "
        "amylase, CMP, CBC — and an abdominal ultrasound. Likely acute "
        "pancreatitis. NPO, IV fluids, ondansetron for nausea. Admitting."
    )
    return Encounter(
        encounter_id="enc_pancreatitis_001",
        patient=patient,
        visit_type="urgent",
        chief_complaint="Severe epigastric pain x 1 day with vomiting",
        transcript=transcript,
        expected_risk="high",
    )


def routine_followup_encounter() -> Encounter:
    patient = make_patient(seed=1002)
    transcript = (
        "PHYSICIAN: Three-month diabetes follow-up. How's the metformin?\n"
        "PATIENT: Tolerating it fine. No GI side effects since the dose change.\n"
        "PHYSICIAN: A1c came back at 6.8, down from 7.4. Blood pressure today "
        "118 over 76. Continue current regimen, recheck A1c in 3 months. "
        "Reminded patient about annual eye exam."
    )
    return Encounter(
        encounter_id="enc_followup_002",
        patient=patient,
        visit_type="office",
        chief_complaint="Routine T2DM follow-up",
        transcript=transcript,
        expected_risk="low",
    )


def chest_pain_encounter() -> Encounter:
    patient = make_patient(seed=1003)
    transcript = (
        "PHYSICIAN: Tell me about the chest pain.\n"
        "PATIENT: Came on this morning while I was walking. Pressure, mid-chest. "
        "Lasted maybe 15 minutes, then eased. Some shortness of breath.\n"
        "PHYSICIAN: Any radiation? Sweating?\n"
        "PATIENT: Felt it in my left jaw a bit. Yeah, I was clammy.\n"
        "PHYSICIAN: Risk factors — hypertension, father had an MI at 58. "
        "EKG shows non-specific T-wave changes. Sending troponin, repeat in "
        "3 hours. Aspirin 325 chewed now. Cardiology consult requested. "
        "Considering NSTEMI vs unstable angina."
    )
    return Encounter(
        encounter_id="enc_chestpain_003",
        patient=patient,
        visit_type="urgent",
        chief_complaint="Exertional chest pain with associated SOB and diaphoresis",
        transcript=transcript,
        expected_risk="critical",
    )


ALL_ENCOUNTERS: dict[str, callable] = {
    "pancreatitis": acute_pancreatitis_encounter,
    "followup": routine_followup_encounter,
    "chest_pain": chest_pain_encounter,
}
