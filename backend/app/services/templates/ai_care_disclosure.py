"""AI-Assisted Care Disclosure — patient-facing standing notice.

Always emits the core patient-rights sections plus a contact line. The
jurisdiction-driven sections (California AB 489, Texas TRAIGA, Utah
AIPA) are appended in deterministic order based on the
``wizard_answers.jurisdictions`` list — re-generating with a different
jurisdiction set deterministically adds or removes the corresponding
block, so an UN-attested disclosure stays in sync with the wizard.

Headings are stable so the diff is clean across re-generations:
``## California (AB 489) — clinical decision support disclosure``,
``## Texas (TRAIGA) — healthcare AI consent and risk disclosure``,
``## Utah (AIPA) — generative AI disclosure``.

Voice rules
-----------
No bare imperatives. "Customer" not "Hospital" / "Tenant". No
"court-admissible".
"""

from __future__ import annotations

from ._common import (
    CALIFORNIA_SLUGS,
    REPLACE_MARKER,
    TEXAS_SLUGS,
    UTAH_SLUGS,
    generated_note,
    has_jurisdiction,
)


_COMPLIANCE_OFFICER_MARKER = "<<REPLACE WITH COMPLIANCE OFFICER CONTACT>>"


def _california_clause() -> list[str]:
    return [
        "## California (AB 489) — clinical decision support disclosure",
        "",
        (
            "California Assembly Bill 489 requires that when AI is used "
            "to support clinical decision-making, the use must be "
            "disclosed to the affected individual and to the licensed "
            "clinician supervising the decision. Recommended disclosure "
            "elements:"
        ),
        "",
        "- The clinical context in which AI assistance is used",
        "- The role of the supervising licensed clinician",
        "- How the individual can request human review",
        "",
        f"{REPLACE_MARKER}",
        "",
    ]


def _texas_clause() -> list[str]:
    return [
        "## Texas (TRAIGA) — healthcare AI consent and risk disclosure",
        "",
        (
            "The Texas Responsible AI Governance Act (TRAIGA) requires "
            "informed consent and risk disclosure for the use of AI in "
            "healthcare contexts. Recommended disclosure elements:"
        ),
        "",
        "- The categories of decisions AI assists with",
        "- The known risks of the AI-assisted process",
        "- The individual's right to opt out of AI-assisted handling",
        "",
        f"{REPLACE_MARKER}",
        "",
    ]


def _utah_clause() -> list[str]:
    return [
        "## Utah (AIPA) — generative AI disclosure",
        "",
        (
            "Utah's Artificial Intelligence Policy Act (AIPA) requires "
            "disclosure when generative AI is used in connection with "
            "regulated services. Recommended disclosure elements:"
        ),
        "",
        "- That generative AI is part of the interaction",
        "- The supervising licensed professional, if any",
        "- The channel for asking questions about the AI's role",
        "",
        f"{REPLACE_MARKER}",
        "",
    ]


def generate_ai_care_disclosure(wizard_answers, org) -> str:
    """Render the patient-facing AI-Assisted Care Disclosure."""
    org_name = (org.name or "Customer organization").strip() or "Customer organization"
    jurisdictions = getattr(wizard_answers, "jurisdictions", None) or []

    parts: list[str] = []
    parts.append("# AI-Assisted Care Disclosure")
    parts.append("")
    parts.append(generated_note())
    parts.append("")
    parts.append(
        f"This standing notice describes how **{org_name}** uses "
        "AI-assisted services in your care. Consider posting this "
        "notice prominently in patient-facing spaces and providing "
        "a copy on request."
    )
    parts.append("")

    # ── Always-included: What AI is used ────────────────────────────
    parts.append("## What AI is used")
    parts.append("")
    parts.append(
        f"**{org_name}** uses AI-assisted services to support specific "
        "parts of clinical workflows. The AI does not replace a "
        "licensed clinician's judgment; a qualified human is "
        "responsible for the final decision in every case."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── Always-included: Patient rights ─────────────────────────────
    parts.append("## Patient rights")
    parts.append("")
    parts.append("As a patient interacting with AI-assisted services, you have the right to:")
    parts.append("")
    parts.append("- Know when AI is used in connection with your care")
    parts.append("- Request that a human clinician review any AI-assisted decision")
    parts.append("- Receive a clear explanation of the AI's role in plain language")
    parts.append("- File a grievance if you believe the AI handling was inappropriate")
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── Always-included: Contact for questions ──────────────────────
    parts.append("## Contact for questions")
    parts.append("")
    parts.append(
        "For questions about how AI is used in your care, please "
        "contact:"
    )
    parts.append("")
    parts.append(f"{_COMPLIANCE_OFFICER_MARKER}")
    parts.append("")

    # ── Conditional clauses, deterministic order ────────────────────
    # CA → TX → UT. Re-running generation with a different jurisdiction
    # set deterministically adds or removes clauses; the headings are
    # stable so the diff is clean.
    if has_jurisdiction(jurisdictions, CALIFORNIA_SLUGS):
        parts.extend(_california_clause())
    if has_jurisdiction(jurisdictions, TEXAS_SLUGS):
        parts.extend(_texas_clause())
    if has_jurisdiction(jurisdictions, UTAH_SLUGS):
        parts.extend(_utah_clause())

    return "\n".join(parts)
