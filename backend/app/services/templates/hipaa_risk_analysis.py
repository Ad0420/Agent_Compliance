"""HIPAA Risk Analysis skeleton — § 164.308(a)(1)(ii)(A).

Generates a Markdown skeleton an organization's counsel + security team
can fill out and attest to. The body cites the Security Rule provision
that mandates a Risk Analysis (45 CFR § 164.308(a)(1)(ii)(A)) and
walks the seven required sections. Each section ends with a
``REPLACE_MARKER`` so reviewers know where to type their actual
practice.

Voice rules
-----------
No bare imperatives. We use "Consider X" / "Recommended: X" throughout.
"Customer" not "Hospital" / "Tenant". No "court-admissible".
"""

from __future__ import annotations

from ._common import REPLACE_MARKER, generated_note


# Marker for the Privacy Officer block. When ``wizard_answers.privacy_officer``
# is populated we substitute this marker with ``{name} ({email})``; when
# null we leave it in place so counsel can fill it in.
_PRIVACY_OFFICER_MARKER = "<<REPLACE WITH PRIVACY OFFICER NAME + CONTACT>>"


def _privacy_officer_text(wizard_answers) -> str:
    po = getattr(wizard_answers, "privacy_officer", None)
    if po is None:
        return _PRIVACY_OFFICER_MARKER
    name = getattr(po, "name", None)
    email = getattr(po, "email", None)
    if not name or not email:
        return _PRIVACY_OFFICER_MARKER
    return (
        "<!-- Pre-filled from your onboarding answers (Privacy Officer). "
        "If your designated HIPAA Privacy Officer differs, replace inline. -->\n"
        f"{name} ({email})"
    )


def generate_hipaa_risk_analysis(wizard_answers, org) -> str:
    """Render the HIPAA Risk Analysis Markdown skeleton.

    The generator does NOT pre-fill clinical content — that's the
    org's responsibility. We do pre-fill the org name in the
    Scope section so the document reads as belonging to the right
    legal entity, and the Privacy Officer block from the wizard's
    onboarding answer when available.
    """
    org_name = (org.name or "Customer organization").strip() or "Customer organization"

    parts: list[str] = []
    parts.append("# HIPAA Risk Analysis")
    parts.append("")
    parts.append(generated_note())
    parts.append("")
    parts.append(
        "This document is the skeleton of a HIPAA Security Rule Risk "
        "Analysis required by **45 CFR § 164.308(a)(1)(ii)(A)**. Each "
        "section is a placeholder; consider replacing every "
        f"`{REPLACE_MARKER}` marker with the actual practice for "
        f"**{org_name}** before counsel sign-off."
    )
    parts.append("")

    # ── 0. HIPAA Privacy Officer ─────────────────────────────────────
    # Pre-filled from the wizard's Privacy Officer answer when present.
    # The marker stays in place when no Privacy Officer is recorded so
    # counsel can fill it in during attestation.
    parts.append("## 0. HIPAA Privacy Officer")
    parts.append("")
    parts.append(
        "The Privacy Officer is responsible for the development and "
        "implementation of the privacy policies and procedures of the "
        "organization, as required by 45 CFR § 164.530(a)(1)."
    )
    parts.append("")
    parts.append(_privacy_officer_text(wizard_answers))
    parts.append("")

    # ── 1. Scope ─────────────────────────────────────────────────────
    parts.append("## 1. Scope")
    parts.append("")
    parts.append(
        f"This Risk Analysis covers all electronic protected health "
        f"information (ePHI) that **{org_name}** creates, receives, "
        "maintains, or transmits in the course of operating AI-assisted "
        "services. Consider including:"
    )
    parts.append("")
    parts.append("- Patient-facing and clinician-facing AI surfaces")
    parts.append("- Vendor sub-processors with access to ePHI")
    parts.append("- The Vera audit trail and any mirrored exports")
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 2. Asset & data inventory ────────────────────────────────────
    parts.append("## 2. Asset and data inventory")
    parts.append("")
    parts.append(
        "Consider listing every system that stores or processes ePHI, "
        "the categories of data each system handles, and the owners "
        "responsible for each system. Recommended columns: System, "
        "Data category, Owner, Hosting location, Encryption posture."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 3. Threat model ──────────────────────────────────────────────
    parts.append("## 3. Threat model")
    parts.append("")
    parts.append(
        "Consider enumerating the threats the inventory above is "
        "exposed to. Common categories include:"
    )
    parts.append("")
    parts.append("- External actors (phishing, credential stuffing, supply-chain compromise)")
    parts.append("- Insider misuse (over-broad access, exfiltration)")
    parts.append("- AI-specific risks (prompt injection, model output leakage, training-data exposure)")
    parts.append("- Operational failures (backup loss, key custody mistakes)")
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 4. Vulnerability assessment ──────────────────────────────────
    parts.append("## 4. Vulnerability assessment")
    parts.append("")
    parts.append(
        "Recommended: for each system in the inventory, document the "
        "vulnerabilities currently identified, the likelihood of "
        "exploitation, and the impact if exploited. Tie each finding "
        "back to the threats enumerated in section 3."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 5. Risk register ─────────────────────────────────────────────
    parts.append("## 5. Risk register")
    parts.append("")
    parts.append(
        "Consider maintaining a structured risk register with at least: "
        "risk id, description, likelihood (low/medium/high), impact "
        "(low/medium/high), residual rating, owner, mitigation, and "
        "review date. The register is the operational artifact a "
        "regulator-ready evidence trail points at."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 6. Controls assessment ───────────────────────────────────────
    parts.append("## 6. Controls assessment")
    parts.append("")
    parts.append(
        "For each risk in the register, document the administrative, "
        "physical, and technical safeguards currently in place. "
        "Recommended: cross-reference each control to the Security "
        "Rule citation it implements (e.g. § 164.312(b) for audit "
        "controls)."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── 7. Review cadence ────────────────────────────────────────────
    parts.append("## 7. Review cadence")
    parts.append("")
    parts.append(
        "Recommended: re-run this Risk Analysis at least annually and "
        "whenever a material change occurs (new AI tool, new vendor, "
        "incident, regulatory update). Consider documenting the "
        "trigger conditions, the responsible reviewer, and where the "
        "revised version is filed."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    return "\n".join(parts)
