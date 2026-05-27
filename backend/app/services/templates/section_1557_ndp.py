"""Section 1557 Nondiscrimination Policy skeleton.

Renders a Markdown nondiscrimination policy + grievance procedure that
satisfies the Section 1557 surface requirements (45 CFR § 92). The
generator does NOT pre-populate the coordinator name or contact — those
are placeholders the org's counsel fills in before sign-off.

Voice rules
-----------
No bare imperatives ("Consider X" / "Recommended: X"). "Customer" not
"Hospital" / "Tenant". Full-date format with year.
"""

from __future__ import annotations

from ._common import REPLACE_MARKER, generated_note


_COORDINATOR_MARKER = "<<REPLACE WITH NONDISCRIMINATION COORDINATOR NAME + CONTACT>>"


def _coordinator_text(wizard_answers) -> str:
    """Build the Coordinator block.

    Section 1557 technically asks for a Nondiscrimination Coordinator,
    which is often (but not always) the same person as the HIPAA
    Privacy Officer. We pre-fill with the wizard's Privacy Officer
    answer when present, prefixed with an HTML comment so counsel sees
    that this was auto-filled and can replace inline if the
    Nondiscrimination Coordinator is actually a different person.
    """
    po = getattr(wizard_answers, "privacy_officer", None)
    if po is None:
        return _COORDINATOR_MARKER
    name = getattr(po, "name", None)
    email = getattr(po, "email", None)
    if not name or not email:
        return _COORDINATOR_MARKER
    return (
        "<!-- Pre-filled from your onboarding answers (Privacy Officer). "
        "If your Nondiscrimination Coordinator differs, replace inline. -->\n"
        f"{name} ({email})"
    )


def generate_section_1557_ndp(wizard_answers, org) -> str:
    """Render the Section 1557 NDP Markdown skeleton."""
    org_name = (org.name or "Customer organization").strip() or "Customer organization"

    parts: list[str] = []
    parts.append("# Section 1557 Nondiscrimination Policy")
    parts.append("")
    parts.append(generated_note())
    parts.append("")
    parts.append(
        f"This policy implements the obligations of **{org_name}** "
        "under Section 1557 of the Affordable Care Act (45 CFR § 92). "
        "Consider reviewing each section with counsel before posting "
        "publicly or distributing to staff."
    )
    parts.append("")

    # ── 1. Statement of nondiscrimination ───────────────────────────
    parts.append("## 1. Statement of nondiscrimination")
    parts.append("")
    parts.append(
        f"**{org_name}** does not discriminate, exclude, or treat "
        "individuals differently on the basis of race, color, national "
        "origin, sex (including sexual orientation and gender "
        "identity), age, or disability in any of its health programs "
        "or activities. This nondiscrimination policy applies to all "
        "AI-assisted services the organization operates."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 2. Coordinator ──────────────────────────────────────────────
    parts.append("## 2. Section 1557 Coordinator")
    parts.append("")
    parts.append(
        "The Section 1557 Coordinator is responsible for receiving "
        "grievances, ensuring corrective action, and serving as the "
        "primary contact for individuals seeking accommodations."
    )
    parts.append("")
    parts.append(_coordinator_text(wizard_answers))
    parts.append("")

    # ── 3. Grievance procedure ──────────────────────────────────────
    parts.append("## 3. Grievance procedure")
    parts.append("")
    parts.append(
        "Recommended steps for any individual who believes they have "
        "been discriminated against:"
    )
    parts.append("")
    parts.append(
        "1. Submit a written grievance to the Section 1557 Coordinator "
        "within 60 days of the alleged incident."
    )
    parts.append(
        "2. The Coordinator acknowledges receipt within 5 business "
        "days and opens an investigation."
    )
    parts.append(
        "3. The Coordinator issues a written determination within 30 "
        "days, including any corrective action."
    )
    parts.append(
        "4. The grievant may appeal to the Office for Civil Rights "
        "(U.S. Department of Health and Human Services) at any point."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 4. Training program ─────────────────────────────────────────
    parts.append("## 4. Training program")
    parts.append("")
    parts.append(
        "Recommended: all workforce members with patient-facing "
        "responsibilities complete Section 1557 training at hire and "
        "annually thereafter. Consider documenting the training "
        "curriculum, completion records, and the evidence trail tying "
        "each completion to a workforce member."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 5. Language access ──────────────────────────────────────────
    parts.append("## 5. Language access")
    parts.append("")
    parts.append(
        f"**{org_name}** is committed to meaningful access for "
        "individuals with limited English proficiency and effective "
        "communication for individuals with disabilities at no cost "
        "to the individual."
    )
    parts.append("")
    parts.append(
        "Recommended: list the qualified-interpreter and translated-"
        "materials channels currently in place, the top languages "
        "served, and the escalation path when a needed language is "
        "not on the standing list."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    return "\n".join(parts)
