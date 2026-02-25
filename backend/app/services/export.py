"""Export service — generates CSV and PDF compliance reports.

CSV: Streaming, row-by-row generation to avoid OOM on large chains.
PDF: Buffered in memory (hard limit 5000 records — PDFs beyond that are unreadable).

Both respect the same filter parameters as the actions list endpoint.
"""

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, ChainState
from ..models.checkpoint import Checkpoint
from ..services.verification import verify_chain

logger = logging.getLogger("actionledger.export")

# ── Constants ─────────────────────────────────────────────────────────────────

_CSV_CHUNK = 500  # rows per DB fetch — mirrors verification chunk size
_PDF_MAX_RECORDS = 5000

CSV_COLUMNS = [
    "sequence_number",
    "recorded_at",
    "action_timestamp",
    "action_name",
    "action_type",
    "action_description",
    "agent_name",
    "agent_version",
    "model_id",
    "framework",
    "result",
    "duration_ms",
    "authorized_by",
    "authorization_scope",
    "target_system",
    "target_resource",
    "error_message",
    "record_hash",
    "previous_hash",
    "input_data",
    "outcome",
    "reasoning",
    "policies_applied",
    "environment",
    "metadata",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_query(org_id: str, filters: dict):
    """Build a SQLAlchemy query from filter params. Used by both CSV and PDF."""
    query = (
        select(ActionRecord)
        .where(ActionRecord.org_id == org_id)
        .order_by(ActionRecord.sequence_number.asc())
    )
    if filters.get("agent_name"):
        query = query.where(ActionRecord.agent_name == filters["agent_name"])
    if filters.get("action_type"):
        query = query.where(ActionRecord.action_type == filters["action_type"])
    if filters.get("result"):
        query = query.where(ActionRecord.result == filters["result"])
    if filters.get("start_date"):
        query = query.where(ActionRecord.action_timestamp >= filters["start_date"])
    if filters.get("end_date"):
        query = query.where(ActionRecord.action_timestamp <= filters["end_date"])
    return query


def _record_to_csv_row(record: ActionRecord) -> list:
    """Convert an ActionRecord ORM object to a list of CSV-safe values."""

    def _fmt_dt(dt) -> str:
        if dt is None:
            return ""
        if hasattr(dt, "isoformat"):
            return dt.isoformat()
        return str(dt)

    def _fmt_json(v) -> str:
        if not v:
            return ""
        try:
            return json.dumps(v, default=str)
        except Exception:
            return str(v)

    return [
        record.sequence_number,
        _fmt_dt(record.recorded_at),
        _fmt_dt(record.action_timestamp),
        record.action_name or "",
        record.action_type or "",
        record.action_description or "",
        record.agent_name or "",
        record.agent_version or "",
        record.model_id or "",
        record.framework or "",
        record.result or "",
        record.duration_ms if record.duration_ms is not None else "",
        record.authorized_by or "",
        record.authorization_scope or "",
        record.target_system or "",
        record.target_resource or "",
        record.error_message or "",
        record.record_hash or "",
        record.previous_hash or "",
        _fmt_json(record.input_data),
        _fmt_json(record.outcome),
        _fmt_json(record.reasoning),
        _fmt_json(record.policies_applied),
        _fmt_json(record.environment),
        _fmt_json(record.metadata_),
    ]


# ── CSV streaming ─────────────────────────────────────────────────────────────


async def stream_csv(
    session: AsyncSession, org_id: str, filters: dict
) -> AsyncGenerator[str, None]:
    """Async generator that yields CSV rows as strings.

    Usage (in route):
        return StreamingResponse(stream_csv(session, org_id, filters),
                                 media_type="text/csv")
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row
    writer.writerow(CSV_COLUMNS)
    yield buf.getvalue()
    buf.truncate(0)
    buf.seek(0)

    # Data rows — chunked to avoid OOM
    query = _build_query(org_id, filters)
    if filters.get("limit"):
        query = query.limit(min(int(filters["limit"]), 10_000))

    offset = 0
    while True:
        chunk_query = query.limit(_CSV_CHUNK).offset(offset)
        result = await session.execute(chunk_query)
        records = result.scalars().all()

        if not records:
            break

        for record in records:
            writer.writerow(_record_to_csv_row(record))

        yield buf.getvalue()
        buf.truncate(0)
        buf.seek(0)

        offset += len(records)
        session.expire_all()  # free memory between chunks

        if len(records) < _CSV_CHUNK:
            break  # last partial chunk — done


# ── PDF generation ────────────────────────────────────────────────────────────


async def generate_pdf(
    session: AsyncSession, org_id: str, filters: dict
) -> bytes:
    """Generate a compliance report PDF and return its bytes.

    Structure:
      1. Report header (title, org, export timestamp, filters applied)
      2. Chain integrity status (live verification)
      3. Checkpoints table
      4. Action records table (capped at PDF_MAX_RECORDS)
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError(
            "fpdf2 is required for PDF export. Install with: pip install fpdf2"
        )

    now = datetime.now(timezone.utc)

    # ── Collect data ──────────────────────────────────────────────────────────

    # 1. Chain verification (live)
    chain_result = await verify_chain(session, org_id)

    # 2. Checkpoints
    cp_result = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(Checkpoint.created_at.desc())
        .limit(20)  # show latest 20 in PDF
    )
    checkpoints = list(cp_result.scalars().all())

    # 3. Action records (capped)
    query = _build_query(org_id, filters).limit(_PDF_MAX_RECORDS)
    ar_result = await session.execute(query)
    records = list(ar_result.scalars().all())

    total_records = len(records)

    # ── Build PDF ─────────────────────────────────────────────────────────────

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Page 1: Header ────────────────────────────────────────────────────────

    # Title
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Action Ledger", ln=True)

    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "Compliance Audit Report", ln=True)

    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # Metadata block
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)

    def _meta_row(label: str, value: str):
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(42, 6, label + ":", ln=False)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, value, ln=True)

    _meta_row("Organization ID", org_id)
    _meta_row("Generated at", now.strftime("%Y-%m-%d %H:%M:%S UTC"))

    # Filters applied
    filter_parts = []
    if filters.get("start_date"):
        filter_parts.append(f"from {filters['start_date']}")
    if filters.get("end_date"):
        filter_parts.append(f"to {filters['end_date']}")
    if filters.get("agent_name"):
        filter_parts.append(f"agent={filters['agent_name']}")
    if filters.get("action_type"):
        filter_parts.append(f"type={filters['action_type']}")
    if filters.get("result"):
        filter_parts.append(f"result={filters['result']}")

    _meta_row("Filters", ", ".join(filter_parts) if filter_parts else "None (all records)")
    _meta_row("Records exported", f"{total_records}" + (" (PDF cap reached)" if total_records >= _PDF_MAX_RECORDS else ""))

    pdf.ln(6)

    # ── Section 1: Chain Integrity ────────────────────────────────────────────

    def _section_header(title: str):
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(0, 8, "  " + title, ln=True, fill=True)
        pdf.ln(2)

    _section_header("1. Chain Integrity")

    is_valid = chain_result.is_valid
    status_label = "VERIFIED — No tampering detected" if is_valid else f"BROKEN — First invalid sequence: {chain_result.first_invalid_sequence}"

    # Status badge (green or red)
    pdf.set_font("Helvetica", "B", 10)
    if is_valid:
        pdf.set_text_color(22, 163, 74)   # green-600
    else:
        pdf.set_text_color(220, 38, 38)   # red-600
    pdf.cell(0, 7, status_label, ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Records checked: {chain_result.records_checked}", ln=True)
    pdf.cell(0, 6, f"Message: {chain_result.message}", ln=True)

    pdf.ln(5)

    # ── Section 2: Checkpoints ────────────────────────────────────────────────

    _section_header("2. Checkpoints")

    if not checkpoints:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(130, 130, 130)
        pdf.cell(0, 6, "No checkpoints found.", ln=True)
    else:
        # Table header
        col_widths = [22, 52, 44, 50, 22]
        col_headers = ["Sequence", "Hash", "Created", "Signature", "Status"]

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(235, 235, 235)
        pdf.set_text_color(50, 50, 50)
        for header, w in zip(col_headers, col_widths):
            pdf.cell(w, 7, header, border=1, fill=True, ln=False)
        pdf.ln()

        # Table rows
        pdf.set_font("Helvetica", "", 7)
        for cp in checkpoints:
            if cp.is_valid is True:
                pdf.set_text_color(22, 163, 74)
                status_str = "Valid"
            elif cp.is_valid is False:
                pdf.set_text_color(220, 38, 38)
                status_str = "Invalid"
            else:
                pdf.set_text_color(130, 130, 130)
                status_str = "Unverified"

            pdf.set_text_color(70, 70, 70)
            created_str = cp.created_at.strftime("%Y-%m-%d %H:%M") if cp.created_at else ""
            hash_str = (cp.hash_at_checkpoint or "")[:16] + "..."
            sig_str = (cp.signature or "")[:16] + "..."

            if cp.is_valid is True:
                status_color = (22, 163, 74)
            elif cp.is_valid is False:
                status_color = (220, 38, 38)
            else:
                status_color = (130, 130, 130)

            row_values = [
                f"#{cp.sequence_at_checkpoint}",
                hash_str,
                created_str,
                sig_str,
                "",  # status drawn separately
            ]

            for i, (val, w) in enumerate(zip(row_values, col_widths)):
                if i == 4:
                    pdf.set_text_color(*status_color)
                    pdf.set_font("Helvetica", "B", 7)
                    pdf.cell(w, 6, status_str, border=1, ln=False)
                    pdf.set_font("Helvetica", "", 7)
                else:
                    pdf.set_text_color(70, 70, 70)
                    pdf.cell(w, 6, val, border=1, ln=False)
            pdf.ln()

    pdf.ln(5)

    # ── Section 3: Action Records ─────────────────────────────────────────────

    _section_header(f"3. Action Records ({total_records} shown)")

    if not records:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(130, 130, 130)
        pdf.cell(0, 6, "No records match the applied filters.", ln=True)
    else:
        # Column widths must sum to ~190 (A4 width 210 - 2*10 margins)
        col_w   = [14,  32,  38,  28,  22,  18,  18,  20]
        col_hdr = ["Seq", "Timestamp", "Action Name", "Agent", "Type", "Result", "Duration", "Hash"]

        # Table header
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(235, 235, 235)
        pdf.set_text_color(50, 50, 50)
        for header, w in zip(col_hdr, col_w):
            pdf.cell(w, 7, header, border=1, fill=True, ln=False)
        pdf.ln()

        # Table rows
        pdf.set_font("Helvetica", "", 7)
        for record in records:
            # Format values
            ts_str = (
                record.action_timestamp.strftime("%Y-%m-%d %H:%M:%S")
                if record.action_timestamp else ""
            )
            dur_str = (
                f"{record.duration_ms}ms"
                if record.duration_ms is not None else "—"
            )
            hash_str = (record.record_hash or "")[:8] + "..."

            if record.result == "success":
                result_color = (22, 163, 74)
            elif record.result == "failure":
                result_color = (220, 38, 38)
            else:
                result_color = (100, 100, 100)

            row_values = [
                f"#{record.sequence_number}",
                ts_str,
                (record.action_name or "")[:30],
                (record.agent_name or "")[:18],
                (record.action_type or "")[:14],
                "",              # result — drawn with color
                dur_str,
                hash_str,
            ]

            for i, (val, w) in enumerate(zip(row_values, col_w)):
                if i == 5:
                    pdf.set_text_color(*result_color)
                    pdf.set_font("Helvetica", "B", 7)
                    pdf.cell(w, 5, record.result or "", border=1, ln=False)
                    pdf.set_font("Helvetica", "", 7)
                    pdf.set_text_color(70, 70, 70)
                else:
                    pdf.set_text_color(70, 70, 70)
                    pdf.cell(w, 5, val, border=1, ln=False)
            pdf.ln()

    # ── Footer (page numbers) ─────────────────────────────────────────────────

    def _footer_text():
        pdf.set_y(-12)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(160, 160, 160)
        pdf.cell(
            0, 5,
            f"Generated by Action Ledger  |  {now.strftime('%Y-%m-%d %H:%M:%S UTC')}  |  Page {{nb}}",
            align="C",
        )

    # fpdf2 page numbering — alias_nb_pages
    pdf.alias_nb_pages()

    return bytes(pdf.output())
