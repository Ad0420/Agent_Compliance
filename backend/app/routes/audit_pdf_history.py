"""Generated audit PDFs history — Phase 4 Wave 2 PR C4.

Two endpoints surface and re-use the rows persisted by
``POST /v1/audits/{customer_id}`` (audits.py):

  * ``GET  /v1/customers/{customer_id}/audit-pdfs`` — paginated list,
    newest first.
  * ``POST /v1/customers/{customer_id}/audit-pdfs/{pdf_id}/regenerate``
    — re-render using the persisted parameters, return
    ``application/pdf`` bytes the same way the original POST does.

We deliberately mount these under the ``customers`` URL space rather
than ``audits`` so the read pattern matches the existing
``GET /v1/customers/{customer_id}/...`` family. The path parameter is
the Customer **primary key** (UUID) to match ``audits.py`` — distinct
from the ``tenant_id`` the SDK uses elsewhere. The Customer detail page
already has the PK in hand.

IAM
---
``read`` permission gates the list endpoint; staff Clerk sessions hit
``ctx.is_staff`` and get a redacted audit-log row written. Regenerate
requires ``write`` permission and rejects staff outright (mirrors
``audits.py``: staff cannot generate or re-render PDFs — Customer
owns the artifact).

BAA freshness
-------------
A re-download regenerates from current chain state. If the BAA has
expired since the original render we still 403 with ``baa_expired`` —
the operator must renew before any new artifact leaves the platform.
That's the regulator-readiness invariant; consistency over convenience.

No DELETE in v1
---------------
History is append-only. Customers can't strike audit-history rows from
this route — that's a feature, not a missing endpoint.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    APIKey,
    BAAAgreement,
    BAAScope,
    Customer,
    GeneratedAuditPdf,
    Organization,
)
from ..services.auth import AuthContext, require_permission_with_context
from ..services.iam import audit_staff_read
from ..services.pdf import PdfRenderTimeout, generate_audit_pdf
from ..services.pdf.sections import DEFAULT_SECTION_ORDER, SECTION_RENDERERS

logger = logging.getLogger("vera.audit_pdf_history")

router = APIRouter(prefix="/customers", tags=["audit-pdf-history"])


_VALID_SECTIONS = frozenset(SECTION_RENDERERS)
_VALID_BRANDING = frozenset({"customer", "vera-neutral"})

_LIST_ENDPOINT = "/v1/customers/{customer_id}/audit-pdfs"


# ── Response shapes ──────────────────────────────────────────────────


class GeneratedByInfo(BaseModel):
    """Identity of the operator that triggered the original render.

    Exactly one of ``user_id`` or ``api_key_id`` is populated when this
    field is non-null on the wire; the dashboard branches on which is
    set to render the right badge.
    """

    user_id: Optional[str] = None
    user_email_or_name: Optional[str] = None
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None


class AuditPdfHistoryItem(BaseModel):
    id: str
    generated_at: str  # ISO 8601 UTC
    generated_by: Optional[GeneratedByInfo] = None
    date_from: date
    date_to: date
    sections: list[str]
    branding: str
    byte_size: int


class AuditPdfHistoryResponse(BaseModel):
    items: list[AuditPdfHistoryItem]
    total: int
    limit: int
    offset: int


# ── Helpers ──────────────────────────────────────────────────────────


async def _resolve_customer_or_404(
    session: AsyncSession, *, org_id: str, customer_id: str
) -> Customer:
    """Org-scoped Customer lookup by PK — cross-org returns 404.

    Mirrors ``audits.py::_resolve_customer_or_404`` so the two routes
    behave identically on missing / cross-org access.
    """
    result = await session.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


async def _is_baa_active_for_customer(
    session: AsyncSession, *, customer_id: str, now: datetime
) -> bool:
    """Same EXISTS query as ``audits.py`` — kept local to avoid coupling."""
    stmt = (
        select(BAAAgreement.id)
        .join(BAAScope, BAAScope.baa_agreement_id == BAAAgreement.id)
        .where(
            BAAAgreement.customer_id == customer_id,
            BAAAgreement.status == "active",
            (BAAAgreement.effective_at.is_(None))
            | (BAAAgreement.effective_at <= now),
            (BAAAgreement.expires_at.is_(None))
            | (BAAAgreement.expires_at > now),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


def _format_iso_utc(dt: datetime) -> str:
    """ISO 8601 with explicit UTC ``Z`` suffix.

    The DB stores naive UTC datetimes (post-Wave-3A convention); we
    surface them with the ``Z`` suffix so the dashboard's Date parser
    treats them as UTC unambiguously.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _resolve_generated_by(
    session: AsyncSession,
    row: GeneratedAuditPdf,
) -> Optional[GeneratedByInfo]:
    """Best-effort denormalisation of who triggered the render.

    For API-key rows we look up the APIKey name (cheap, indexed by PK).
    For user_id rows we surface the raw id today; a future PR can wire
    in a Clerk REST lookup to map ``user_id → email/full_name``. The
    dashboard renders the id as a tooltip-only fallback when the
    resolved label is missing.
    """
    if row.generated_by_api_key_id:
        key = await session.get(APIKey, row.generated_by_api_key_id)
        return GeneratedByInfo(
            api_key_id=row.generated_by_api_key_id,
            api_key_name=key.name if key is not None else None,
        )
    if row.generated_by_user_id:
        # Clerk lookup not wired in this PR — surface the raw id only.
        # The dashboard tooltip will show the id; a follow-up can map
        # to email/name via ``services/clerk_reconcile.py``.
        return GeneratedByInfo(
            user_id=row.generated_by_user_id,
            user_email_or_name=None,
        )
    return None


def _safe_filename(tenant_id: str, date_to: date) -> str:
    """Same filename convention as ``audits.py``."""
    safe = tenant_id or "audit"
    return f"audit-{safe}-{date_to.isoformat()}.pdf"


# ── GET — list history ───────────────────────────────────────────────


@router.get(
    "/{customer_id}/audit-pdfs",
    response_model=AuditPdfHistoryResponse,
    name="list_audit_pdf_history",
)
async def list_audit_pdf_history(
    customer_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> AuditPdfHistoryResponse:
    """List a Customer's audit PDF history, newest first.

    * Customer admin (Clerk OR API key) sees their own org only.
    * Vera staff: ``X-Org-Id``-pinned read with a ``staff_audit_log``
      row written. The PDF history surface is metadata-only (date range,
      section list, byte size) — no PHI redaction needed because no PHI
      is on the response.
    * Cross-org → 404.
    """
    customer = await _resolve_customer_or_404(
        session, org_id=ctx.org_id, customer_id=customer_id
    )

    # Total — separate count query so pagination is correct even when
    # ``limit < total``. Index on ``(customer_id, generated_at)`` covers
    # both this COUNT and the windowed SELECT below.
    total_result = await session.execute(
        select(func.count(GeneratedAuditPdf.id)).where(
            GeneratedAuditPdf.customer_id == customer.id
        )
    )
    total = int(total_result.scalar_one() or 0)

    rows_result = await session.execute(
        select(GeneratedAuditPdf)
        .where(GeneratedAuditPdf.customer_id == customer.id)
        .order_by(GeneratedAuditPdf.generated_at.desc(), GeneratedAuditPdf.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(rows_result.scalars().all())

    items: list[AuditPdfHistoryItem] = []
    for row in rows:
        generated_by = await _resolve_generated_by(session, row)
        # ``sections_json`` is typed Any on the model (JSON column); the
        # write path always persists ``list[str]`` so a runtime cast is
        # safe — but we defensively coerce to ``list[str]`` here so a
        # historical row with a non-list value doesn't 500 the list.
        raw_sections = row.sections_json
        sections: list[str] = (
            [str(s) for s in raw_sections]
            if isinstance(raw_sections, list)
            else []
        )
        items.append(
            AuditPdfHistoryItem(
                id=row.id,
                generated_at=_format_iso_utc(row.generated_at),
                generated_by=generated_by,
                date_from=row.date_from,
                date_to=row.date_to,
                sections=sections,
                branding=row.branding,
                byte_size=int(row.byte_size),
            )
        )

    # Staff audit row — list read, ``resource_count`` = items returned.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint=_LIST_ENDPOINT,
            org_id=ctx.org_id,
            resource_type="audit_pdf_history",
            resource_count=len(items),
            redacted=False,
        )

    return AuditPdfHistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ── POST — regenerate by id ──────────────────────────────────────────


@router.post(
    "/{customer_id}/audit-pdfs/{pdf_id}/regenerate",
    response_class=Response,
    name="regenerate_audit_pdf",
)
async def regenerate_audit_pdf(
    customer_id: str,
    pdf_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> Response:
    """Re-render the PDF using the persisted parameters.

    Returns ``application/pdf`` with the same Content-Disposition
    convention as ``audits.py``. Errors:

      * 403 ``staff_read_only`` — staff cannot regenerate (write).
      * 403 ``baa_expired``     — BAA expired since original render;
                                  operator must renew before the
                                  artifact leaves the platform.
      * 404                     — pdf_id missing or cross-org.
      * 504 ``pdf_render_timeout`` — same semantics as audits.py.
    """
    # Defense-in-depth: ``require_permission_with_context("write")``
    # already 403s staff, but we keep the explicit guard for legibility
    # (mirrors ``audits.py``).
    if ctx.is_staff:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "staff_read_only",
                "detail": (
                    "Vera staff sessions are read-only in this tier. "
                    "Customer admins regenerate audit PDFs from their "
                    "own dashboard."
                ),
            },
        )

    customer = await _resolve_customer_or_404(
        session, org_id=ctx.org_id, customer_id=customer_id
    )

    # Look up the history row — must belong to the same customer AND
    # caller's org. We re-check org_id explicitly even though
    # _resolve_customer_or_404 already org-scoped the customer; a
    # history row pinned to a different org via the same customer is
    # not possible (FK is org_id-scoped via customer_id) but a defensive
    # check costs nothing.
    row_result = await session.execute(
        select(GeneratedAuditPdf).where(
            GeneratedAuditPdf.id == pdf_id,
            GeneratedAuditPdf.customer_id == customer.id,
            GeneratedAuditPdf.org_id == ctx.org_id,
        )
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Audit PDF history row not found")

    # Validate persisted parameters against the current contract — a
    # historical row whose branding or section set is no longer
    # supported should produce a clean 400 rather than a 500 from the
    # renderer.
    if row.branding not in _VALID_BRANDING:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_branding",
                "detail": (
                    f"Persisted branding {row.branding!r} is no longer "
                    f"supported. Generate a fresh audit PDF instead."
                ),
            },
        )

    raw_sections = row.sections_json
    persisted_sections: list[str] = (
        [str(s) for s in raw_sections] if isinstance(raw_sections, list) else []
    )
    unknown = [s for s in persisted_sections if s not in _VALID_SECTIONS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_sections",
                "detail": (
                    f"Persisted section(s) {unknown} are no longer supported. "
                    "Generate a fresh audit PDF instead."
                ),
            },
        )
    # Empty persisted list → fall back to all sections, matching the
    # original POST behaviour for an empty body.
    sections_arg: Optional[list[str]] = (
        persisted_sections if persisted_sections else None
    )

    org = await session.get(Organization, ctx.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # BAA freshness — re-checked at re-download time. If the BAA has
    # expired since the original render we refuse: the artifact must
    # not leave the platform under an expired agreement.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    baa_active = await _is_baa_active_for_customer(
        session, customer_id=customer.id, now=now
    )
    if not baa_active:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "baa_expired",
                "detail": (
                    "An active Business Associate Agreement is required "
                    "to re-download an audit PDF for this Customer."
                ),
                "fix_url": f"/customers/{customer.tenant_id}",
            },
        )

    try:
        pdf_bytes = await generate_audit_pdf(
            session,
            org,
            customer,
            date_from=row.date_from,
            date_to=row.date_to,
            sections=sections_arg,
            branding=row.branding,
        )
    except PdfRenderTimeout:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "pdf_render_timeout",
                "detail": (
                    "The audit PDF re-render exceeded the 30 second "
                    "budget. Consider narrowing the date range and "
                    "retrying."
                ),
            },
        )
    except ValueError as exc:
        logger.warning("PDF generator rejected regenerate request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_request", "detail": str(exc)},
        )

    filename = _safe_filename(customer.tenant_id, row.date_to)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
