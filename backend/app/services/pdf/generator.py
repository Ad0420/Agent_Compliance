"""ReportLab-based PDF generator entry point.

Public entry::

    pdf_bytes = await generate_audit_pdf(
        db, org_id, customer_id,
        sections=["cover", "scope", ...],
        branding="customer",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 3, 31),
    )

ReportLab's ``SimpleDocTemplate`` builds the PDF into a ``BytesIO``
buffer; we return the bytes. The actual rendering is CPU-bound and
synchronous (ReportLab has no async API), so we run it inside
``asyncio.to_thread`` to keep the FastAPI event loop responsive and to
give us a clean place to enforce the 30 s timeout the route promises.

Timeout strategy
----------------
``asyncio.wait_for`` with a 30 s budget. On overrun, the helper raises
``PdfRenderTimeout``; the route maps it to ``HTTP 504 pdf_render_timeout``.
The background thread is left to finish in its own time (``to_thread``
doesn't support cancellation); on pilot scale (≤500 records) we never
exercise that branch, and the cost is one dead thread on a misbehaving
input — strictly preferable to crashing the worker.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import date
from typing import Iterable, Optional

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Customer, Organization
from .context import PdfContext, TooManyRecordsForPdf, build_context
from .sections import (
    DEFAULT_SECTION_ORDER,
    SECTION_RENDERERS,
)

logger = logging.getLogger("vera.pdf")


# 30 s render budget — matches the brief's promise on the synchronous
# POST /v1/audits endpoint. At pilot scale (≤500 records) a clean render
# finishes well under 1 s on a developer laptop; the 30 s ceiling is
# defense-in-depth for a pathological dataset.
DEFAULT_RENDER_TIMEOUT_SECONDS = 30.0


class PdfRenderTimeout(Exception):
    """Raised when PDF rendering exceeds the configured budget.

    Route handlers should catch this and map to ``HTTP 504`` with the
    stable ``pdf_render_timeout`` error code so the dashboard can
    surface a clean retry CTA without crashing the worker.
    """


def _validate_section_names(sections: Iterable[str]) -> list[str]:
    """Return the requested sections in the canonical order.

    Unknown section names raise ``ValueError`` — the route validates the
    request body before calling us, but we double-check here so direct
    callers (tests, scripts) get a clear error message.
    """
    requested = set(sections)
    unknown = requested - set(SECTION_RENDERERS)
    if unknown:
        raise ValueError(
            f"Unknown PDF sections: {sorted(unknown)}. "
            f"Valid sections: {sorted(SECTION_RENDERERS)}"
        )
    return [name for name in DEFAULT_SECTION_ORDER if name in requested]


def _render_to_bytes(ctx: PdfContext, sections: list[str]) -> bytes:
    """Synchronous render path. Runs inside ``asyncio.to_thread``.

    Builds the Platypus story by calling each requested section
    renderer in canonical order, asks ``SimpleDocTemplate`` to lay out
    the pages into a BytesIO buffer, and finally post-processes the
    result with pypdf to embed each Merkle proof JSON as a PDF
    attachment.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="HIPAA AI Audit Trail",
        author="Vera",
    )
    story: list = []
    for name in sections:
        renderer = SECTION_RENDERERS[name]
        renderer(story, ctx)

    doc.build(story)
    rendered = buf.getvalue()

    # A2: attach per-decision Merkle proofs. If there's nothing to
    # attach, skip the post-processing step entirely so this PR stays a
    # no-op for date ranges with zero sealed records.
    if not ctx.merkle_attachments:
        return rendered
    return _attach_proofs(rendered, ctx.merkle_attachments)


def _attach_proofs(
    pdf_bytes: bytes, attachments: list[tuple[str, dict]]
) -> bytes:
    """Embed one ``proof-*.json`` file per ActionRecord in the PDF.

    Uses ``pypdf``'s built-in ``add_attachment`` rather than introducing
    a new dependency (pikepdf). The attached files are visible in
    Acrobat → View → Show/Hide → Navigation Panes → Attachments and in
    Preview's sidebar; both surfaces let a regulator extract a
    ``proof.json`` and pipe it into ``vera verify --merkle-proof``.

    The function is CPU-bound (one full re-parse of the rendered PDF)
    but well inside the 30 s render budget — the cap is 500 records and
    a ~1 MB JSON per record, dominated by the underlying Merkle proof
    build, not the attachment step.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)
    for filename, payload in attachments:
        # ``json.dumps`` rather than carrying the raw bytes so we know
        # the on-disk encoding is deterministic UTF-8 and the JSON shape
        # is exactly the dict ``build_proof`` returned.
        writer.add_attachment(
            filename,
            json.dumps(payload, sort_keys=True).encode("utf-8"),
        )
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def generate_audit_pdf(
    session: AsyncSession,
    org: Organization,
    customer: Customer,
    *,
    date_from: date,
    date_to: date,
    sections: Optional[Iterable[str]] = None,
    branding: str = "customer",
    timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
    records_hard_cap: Optional[int] = None,
) -> bytes:
    """Render the HIPAA AI Audit Trail PDF for one Customer / date range.

    The caller passes already-resolved ORM rows for ``org`` and
    ``customer`` so this function does not re-do the IAM gate; that's the
    route handler's responsibility.

    Parameters mirror the route's request body (`date_from`, `date_to`,
    `sections`, `branding`). If ``sections`` is ``None`` we render every
    section in the canonical order — the typical PDF flow.

    ``records_hard_cap`` overrides the default per-PDF cap on the number
    of attached Merkle proofs (500 in v1). Tests lower the cap to
    exercise the 413 path without seeding 500 records; in production
    callers pass ``None`` so the module-level default holds.

    Raises:
      * ``PdfRenderTimeout`` if rendering exceeds ``timeout_seconds``.
        Route handlers map this to ``504 pdf_render_timeout``.
      * ``TooManyRecordsForPdf`` if the in-range record count exceeds
        ``records_hard_cap``. Route handlers map this to
        ``413 too_many_records_for_pdf``.
      * ``ValueError`` if an unknown section name is requested.
    """
    section_list = _validate_section_names(
        sections if sections is not None else DEFAULT_SECTION_ORDER
    )

    ctx = await build_context(
        session,
        org=org,
        customer=customer,
        date_from=date_from,
        date_to=date_to,
        branding=branding,
        records_hard_cap=records_hard_cap,
    )

    try:
        pdf_bytes: bytes = await asyncio.wait_for(
            asyncio.to_thread(_render_to_bytes, ctx, section_list),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "PDF render exceeded %.1fs budget for org=%s customer=%s "
            "date_range=%s..%s sections=%s",
            timeout_seconds,
            org.id,
            customer.id,
            date_from,
            date_to,
            section_list,
        )
        raise PdfRenderTimeout(
            f"PDF render exceeded {timeout_seconds:.0f}s budget"
        ) from exc
    return pdf_bytes
