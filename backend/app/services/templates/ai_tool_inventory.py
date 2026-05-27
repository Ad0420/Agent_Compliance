"""AI Tool Inventory skeleton.

A starting-point Markdown table the org's compliance team fills in by
hand for v1. v1.1 (or later) will auto-populate from the
``CustomerAgent`` table; the body explicitly calls that out so
reviewers know the surface is meant to evolve.

Voice rules
-----------
No bare imperatives. "Customer" not "Hospital" / "Tenant".
"""

from __future__ import annotations

from ._common import generated_note


_TOOL_NAME = "<<REPLACE WITH AI TOOL NAME>>"
_INTENDED_USE = "<<REPLACE WITH INTENDED USE>>"
_VENDOR = "<<REPLACE WITH VENDOR>>"
_BAA_STATUS = "<<REPLACE WITH BAA STATUS>>"


def generate_ai_tool_inventory(wizard_answers, org) -> str:
    """Render the AI Tool Inventory Markdown skeleton."""
    org_name = (org.name or "Customer organization").strip() or "Customer organization"

    parts: list[str] = []
    parts.append("# AI Tool Inventory")
    parts.append("")
    parts.append(generated_note())
    parts.append("")
    parts.append(
        f"This inventory catalogs every AI tool **{org_name}** "
        "operates that touches patient data or clinical decisions. "
        "Recommended: maintain one row per distinct deployed tool; "
        "consider revisiting at least quarterly and whenever a new "
        "tool is onboarded."
    )
    parts.append("")
    parts.append(
        "_Note: this is a starting skeleton. A future release "
        "(v1.1) will auto-populate this table from the registered "
        "AI agents on your account — until then, this is a "
        "manually-maintained document._"
    )
    parts.append("")

    parts.append("## Tool inventory")
    parts.append("")
    parts.append("| Tool name | Intended use | Vendor | BAA status |")
    parts.append("| --- | --- | --- | --- |")
    parts.append(
        f"| {_TOOL_NAME} | {_INTENDED_USE} | {_VENDOR} | {_BAA_STATUS} |"
    )
    parts.append("")
    parts.append(
        "Recommended fields to capture per tool (consider extending "
        "the table above): hosting region, ePHI categories accessed, "
        "primary operator, oversight cadence, incident-response "
        "owner, and the date the most recent risk review was filed."
    )
    parts.append("")

    return "\n".join(parts)
