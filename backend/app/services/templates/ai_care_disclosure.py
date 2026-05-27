"""AI-Assisted Care Disclosure — patient-facing standing notice.

Always emits the core patient-rights sections plus a contact line. The
jurisdiction-driven sections (California AB 489, California SB 942,
Texas TRAIGA, Utah AIPA, Colorado SB 24-205, EU AI Act, New York
placeholder, Other) are appended in deterministic order based on the
``wizard_answers.jurisdictions`` list — re-generating with a different
jurisdiction set deterministically adds or removes the corresponding
block, so an UN-attested disclosure stays in sync with the wizard.

Headings are stable so the diff is clean across re-generations.

Voice rules
-----------
No bare imperatives. "Customer" not "Hospital" / "Tenant". No
"court-admissible".
"""

from __future__ import annotations

from ._common import (
    CALIFORNIA_AB489_SLUGS,
    CALIFORNIA_SB942_SLUGS,
    COLORADO_SLUGS,
    EU_SLUGS,
    NEW_YORK_SLUGS,
    OTHER_SLUGS,
    REPLACE_MARKER,
    TEXAS_SLUGS,
    UTAH_SLUGS,
    generated_note,
    has_jurisdiction,
)


_COMPLIANCE_OFFICER_MARKER = "<<REPLACE WITH COMPLIANCE OFFICER CONTACT>>"


def _california_ab489_clause() -> list[str]:
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


def _california_sb942_clause() -> list[str]:
    return [
        "## California (SB 942) — AI consumer disclosure",
        "",
        (
            "California Senate Bill 942 (the California AI Transparency "
            "Act) requires consumer-facing disclosure when AI generates "
            "content delivered to a California resident. Recommended "
            "disclosure elements:"
        ),
        "",
        "- A clear notice that AI generated or substantially modified the content",
        "- The detection-tool channel a recipient can use to verify provenance",
        "- The retention period for any AI-generated content metadata",
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


def _colorado_clause() -> list[str]:
    return [
        "## Colorado (SB 24-205) — consequential AI disclosure",
        "",
        (
            "Colorado Senate Bill 24-205 (the Colorado AI Act) requires "
            "disclosure when an AI system is used to make or substantially "
            "support a consequential decision affecting a Colorado "
            "consumer. Recommended disclosure elements:"
        ),
        "",
        "- The categories of consequential decisions the AI assists with",
        "- The right to opt out of profiling and to request human review",
        "- The channel for filing an appeal or correction request",
        "",
        f"{REPLACE_MARKER}",
        "",
    ]


def _eu_clause() -> list[str]:
    return [
        "## European Union (AI Act) — high-risk AI disclosure",
        "",
        (
            "The EU Artificial Intelligence Act Article 50(1) requires "
            "transparency notices when an individual interacts with an AI "
            "system or with AI-generated content. For high-risk AI in "
            "healthcare, additional Annex III obligations apply. "
            "Recommended disclosure elements:"
        ),
        "",
        "- A clear notice that the individual is interacting with an AI system",
        "- The intended purpose and known limitations of the AI",
        "- The right to a meaningful explanation of any consequential decision",
        "",
        f"{REPLACE_MARKER}",
        "",
    ]


def _new_york_clause() -> list[str]:
    # Single-paragraph placeholder. No REPLACE_MARKER — this clause IS
    # the marker; counsel decides whether NY DFS or NY-state-specific
    # disclosures apply and writes the actual clause out of band.
    return [
        "## New York — coordinate with counsel",
        "",
        (
            "Vera does not yet have a built-in clause for New York-specific "
            "AI requirements. Coordinate with counsel on whether NY DFS or "
            "NY state-specific disclosures apply to your deployment."
        ),
        "",
    ]


def _other_clause(entries: list[str] | None) -> list[str]:
    """Render the "Other jurisdictions" section.

    Always emits the heading + intro when this function is called (the
    caller has already confirmed ``other`` is in the jurisdictions
    list). When ``entries`` is empty or None we still render the
    heading so counsel sees the placeholder — the contract is soft:
    the disclosure surfaces a marker regardless of whether the
    operator filled in the free-text list.
    """
    parts: list[str] = [
        "## Other jurisdictions — coordinate with counsel",
        "",
    ]
    if entries:
        parts.append(
            "Vera does not have built-in clauses for the jurisdictions "
            "below. Coordinate with counsel on the applicable "
            "disclosure language:"
        )
        parts.append("")
        for entry in entries:
            parts.append(
                f"- Coordinate with counsel on {entry}-specific requirements."
            )
        parts.append("")
    else:
        parts.append(
            "Other jurisdictions were flagged at onboarding but no "
            "free-text descriptions were captured. Coordinate with "
            "counsel on the applicable disclosure language."
        )
        parts.append("")
    return parts


def generate_ai_care_disclosure(wizard_answers, org) -> str:
    """Render the patient-facing AI-Assisted Care Disclosure."""
    org_name = (org.name or "Customer organization").strip() or "Customer organization"
    jurisdictions = getattr(wizard_answers, "jurisdictions", None) or []
    jurisdictions_other = (
        getattr(wizard_answers, "jurisdictions_other", None) or []
    )

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
    # CA AB 489 → CA SB 942 → TX → UT → CO → EU → NY → Other. Re-
    # running generation with a different jurisdiction set
    # deterministically adds or removes clauses; the headings are
    # stable so the diff is clean.
    if has_jurisdiction(jurisdictions, CALIFORNIA_AB489_SLUGS):
        parts.extend(_california_ab489_clause())
    if has_jurisdiction(jurisdictions, CALIFORNIA_SB942_SLUGS):
        parts.extend(_california_sb942_clause())
    if has_jurisdiction(jurisdictions, TEXAS_SLUGS):
        parts.extend(_texas_clause())
    if has_jurisdiction(jurisdictions, UTAH_SLUGS):
        parts.extend(_utah_clause())
    if has_jurisdiction(jurisdictions, COLORADO_SLUGS):
        parts.extend(_colorado_clause())
    if has_jurisdiction(jurisdictions, EU_SLUGS):
        parts.extend(_eu_clause())
    if has_jurisdiction(jurisdictions, NEW_YORK_SLUGS):
        parts.extend(_new_york_clause())
    if has_jurisdiction(jurisdictions, OTHER_SLUGS):
        parts.extend(_other_clause(jurisdictions_other))

    return "\n".join(parts)
