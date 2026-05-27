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

import io
import logging
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .context import PdfContext

logger = logging.getLogger("vera.pdf.sections")


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


# Cached ParagraphStyle objects for table cells. ReportLab is fine with
# style reuse across cells of the same kind, and building these once at
# import time saves a per-render allocation for every cell in every
# table. The styles inherit ``BodyText`` defaults (margins, alignment)
# from the sample stylesheet but pin the font + size so the on-page
# rendering matches the rest of the document.
_BASE_STYLES = getSampleStyleSheet()


def _table_cell_style(*, bold: bool = False, size: int = 10) -> ParagraphStyle:
    """Paragraph style for table cells with word-wrap enabled.

    Wrapping in a ``Paragraph`` (instead of passing a raw ``str`` to
    the cell) is what unlocks ReportLab's word-wrap inside ``Table``
    cells. Plain strings render on a single line and clip at the cell
    edge — see the hotfix for the Coverage Matrix header collisions
    and the Audit Controls right-column truncation.
    """
    return ParagraphStyle(
        name=f"VeraCell_{'bold' if bold else 'body'}_{size}",
        parent=_BASE_STYLES["BodyText"],
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size + 2,
        spaceBefore=0,
        spaceAfter=0,
        textColor=colors.HexColor("#1a1a1a") if bold else colors.HexColor("#2a2a2a"),
    )


_TABLE_HEADER_CELL_STYLE = _table_cell_style(bold=True, size=9)
_TABLE_BODY_CELL_STYLE = _table_cell_style(bold=False, size=9)
_TABLE_BODY_CELL_STYLE_10 = _table_cell_style(bold=False, size=10)


def _escape_markup(value: str) -> str:
    """Escape ReportLab Paragraph markup metacharacters.

    Paragraph treats ``<``, ``>``, and ``&`` as the start of intra-
    paragraph markup (``<b>`` / ``<font>`` / ``&amp;``). When a
    user-controlled string (e.g. ``agent_type`` auto-discovered from
    an SDK caller's ``action_class``, or ``gate_name`` from an
    Approval row) contains any of those characters, Paragraph's
    parser raises ``ValueError`` and 500s the audit PDF endpoint.

    Escape unconditionally; the cell content is plain text and never
    relies on inline markup. ``&`` is escaped first so we don't
    double-escape the ampersands we just emitted.
    """
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ── Section 1: Cover ─────────────────────────────────────────
#
# Phase 4 Wave 2 PR A3 — white-label cover. Three branches:
#
#   1. ``branding == "customer"`` + ``logo_bytes`` set: render the
#      Customer's logo at the top of the cover, sized to ≤ 2" wide
#      preserving aspect ratio, *left-aligned*. The accent colour
#      (``accent_color_hex`` or the project default) drives the title
#      underline rule. Customer name in display size below the logo.
#
#   2. ``branding == "customer"`` + ``logo_bytes is None``: render a
#      neutral monochrome wordmark of the Customer name (no logo). No
#      accent colour — falls back to the project default underline grey.
#
#   3. ``branding == "vera-neutral"``: render a small "Generated by Vera"
#      wordmark at the top + Customer name in the body. No Customer
#      logo, no accent colour. The footer wordmark is also rendered so
#      the cover is unambiguously a Vera artifact.
#
# Logos are pre-loaded into ``ctx.logo_bytes`` in :func:`build_context`
# so this renderer is fully synchronous — ReportLab's layout engine
# can't ``await`` and we MUST NOT block on I/O inside it.

# Max logo render width on the cover. 2" leaves plenty of breathing
# room on the standard 8.5×11" page and matches the dashboard's "small
# enough to look like a header logo, not a hero image" intent.
_LOGO_MAX_WIDTH_INCH = 2.0
_LOGO_MAX_HEIGHT_INCH = 1.0

# Project default underline / decoration colour when the Customer
# hasn't configured an accent. Matches the body-text grey already in
# use across the document.
_DEFAULT_ACCENT_HEX = "#1a1a1a"


def _accent_color(ctx: PdfContext) -> colors.Color:
    """Resolve the cover's accent colour.

    Reads ``ctx.accent_color_hex`` (already validated as ``#RRGGBB`` at
    upload time) and falls back to ``_DEFAULT_ACCENT_HEX``. Wrapped in a
    helper so a future cover redesign can swap colour resolution in
    one place.
    """
    hex_value = ctx.accent_color_hex or _DEFAULT_ACCENT_HEX
    try:
        return colors.HexColor(hex_value)
    except (ValueError, AttributeError):
        # Defensive: a malformed stored value (e.g. legacy row pre-
        # validation) shouldn't crash the render. Fall back to default.
        logger.warning(
            "Invalid accent_color_hex on org=%s: %r; using default",
            getattr(ctx.org, "id", "?"),
            hex_value,
        )
        return colors.HexColor(_DEFAULT_ACCENT_HEX)


def _build_logo_flowable(ctx: PdfContext):
    """Convert ``ctx.logo_bytes`` to a ReportLab flowable sized to fit.

    Returns ``None`` on any decode error — the cover renderer falls
    back to the wordmark variant in that case. We deliberately do NOT
    re-raise: a corrupted logo blob should degrade the cover, not 500
    the audit-PDF endpoint.

    PNG path uses ``ImageReader`` for fast header parse + intrinsic
    size, then wraps the bytes in a Platypus ``Image`` flowable scaled
    to ``_LOGO_MAX_WIDTH_INCH`` × ``_LOGO_MAX_HEIGHT_INCH`` preserving
    aspect ratio.

    SVG path uses ``svglib.svglib.svg2rlg`` to turn the SVG into a
    ReportLab ``Drawing``, then scales the drawing so the larger
    dimension hits the max. Lazy-imported so a test environment
    without svglib (e.g. a minimal sandbox) doesn't crash at module
    load.
    """
    if not ctx.logo_bytes:
        return None

    max_w = _LOGO_MAX_WIDTH_INCH * inch
    max_h = _LOGO_MAX_HEIGHT_INCH * inch

    if ctx.logo_mime == "image/png":
        try:
            reader = ImageReader(io.BytesIO(ctx.logo_bytes))
            iw, ih = reader.getSize()
            if iw <= 0 or ih <= 0:
                return None
            scale = min(max_w / iw, max_h / ih, 1.0)
            return Image(
                io.BytesIO(ctx.logo_bytes),
                width=iw * scale,
                height=ih * scale,
                hAlign="LEFT",
            )
        except Exception:
            logger.warning(
                "Failed to decode PNG logo for org=%s; falling back to "
                "wordmark cover",
                getattr(ctx.org, "id", "?"),
                exc_info=True,
            )
            return None

    if ctx.logo_mime == "image/svg+xml":
        try:
            from svglib.svglib import svg2rlg  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "svglib not available; SVG logo for org=%s will fall "
                "back to wordmark",
                getattr(ctx.org, "id", "?"),
            )
            return None
        try:
            drawing = svg2rlg(io.BytesIO(ctx.logo_bytes))
            if drawing is None:
                return None
            dw = float(drawing.width or 0)
            dh = float(drawing.height or 0)
            if dw <= 0 or dh <= 0:
                return None
            scale = min(max_w / dw, max_h / dh, 1.0)
            drawing.width = dw * scale
            drawing.height = dh * scale
            drawing.scale(scale, scale)
            drawing.hAlign = "LEFT"
            return drawing
        except Exception:
            logger.warning(
                "Failed to decode SVG logo for org=%s; falling back to "
                "wordmark cover",
                getattr(ctx.org, "id", "?"),
                exc_info=True,
            )
            return None

    # Unknown MIME — treat as no logo.
    return None


def _title_with_accent(title: str, accent: colors.Color) -> Table:
    """Render the title + a 1-row underline coloured by the accent.

    Implemented as a 2-row Table with a coloured LINEBELOW so the
    underline tracks the title width and survives multi-line wraps.
    Falls into Platypus' flow naturally — no manual canvas drawing.
    """
    title_style = ParagraphStyle(
        name="VeraCoverTitle",
        fontName="Helvetica-Bold",
        fontSize=28,
        leading=32,
        textColor=colors.HexColor("#1a1a1a"),
        spaceAfter=0,
    )
    para = Paragraph(title, title_style)
    table = Table([[para]], colWidths=[6.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 2.5, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def render_cover(story: list, ctx: PdfContext) -> None:
    """Title page.

    Three branches keyed on ``ctx.branding`` + presence of an uploaded
    logo. See module-top comment for the full decision matrix.
    """
    s = _styles()
    customer_name = ctx.customer.display_name or ctx.customer.tenant_id
    is_customer_branding = ctx.branding == "customer"
    logo_flowable = (
        _build_logo_flowable(ctx) if is_customer_branding else None
    )
    # Accent colour is *only* applied when we're in the Customer-branded
    # path AND a logo was successfully rendered. The "Customer
    # branding, no logo" fallback uses the neutral default so an org
    # that uploaded an accent without a logo doesn't get a half-branded
    # cover. The "vera-neutral" path always uses the default.
    accent = (
        _accent_color(ctx)
        if is_customer_branding and logo_flowable is not None
        else colors.HexColor(_DEFAULT_ACCENT_HEX)
    )

    # ── Top-of-page block ────────────────────────────────────
    story.append(Spacer(1, 0.75 * inch))
    if is_customer_branding:
        if logo_flowable is not None:
            # Branch 1: Customer logo + accent-coloured title rule.
            story.append(logo_flowable)
            story.append(Spacer(1, 0.4 * inch))
        # Branch 2 falls through with no logo flowable — the wordmark
        # of the Customer name renders below the title block.
    else:
        # Branch 3: ``vera-neutral`` — render a small Vera wordmark at
        # the top so the cover is unambiguously a Vera artifact. Plain
        # paragraph so it stays cheap and accessible.
        story.append(
            Paragraph(
                "Generated by Vera",
                ParagraphStyle(
                    name="VeraCoverWordmark",
                    fontName="Helvetica-Bold",
                    fontSize=10,
                    leading=12,
                    textColor=colors.HexColor("#6a6a6a"),
                    spaceAfter=10,
                ),
            )
        )

    story.append(_title_with_accent("HIPAA AI Audit Trail", accent))
    story.append(Spacer(1, 0.15 * inch))

    # Customer name. In the "customer branding, no logo" fallback we
    # render the name *bigger* so it acts as a wordmark; otherwise the
    # standard subtitle weight is enough.
    if is_customer_branding and logo_flowable is None:
        wordmark_style = ParagraphStyle(
            name="VeraCoverCustomerWordmark",
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#1a1a1a"),
            spaceAfter=10,
        )
        story.append(Paragraph(customer_name, wordmark_style))
    else:
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

    # Footer wordmark — always present; the Vera-neutral branch makes
    # it the primary brand signal, the Customer-branded branches keep
    # it small so the artifact is still attributable to its generator
    # at a glance (regulator audit trail requirement).
    story.append(Spacer(1, 3.0 * inch))
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
        # Wrap every header label in a Paragraph so multi-word labels
        # ("Vera coverage", "PDF included", "Posture included") can
        # wrap to two lines inside their cell instead of butting up
        # against the next column when the column is narrower than the
        # rendered label width. This was Bug 1 in the hotfix brief:
        # plain strings render on a single line and visually collide
        # ("Vera coverageCapture", "PDF includePosture included").
        header_labels = [
            "Agent type",
            "Detected",
            "Vera coverage",
            "Capture",
            "HITL gates",
            "PDF included",
            "Posture included",
        ]
        header: list[object] = [
            Paragraph(label, _TABLE_HEADER_CELL_STYLE)
            for label in header_labels
        ]
        rows: list[list[object]] = [header]
        # Wrap the agent_type label and HITL-gates list in Paragraphs
        # so long agent names ("prior_auth_v2") and comma-separated
        # gate lists ("new_diagnosis, controlled_substance") reflow
        # onto multiple lines inside their cell instead of overflowing.
        # The check-mark columns stay as plain strings — single-glyph
        # cells don't need wrap behaviour.
        for row in ctx.coverage_matrix:
            # Both ``agent_type`` and the elements of ``hitl_gates``
            # originate from SDK callers (``ActionRecordCreate.action_class``
            # and ``Approval.context["gate_name"]`` respectively). They
            # are stored verbatim modulo the ORM's lower+strip normaliser
            # — they are NOT restricted to ``[a-z0-9_]``. A caller posting
            # ``"hr&admissions"`` or ``"<scribe>"`` would otherwise crash
            # the Paragraph parser. Escape before wrapping.
            agent_type_label = _escape_markup(row["agent_type"])
            gates_text = (
                ", ".join(_escape_markup(g) for g in row["hitl_gates"])
                if row["hitl_gates"]
                else ""
            )
            rows.append(
                [
                    Paragraph(agent_type_label, _TABLE_BODY_CELL_STYLE),
                    _check(row["detected"]),
                    _check(row["covered"]),
                    _check(row["captured_count"] > 0),
                    Paragraph(gates_text, _TABLE_BODY_CELL_STYLE) if gates_text else "",
                    _check(row["pdf_included"]),
                    _check(row["posture_included"]),
                ]
            )
        # Explicit column widths in points (1pt = 1/72in). Budget for
        # the seven columns sums to 500pt, fitting inside the 504pt
        # content area (8.5in page − 2×0.75in margins). ReportLab
        # shrink-to-fits on overflow, but explicit widths are what
        # let the header Paragraphs wrap predictably onto two lines.
        # Single-glyph check-mark columns (Detected / Capture) need
        # ~60pt to keep their 8-char headers on one line at 9pt bold.
        table = Table(
            rows,
            colWidths=[
                88,  # Agent type — fits "prior_auth_v2" + padding
                60,  # Detected — fits "Detected" on one line at 9pt
                72,  # Vera coverage — wraps to 2 lines
                60,  # Capture — fits "Capture" on one line
                86,  # HITL gates — wraps comma-separated lists
                62,  # PDF included — wraps to 2 lines
                72,  # Posture included — wraps to 2 lines
            ],
            repeatRows=1,
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

    # Wrap every cell in a Paragraph so the right column reflows onto
    # multiple lines instead of clipping at the page edge. This was
    # Bug 2 in the hotfix brief: ReportLab does not word-wrap plain
    # ``str`` cells, so long sentences ran off the right margin and
    # truncated mid-word ("SHA-", "all reco", "staff_a", "when configu").
    requirement_rows: list[tuple[str, str]] = [
        (
            "Activity recording",
            "Every AI-driven decision is committed as an "
            "ActionRecord row chained to its predecessor via "
            "SHA-256. The previous_hash + record_hash columns "
            "form an append-only chain.",
        ),
        (
            "Tamper evidence",
            "Periodic Checkpoints seal the chain head with a "
            "KMS-issued signature and a Merkle root of all "
            "records sealed in the interval.",
        ),
        (
            "Activity examination",
            "Customer admins read the chain via the dashboard "
            "and SDK; Vera staff reads write a row to "
            "staff_audit_log so the Customer sees who looked at "
            "what.",
        ),
        (
            "Authentication of activity origin",
            "ActionRecord.authorized_by + delegation_chain "
            "capture the upstream caller; the chain hash binds "
            "those fields cryptographically.",
        ),
        (
            "Retention",
            "Customer-owned S3 mirror with Object Lock "
            "(COMPLIANCE mode, 7-year retention) when configured "
            "via the Off-Vera mirror onboarding flow.",
        ),
    ]
    rows: list[list[object]] = [
        [
            Paragraph("Requirement", _TABLE_HEADER_CELL_STYLE),
            Paragraph("Vera Implementation", _TABLE_HEADER_CELL_STYLE),
        ]
    ]
    for label, body in requirement_rows:
        rows.append(
            [
                Paragraph(label, _TABLE_BODY_CELL_STYLE_10),
                Paragraph(body, _TABLE_BODY_CELL_STYLE_10),
            ]
        )
    # Explicit column widths in points. 140 + 328 = 468pt fits inside
    # the 504pt content area; the wider right column gives the
    # implementation text room to wrap onto 3–4 lines per row instead
    # of overflowing.
    table = Table(rows, colWidths=[140, 328], repeatRows=1)
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
