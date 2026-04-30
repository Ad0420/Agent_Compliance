"""Synthetic triage sessions. Each session pairs a patient profile with
a symptom narrative the triage classifier will read.

Crafted to land on different policy outcomes:
  - `easy_self_care`         — common cold, no red flags → auto-route low.
  - `red_flag_chest_pain`    — exertional chest pain + diaphoresis + jaw
                               radiation → classifier under-triages,
                               red-flag detector fires, HITL fires.
  - `ambiguous`              — moderate symptoms, no clear red flag →
                               virtual visit, no HITL.
"""

from __future__ import annotations

from dataclasses import dataclass

from simulator.shared.fixtures.patients import Patient, make_patient


@dataclass
class TriageFixture:
    session_id: str
    patient: Patient
    chief_complaint: str
    symptoms: str
    expected_classifier_level: str  # "self_care" | "virtual_visit" | "urgent_care" | "ER"
    expected_red_flag: bool
    expected_recommended_override: str | None


def easy_self_care_session() -> TriageFixture:
    patient = make_patient(seed=2001)
    symptoms = (
        "I've had a runny nose, mild sore throat, and a low-grade fever "
        "(99.5F) for the past two days. No shortness of breath, no chest "
        "pain. Drinking fluids, resting at home. Just want to know if I "
        "should see a doctor."
    )
    return TriageFixture(
        session_id="ses_easy_001",
        patient=patient,
        chief_complaint="Cold-like symptoms x 2 days",
        symptoms=symptoms,
        expected_classifier_level="self_care",
        expected_red_flag=False,
        expected_recommended_override=None,
    )


def red_flag_chest_pain_session() -> TriageFixture:
    patient = make_patient(seed=2002)
    symptoms = (
        "I'm a 58 year old man with high blood pressure. Started getting "
        "pressure in the middle of my chest while walking up the stairs "
        "this morning. The pain spread to my left jaw a little. I was "
        "sweating a lot, more than usual. It eased up after I sat down for "
        "ten minutes. I'm a bit short of breath now too."
    )
    return TriageFixture(
        session_id="ses_chestpain_002",
        patient=patient,
        chief_complaint="Exertional chest pain with jaw radiation and diaphoresis",
        symptoms=symptoms,
        expected_classifier_level="virtual_visit",
        expected_red_flag=True,
        expected_recommended_override="ER",
    )


def ambiguous_session() -> TriageFixture:
    patient = make_patient(seed=2003)
    symptoms = (
        "Cough for the last 5 days, mostly dry but a little productive in "
        "the mornings. Fever up to 101.2F yesterday, down to 99 today with "
        "Tylenol. Tired, achy, but eating okay. No chest pain, no "
        "shortness of breath, no confusion."
    )
    return TriageFixture(
        session_id="ses_ambiguous_003",
        patient=patient,
        chief_complaint="Cough + intermittent fever x 5 days",
        symptoms=symptoms,
        expected_classifier_level="virtual_visit",
        expected_red_flag=False,
        expected_recommended_override=None,
    )


ALL_SESSIONS: dict[str, callable] = {
    "easy_self_care": easy_self_care_session,
    "red_flag_chest_pain": red_flag_chest_pain_session,
    "ambiguous": ambiguous_session,
}
