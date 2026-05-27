"""Workforce Training Outline skeleton.

Pulls ``wizard_answers.workforce_training_attestations`` (if present)
to surface the count + most-recent date of completed training. The
wizard does NOT currently capture this — Phase 5 PR A keeps the field
optional so a future onboarding-wizard expansion can populate it
without a schema change here. Today the body falls back to empty-state
guidance.

Voice rules
-----------
No bare imperatives. "Customer" not "Hospital" / "Tenant".
"""

from __future__ import annotations

from datetime import date, datetime

from ._common import REPLACE_MARKER, format_generated_date, generated_note


def _coerce_attestations(raw):
    """Best-effort coercion of the optional wizard field.

    The wizard schema in ``app/schemas/wizard.py`` doesn't define
    ``workforce_training_attestations`` today; this generator reads it
    defensively in case a future wizard expansion does. Accept either
    ``None``, a list (count = ``len(...)``), or a dict shaped
    ``{"count": int, "last_completed_at": "YYYY-MM-DD" | datetime}``.
    """
    if raw is None:
        return None, None
    if isinstance(raw, list):
        # List of attestation records; count + most-recent date if any
        # entry carries a ``completed_at`` key.
        count = len(raw)
        last = None
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("completed_at") or entry.get("date")
            if ts is None:
                continue
            if isinstance(ts, (date, datetime)):
                if last is None or ts > last:
                    last = ts
        return count, last
    if isinstance(raw, dict):
        count = raw.get("count")
        last = raw.get("last_completed_at")
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = None
        return count, last
    return None, None


def generate_workforce_training_outline(wizard_answers, org) -> str:
    """Render the Workforce Training Outline Markdown skeleton."""
    org_name = (org.name or "Customer organization").strip() or "Customer organization"

    # Wizard answers is a Pydantic model; ``getattr`` defends against
    # the field being absent (the schema doesn't define it today).
    raw_attestations = getattr(
        wizard_answers, "workforce_training_attestations", None
    )
    count, last_completed = _coerce_attestations(raw_attestations)

    parts: list[str] = []
    parts.append("# Workforce Training Outline")
    parts.append("")
    parts.append(generated_note())
    parts.append("")
    parts.append(
        f"This outline scopes the workforce training program **{org_name}** "
        "maintains for staff who interact with AI-assisted services. "
        "Recommended: revisit annually and whenever the training "
        "curriculum or workforce composition materially changes."
    )
    parts.append("")

    # ── Current attestation status ───────────────────────────────────
    parts.append("## Current attestation status")
    parts.append("")
    if count is not None:
        if last_completed is not None:
            last_str = (
                format_generated_date(last_completed)
                if isinstance(last_completed, (date, datetime))
                else str(last_completed)
            )
            parts.append(
                f"Workforce training attestations on file: **{count:,}** "
                f"(most recent: {last_str})."
            )
        else:
            parts.append(
                f"Workforce training attestations on file: **{count:,}**."
            )
    else:
        parts.append(
            "No workforce training attestations are captured on file "
            "yet. Recommended: log each completed training session "
            "against the responsible workforce member so the evidence "
            "trail can demonstrate program coverage."
        )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── Module outline ───────────────────────────────────────────────
    parts.append("## Required modules")
    parts.append("")
    parts.append(
        "Recommended module set for any workforce member with access "
        "to AI-assisted clinical surfaces:"
    )
    parts.append("")
    parts.append(
        "1. **HIPAA Privacy and Security** — annual refresher on "
        "minimum-necessary, accounting of disclosures, breach "
        "response."
    )
    parts.append(
        "2. **AI tool oversight** — when to escalate an AI output, "
        "how to log a clinical override, the evidence trail the "
        "workforce member is responsible for capturing."
    )
    parts.append(
        "3. **Section 1557 nondiscrimination** — recognising and "
        "escalating potential bias in AI outputs, the grievance "
        "process for affected individuals."
    )
    parts.append(
        "4. **Incident response** — first-touch protocol for "
        "suspected AI-related adverse events."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    # ── Cadence + record-keeping ─────────────────────────────────────
    parts.append("## Cadence and record-keeping")
    parts.append("")
    parts.append(
        "Recommended: initial training within 30 days of hire and "
        "annual refresher for every workforce member. Consider "
        "capturing the completion timestamp, the module version, "
        "and a signed attestation for each completion."
    )
    parts.append("")
    parts.append(f"{REPLACE_MARKER}")
    parts.append("")

    return "\n".join(parts)
