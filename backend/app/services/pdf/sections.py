"""Eight section renderers for the HIPAA AI Audit Trail PDF.

Each section is a pure function ``render_<name>(story, ctx) -> None`` that
appends ReportLab Platypus flowables to ``story``. No DB I/O here — all
data is read off the pre-loaded :class:`PdfContext`.

Section order (per ``policy-engine-mvp.md`` OCR checklist):

  1. ``render_cover``                  — title page
  2. ``render_scope``                  — basic scope (A2 extends)
  3. ``render_audit_controls``         — HIPAA § 164.312(b) map
  4. ``render_hitl_evidence``          — Approval counts + roles
  5. ``render_demographic_monitoring`` — Section 1557 § 92.210
  6. ``render_workforce_training``     — Customer-attested records
  7. ``render_baa_chain``              — ScribeMD → Customer BAA
  8. ``render_technical_appendix``     — chain head + verify URL

Voice rules (from CLAUDE.md): "Customer" not "Tenant"/"Hospital",
"evidence trail" not "court-admissible", full-date "Mar 15, 2026",
comma-separated numbers ("12,500"), "Consider X" / "Recommended: X"
instead of bare imperatives.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .context import PdfContext


# ── Style helpers ────────────────────────────────────────────


def _styles() -> dict[str, ParagraphStyle]:
    """Project-wide paragraph styles.

    Built once per render (cheap) so we can tweak the design without
    threading the styles dict through every section call site.
    """
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            name="VeraTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#1a1a1a"),
            spaceAfter=18,
        ),
        "subtitle": ParagraphStyle(
            name="VeraSubtitle",
            parent=base["Heading2"],
            fontName="Helvetica",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#4a4a4a"),
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            name="VeraSection",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1a1a1a"),
            spaceBefore=18,
            spaceAfter=10,
        ),
        "h3": ParagraphStyle(
            name="VeraH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#1a1a1a"),
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            name="VeraBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#2a2a2a"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            name="VeraMeta",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#6a6a6a"),
            spaceAfter=4,
        ),
        "footer_wordmark": ParagraphStyle(
            name="VeraFooterWordmark",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#9a9a9a"),
            alignment=1,  # CENTER
        ),
        "placeholder": ParagraphStyle(
            name="VeraPlaceholder",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#6a6a6a"),
            spaceAfter=8,
        ),
    }


def _full_date(d) -> str:
    """Format a date / datetime as "Mar 15, 2026".

    Project copy rule (CLAUDE.md): full-date format with year, never the
    abbreviated "Mar 15".
    """
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%b %d, %Y")


def _full_dt(dt) -> str:
    """Format a datetime as "Mar 15, 2026 at 14:32 UTC"."""
    if dt is None:
        return "—"
    return dt.strftime("%b %d, %Y at %H:%M UTC")


def _comma_int(n: int) -> str:
    """Format integer with thousands separator per copy rules.

    "12,500" not "12500"; no abbreviation under 10K ("9,500" not "9.5K").
    """
    return f"{int(n):,}"


def _short_hash(h: Optional[str], n: int = 12) -> str:
    if not h:
        return "—"
    if len(h) <= n:
        return h
    return f"{h[:n]}…"


def _table_style_default() -> TableStyle:
    """The grey-header / thin-grid look used by every table in the doc."""
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ececec")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )


# ── Section 1: Cover ─────────────────────────────────────────


def render_cover(story: list, ctx: PdfContext) -> None:
    """Title page: HIPAA AI Audit Trail + Customer + date range.

    A1 ships a neutral cover. A3 will swap in the white-label cover
    pulled from ``Organization.logo_url`` when ``branding == "customer"``.
    """
    s = _styles()
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("HIPAA AI Audit Trail", s["title"]))
    customer_name = ctx.customer.display_name or ctx.customer.tenant_id
    story.append(Paragraph(f"Customer: {customer_name}", s["subtitle"]))
    story.append(
        Paragraph(
            f"Reporting period: {_full_date(ctx.date_from)} "
            f"– {_full_date(ctx.date_to)}",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            f"Generated: {_full_dt(ctx.generated_at)}",
            s["meta"],
        )
    )

    story.append(Spacer(1, 0.5 * inch))
    story.append(
        Paragraph(
            "This document is an evidence trail prepared from "
            "chain-anchored runtime records. Each section maps a "
            "regulatory requirement to the underlying chain-of-custody "
            "data.",
            s["body"],
        )
    )

    # Footer wordmark — small, low-emphasis. A3 may swap this for the
    # Customer's logo when ``branding == "customer"`` and a logo URL is
    # configured.
    story.append(Spacer(1, 3.5 * inch))
    story.append(Paragraph("Generated by Vera", s["footer_wordmark"]))
    story.append(PageBreak())


# ── Section 2: Scope (AI Coverage Matrix + Merkle proof reference) ───


def _check(value: bool) -> str:
    """Render the ✓ / ✗ glyphs used by the Coverage Matrix table.

    Helvetica ships these as basic Latin-1 / WGL4 glyphs so ReportLab
    embeds them without falling back to a missing-glyph box. Tests
    extract them via pypdf and assert on the surrounding text — not on
    the glyph itself — so the visual rendering is decoupled from the
    test assertion.
    """
    return "✓" if value else "✗"


def render_scope(story: list, ctx: PdfContext) -> None:
    """Scope page with the AI Coverage Matrix + Merkle proof reference.

    Renders, in order:

      1. The orientation sentence (Customer + date range).
      2. The AI Coverage Matrix table — one row per CustomerAgent,
         columns: Agent type, Detected, Vera coverage, Capture,
         HITL gates, PDF included, Posture included.
      3. The blunt scope line in red so a reader can't miss what is
         *not* covered by this packet.
      4. The Merkle proof reference sentence pointing at the
         ``vera verify --merkle-proof`` CLI for offline validation.

    All data is read off ``ctx`` — ``build_context`` did the SQL.
    """
    s = _styles()
    story.append(Paragraph("Scope", s["section"]))
    customer_name = ctx.customer.display_name or ctx.customer.tenant_id

    # (a) Orientation sentence.
    story.append(
        Paragraph(
            f"AI-driven decisions captured for {customer_name} between "
            f"{_full_date(ctx.date_from)} and {_full_date(ctx.date_to)}.",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            f"Records captured in this period: "
            f"{_comma_int(ctx.action_record_count)}.",
            s["body"],
        )
    )

    # (b) AI Coverage Matrix table.
    story.append(Paragraph("AI coverage matrix", s["h3"]))
    if not ctx.coverage_matrix:
        story.append(
            Paragraph(
                "No AI agents detected for this Customer yet.",
                s["placeholder"],
            )
        )
    else:
        header = [
            "Agent type",
            "Detected",
            "Vera coverage",
            "Capture",
            "HITL gates",
            "PDF included",
            "Posture included",
        ]
        rows: list[list[object]] = [header]
        # Use Paragraphs in the HITL-gates column so long lists wrap
        # inside the cell rather than overflow horizontally.
        for row in ctx.coverage_matrix:
            gates_text = ", ".join(row["hitl_gates"]) if row["hitl_gates"] else ""
            rows.append(
                [
                    row["agent_type"],
                    _check(row["detected"]),
                    _check(row["covered"]),
                    _check(row["captured_count"] > 0),
                    Paragraph(gates_text, s["body"]) if gates_text else "",
                    _check(row["pdf_included"]),
                    _check(row["posture_included"]),
                ]
            )
        table = Table(
            rows,
            colWidths=[
                1.1 * inch,  # agent type
                0.6 * inch,  # detected
                0.8 * inch,  # vera coverage
                0.6 * inch,  # capture
                1.6 * inch,  # HITL gates (wraps)
                0.7 * inch,  # PDF included
                0.8 * inch,  # posture included
            ],
        )
        table.setStyle(_table_style_default())
        story.append(table)

    # (c) Blunt scope line — directly under the table, red ink so a
    # regulator scanning the page sees the uncovered list at a glance.
    blunt_line = _build_blunt_scope_line(ctx)
    story.append(Spacer(1, 6))
    blunt_style = ParagraphStyle(
        name="VeraBluntScope",
        parent=s["body"],
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#a40000"),
        spaceAfter=10,
    )
    story.append(Paragraph(blunt_line, blunt_style))

    # (d) Merkle proof reference sentence.
    story.append(Paragraph("Merkle inclusion proofs", s["h3"]))
    story.append(Paragraph(_build_merkle_reference_sentence(ctx), s["body"]))


def _build_blunt_scope_line(ctx: PdfContext) -> str:
    """Return the red-ink "what this PDF does not cover" sentence.

    Three cases (matches the PR brief):
      * No CustomerAgents → "No covered AI workflows in this date range."
      * All detected agents are covered → inclusive sentence.
      * Partial coverage → uncovered list called out explicitly.
    """
    if not ctx.coverage_matrix:
        return "No covered AI workflows in this date range."

    covered = [r["agent_type"] for r in ctx.coverage_matrix if r["covered"]]
    uncovered = [
        r["agent_type"] for r in ctx.coverage_matrix if not r["covered"]
    ]
    if covered and not uncovered:
        return (
            "This evidence covers all detected AI workflows: "
            f"{', '.join(covered)}."
        )
    if not covered and uncovered:
        return (
            "No covered AI workflows in this date range. Detected "
            f"agents: {', '.join(uncovered)}."
        )
    # Partial coverage.
    return (
        f"This evidence covers {', '.join(covered)} only. "
        f"{', '.join(uncovered)} are excluded from this audit packet."
    )


def _build_merkle_reference_sentence(ctx: PdfContext) -> str:
    """Return the Scope-page Merkle proof CLI reference sentence.

    The sentence cites the checkpoint root hash + signed_at so a
    regulator can map any attached ``proof-*.json`` back to the
    sealing checkpoint without rummaging through the Technical
    Appendix. Per the PR brief: if there is NO checkpoint sealing
    any record in this packet yet, surface "Checkpoint pending".
    We branch on ``merkle_attachments`` (not on the existence of a
    historical checkpoint elsewhere in time) so the citation always
    matches the proofs actually shipped with the PDF.
    """
    cp = ctx.checkpoint_for_range or ctx.latest_checkpoint
    if (
        cp is None
        or not cp.merkle_root
        or not ctx.merkle_attachments
    ):
        return (
            "Checkpoint pending — proofs will become available after "
            "the next checkpoint cadence."
        )
    root_short = (cp.merkle_root or "")[:12]
    signed_at = _full_dt(cp.created_at)
    return (
        "Each captured decision in this evidence packet has an attached "
        "Merkle inclusion proof verifiable against checkpoint root "
        f"{root_short} (anchored at {signed_at}). Run "
        "vera verify --merkle-proof &lt;proof.json&gt; to validate any "
        "single record offline."
    )


# ── Section 3: Audit Controls (HIPAA § 164.312(b)) ───────────


def render_audit_controls(story: list, ctx: PdfContext) -> None:
    """HIPAA § 164.312(b) requirement-to-implementation map.

    Static content; pulled from Customer's BAA scope metadata where
    available. The body of the section is the same across customers in
    v1 because the implementation is the same — what varies is the
    chain head + checkpoint root cited at the end (covered in the
    Technical Appendix).
    """
    s = _styles()
    story.append(Paragraph("Audit Controls — HIPAA § 164.312(b)", s["section"]))
    story.append(
        Paragraph(
            "§ 164.312(b) requires covered entities and business "
            "associates to implement hardware, software, and procedural "
            "mechanisms that record and examine activity in information "
            "systems that contain or use ePHI.",
            s["body"],
        )
    )

    rows = [
        ["Requirement", "Vera Implementation"],
        [
            "Activity recording",
            "Every AI-driven decision is committed as an "
            "ActionRecord row chained to its predecessor via "
            "SHA-256. The previous_hash + record_hash columns "
            "form an append-only chain.",
        ],
        [
            "Tamper evidence",
            "Periodic Checkpoints seal the chain head with a "
            "KMS-issued signature and a Merkle root of all "
            "records sealed in the interval.",
        ],
        [
            "Activity examination",
            "Customer admins read the chain via the dashboard "
            "and SDK; Vera staff reads write a row to "
            "staff_audit_log so the Customer sees who looked at "
            "what.",
        ],
        [
            "Authentication of activity origin",
            "ActionRecord.authorized_by + delegation_chain "
            "capture the upstream caller; the chain hash binds "
            "those fields cryptographically.",
        ],
        [
            "Retention",
            "Customer-owned S3 mirror with Object Lock "
            "(COMPLIANCE mode, 7-year retention) when configured "
            "via the Off-Vera mirror onboarding flow.",
        ],
    ]
    table = Table(rows, colWidths=[1.7 * inch, 4.3 * inch])
    table.setStyle(_table_style_default())
    story.append(table)


# ── Section 4: HITL Evidence ─────────────────────────────────


def render_hitl_evidence(story: list, ctx: PdfContext) -> None:
    """Approval counts + reviewer-role breakdown for the period."""
    s = _styles()
    story.append(Paragraph("Human-in-the-Loop Evidence", s["section"]))
    story.append(
        Paragraph(
            f"Decisions captured: {_comma_int(ctx.action_record_count)}",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            f"HITL events triggered: {_comma_int(ctx.approval_count)}",
            s["body"],
        )
    )

    if ctx.approval_count == 0:
        story.append(
            Paragraph(
                "No HITL events recorded in this period.",
                s["placeholder"],
            )
        )
        return

    # Status breakdown
    story.append(Paragraph("HITL outcomes", s["h3"]))
    status_rows = [["Status", "Count"]]
    for status in ("pending", "approved", "rejected", "expired", "cancelled"):
        if status in ctx.hitl_count_by_status:
            status_rows.append(
                [status, _comma_int(ctx.hitl_count_by_status[status])]
            )
    if len(status_rows) > 1:
        table = Table(status_rows, colWidths=[2.5 * inch, 1.5 * inch])
        table.setStyle(_table_style_default())
        story.append(table)
        story.append(Spacer(1, 8))

    # Reviewer role breakdown
    if ctx.reviewer_role_breakdown:
        story.append(Paragraph("Reviewer roles", s["h3"]))
        role_rows = [["Role", "Count"]]
        for role, cnt in sorted(
            ctx.reviewer_role_breakdown.items(),
            key=lambda kv: (-kv[1], kv[0]),
        ):
            role_rows.append([role, _comma_int(cnt)])
        table = Table(role_rows, colWidths=[2.5 * inch, 1.5 * inch])
        table.setStyle(_table_style_default())
        story.append(table)

    if ctx.approvals_truncated_above is not None:
        story.append(
            Paragraph(
                f"Note: per-row detail truncated to the first "
                f"{_comma_int(ctx.approvals_truncated_above)} HITL "
                f"events. Aggregate counts above are over the full "
                f"period.",
                s["meta"],
            )
        )


# ── Section 5: Demographic Monitoring (§ 92.210) ─────────────


def render_demographic_monitoring(story: list, ctx: PdfContext) -> None:
    """Section 1557 § 92.210 monitoring: aggregate gate firings."""
    s = _styles()
    story.append(
        Paragraph(
            "Demographic Monitoring — Section 1557 § 92.210",
            s["section"],
        )
    )
    story.append(
        Paragraph(
            "§ 92.210 requires recipients to monitor patient-care "
            "decision-support tools for discriminatory outputs on the "
            "basis of race, color, national origin, sex, age, or "
            "disability.",
            s["body"],
        )
    )

    if not ctx.demographic_data_captured:
        story.append(
            Paragraph(
                "Demographic data not captured for this Customer's "
                "workflow. § 92.210 monitoring is not applicable in "
                "this period.",
                s["placeholder"],
            )
        )
        return

    rows = [["Gate", "Firings"]]
    for gate_name, cnt in sorted(
        ctx.gate_firings_by_gate_name.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        rows.append([gate_name, _comma_int(cnt)])
    if len(rows) > 1:
        table = Table(rows, colWidths=[3.0 * inch, 1.5 * inch])
        table.setStyle(_table_style_default())
        story.append(table)
    else:
        story.append(
            Paragraph(
                "No demographic gate firings recorded in this period.",
                s["placeholder"],
            )
        )


# ── Section 6: Workforce Training (§ 164.308(a)(5)) ─────────


def render_workforce_training(story: list, ctx: PdfContext) -> None:
    """Customer-attested workforce training records."""
    s = _styles()
    story.append(Paragraph("Workforce Training", s["section"]))
    story.append(
        Paragraph(
            "§ 164.308(a)(5) requires implementation of a security "
            "awareness and training program. Records below are "
            "customer-attested.",
            s["body"],
        )
    )

    if not ctx.workforce_training_attestations:
        story.append(
            Paragraph(
                "No workforce training attestations recorded.",
                s["placeholder"],
            )
        )
        return

    rows = [["Program", "Attested by", "Date"]]
    for att in ctx.workforce_training_attestations:
        rows.append(
            [
                str(att.get("program", "—")),
                str(att.get("attested_by", "—")),
                _full_date(att.get("attested_at")) if att.get("attested_at") else "—",
            ]
        )
    table = Table(rows, colWidths=[2.5 * inch, 2.0 * inch, 1.5 * inch])
    table.setStyle(_table_style_default())
    story.append(table)


# ── Section 7: BAA Chain ─────────────────────────────────────


def render_baa_chain(story: list, ctx: PdfContext) -> None:
    """BAA chain: ScribeMD → Customer signed BAA."""
    s = _styles()
    story.append(Paragraph("Business Associate Agreement Chain", s["section"]))
    story.append(
        Paragraph(
            f"Signed BAA between {ctx.org.name} and "
            f"{ctx.customer.display_name or ctx.customer.tenant_id}.",
            s["body"],
        )
    )

    if not ctx.baa_agreements:
        story.append(
            Paragraph(
                "No BAA on file for this Customer.",
                s["placeholder"],
            )
        )
        return

    rows = [
        [
            "Status",
            "Signed",
            "Effective",
            "Expires",
            "Scope",
        ]
    ]
    # Group scopes by agreement so we can summarise per row.
    scopes_by_agreement: dict[str, list] = {}
    for scope in ctx.baa_scopes:
        scopes_by_agreement.setdefault(scope.baa_agreement_id, []).append(
            scope
        )

    for agreement in ctx.baa_agreements:
        scope_list = scopes_by_agreement.get(agreement.id, [])
        if not scope_list:
            scope_label = "—"
        elif any(getattr(scope, "is_unrestricted", False) for scope in scope_list):
            scope_label = "Unrestricted"
        else:
            # Summarise the most-recent scope's covered_services.
            services = scope_list[0].covered_services or []
            scope_label = ", ".join(services) if services else "—"
        rows.append(
            [
                agreement.status,
                _full_date(agreement.signed_at),
                _full_date(agreement.effective_at),
                _full_date(agreement.expires_at),
                scope_label,
            ]
        )
    table = Table(
        rows,
        colWidths=[
            0.9 * inch,
            1.1 * inch,
            1.1 * inch,
            1.1 * inch,
            1.8 * inch,
        ],
    )
    table.setStyle(_table_style_default())
    story.append(table)


# ── Section 8: Technical Appendix ────────────────────────────


def render_technical_appendix(story: list, ctx: PdfContext) -> None:
    """Vera-only section: chain head + latest checkpoint + verify URL."""
    s = _styles()
    story.append(Paragraph("Technical Appendix", s["section"]))
    story.append(
        Paragraph(
            "Chain-of-custody material for independent verification.",
            s["body"],
        )
    )

    chain_head_hash = (
        ctx.chain_state.latest_hash if ctx.chain_state else None
    )
    chain_sequence = (
        ctx.chain_state.latest_sequence if ctx.chain_state else 0
    )

    # Use Paragraph for hash cells so ReportLab wraps the 64-char SHA-256
    # string across lines inside the table cell rather than overflowing.
    # The full hash MUST appear here — truncated hashes are useless for
    # regulator verification.
    s_body = s["body"]

    def _hash_paragraph(value: Optional[str]) -> Paragraph | str:
        if not value:
            return "—"
        return Paragraph(f'<font face="Courier" size="8">{value}</font>', s_body)

    rows = [
        ["Field", "Value"],
        ["Chain head sequence", _comma_int(chain_sequence)],
        ["Chain head hash", _hash_paragraph(chain_head_hash)],
    ]
    if ctx.latest_checkpoint is not None:
        cp = ctx.latest_checkpoint
        rows.extend(
            [
                ["Latest checkpoint id", cp.id or "—"],
                [
                    "Checkpoint sealed at",
                    _full_dt(cp.created_at),
                ],
                [
                    "Checkpoint Merkle root",
                    _hash_paragraph(cp.merkle_root),
                ],
                ["KMS key id", cp.key_id or "—"],
            ]
        )
    else:
        rows.append(["Latest checkpoint", "No checkpoint sealed yet"])
    # Verify URL — short chain head suffix lets a regulator paste into
    # verify.vera.io without leaking the full hash on the address bar.
    short = (chain_head_hash[:12] if chain_head_hash else "—")
    rows.append(["Verify URL", f"verify.vera.io/{short}"])
    table = Table(rows, colWidths=[2.0 * inch, 4.0 * inch])
    table.setStyle(_table_style_default())
    story.append(table)

    # A2: surface pending-proof records. These ActionRecords live in the
    # current uncheckpointed tail window, so we can't ship a Merkle proof
    # for them in this packet. Tell the reader honestly rather than
    # silently dropping the attachment.
    if ctx.pending_proof_record_ids:
        story.append(Spacer(1, 0.15 * inch))
        count = len(ctx.pending_proof_record_ids)
        plural = "record" if count == 1 else "records"
        story.append(
            Paragraph(
                f"{_comma_int(count)} {plural} in this packet "
                "are not yet checkpointed; re-generate this PDF after the "
                "next checkpoint cadence to include their proofs.",
                s["meta"],
            )
        )

    # A2: count of Merkle proof attachments embedded in this PDF. Helps a
    # regulator confirm "this PDF contains N proof.json files" before
    # opening Acrobat's attachments pane.
    if ctx.merkle_attachments:
        story.append(
            Paragraph(
                f"This PDF carries {_comma_int(len(ctx.merkle_attachments))} "
                "Merkle inclusion proof attachment(s); extract them with "
                "Acrobat / Preview's attachments pane.",
                s["meta"],
            )
        )

    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "Generated by Vera. Chain hashes and signatures are "
            "reproducible from the customer-owned S3 mirror.",
            s["footer_wordmark"],
        )
    )


# Public registry. Keys map 1:1 to the ``sections`` request body field.
SECTION_RENDERERS = {
    "cover": render_cover,
    "scope": render_scope,
    "audit_controls": render_audit_controls,
    "hitl_evidence": render_hitl_evidence,
    "demographic_monitoring": render_demographic_monitoring,
    "workforce_training": render_workforce_training,
    "baa_chain": render_baa_chain,
    "technical_appendix": render_technical_appendix,
}

# Default ordering — matches the OCR checklist in policy-engine-mvp.md.
DEFAULT_SECTION_ORDER: tuple[str, ...] = (
    "cover",
    "scope",
    "audit_controls",
    "hitl_evidence",
    "demographic_monitoring",
    "workforce_training",
    "baa_chain",
    "technical_appendix",
)
