"""``POST /v1/audits/{customer_id}`` — HIPAA AI Audit Trail PDF (Phase 4 W1 A1).

Synchronous endpoint that renders the central product artifact: a
regulator-ready PDF for one Customer over a specified date range. The
response body is the raw PDF bytes with
``Content-Disposition: attachment`` so a browser download works without
extra dashboard plumbing.

IAM model (matches the brief)
-----------------------------
* Customer admins (Clerk admin OR API-key with ``write`` permission)
  generate PDFs for Customers in their own org.
* Vera staff are blocked outright — the Customer owns the artifact and
  must request it from their own dashboard. This matches the
  ``records.py`` precedent where the per-decision Merkle proof endpoint
  also refuses staff reads.
* Cross-org access returns 404 (not 403) so the existence of the other
  org's Customer never leaks through the response code.

BAA gate
--------
If the Customer's BAA is expired *at the moment of the request*, we
return ``HTTP 403`` with ``error.code = "baa_expired"`` so the dashboard
C3 modal can surface the issue inline rather than letting the PDF render
against a stale BAA.

Timeout
-------
Render must finish under 30 s at pilot scale (≤500 records). On overrun
we return ``HTTP 504`` with ``error.code = "pdf_render_timeout"``; the
worker is NOT crashed (see ``services/pdf/generator.py`` for the
``asyncio.wait_for`` strategy).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal, get_db
from ..models import (
    BAAAgreement,
    BAAScope,
    Customer,
    GeneratedAuditPdf,
    Organization,
)
from ..services.auth import AuthContext, require_permission_with_context
from ..services.pdf import PdfRenderTimeout, generate_audit_pdf
from ..services.pdf.sections import DEFAULT_SECTION_ORDER, SECTION_RENDERERS

logger = logging.getLogger("vera.audits")

router = APIRouter(prefix="/audits", tags=["audits"])


_VALID_SECTIONS = frozenset(SECTION_RENDERERS)
_VALID_BRANDING = frozenset({"customer", "vera-neutral"})


class AuditPdfRequest(BaseModel):
    """Body for ``POST /v1/audits/{customer_id}``.

    ``sections`` defaults to all eight sections in canonical order; the
    dashboard's section-toggle UI sends a subset. ``branding`` defaults
    to ``"customer"`` so the typical PDF carries the Customer's
    white-label cover (extension lands in A3); ``"vera-neutral"`` lets
    the Customer download a Vera-branded copy for archive purposes.
    """

    date_from: date = Field(
        description=(
            "Inclusive UTC calendar date. The window for HITL evidence "
            "and Demographic Monitoring is "
            "``[date_from 00:00 UTC, date_to+1 00:00 UTC)``."
        )
    )
    date_to: date = Field(
        description="Inclusive UTC calendar date. Must be >= date_from."
    )
    sections: Optional[list[str]] = Field(
        default=None,
        description=(
            "Subset of the canonical section list. Defaults to all "
            "eight sections in the OCR checklist order."
        ),
    )
    branding: str = Field(
        default="customer",
        description=(
            "``customer`` (default) renders the Customer's white-label "
            "cover (A3); ``vera-neutral`` renders the Vera-branded "
            "fallback cover."
        ),
    )


async def _resolve_customer_or_404(
    session: AsyncSession, *, org_id: str, customer_id: str
) -> Customer:
    """Org-scoped Customer lookup.

    The route accepts the Customer's **primary key** (UUID) as the path
    param — distinct from the ``tenant_id`` string the SDK uses
    elsewhere. We use the PK here because the audit PDF is a Customer-
    detail-page artifact and the dashboard already holds the PK.

    Cross-org returns 404 (not 403) — same convention as
    ``customers.py`` / ``customer_chain_summary.py``: confirming the
    Customer exists would be a side channel.
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
    """Return True iff this Customer has an active+scoped BAA right now.

    Distinct from ``services.baa.is_org_baa_active`` (which is org-scoped
    and cached) — here we need a per-Customer answer that reflects the
    current commit, so we bypass the freshness cache and hit the DB
    directly. The cost is one bounded EXISTS query.
    """
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


def _safe_filename(tenant_id: str, date_to: date) -> str:
    """Build a Content-Disposition filename that's URL-safe and stable.

    ``tenant_id`` is already constrained by the API boundary regex to
    ``^[a-zA-Z0-9_-]{1,64}$`` (see Phase 1 PR 4), so the only
    sanitisation we do is fall back to ``audit`` if the tenant_id is
    empty for any reason.
    """
    safe = tenant_id or "audit"
    return f"audit-{safe}-{date_to.isoformat()}.pdf"


@router.post(
    "/{customer_id}",
    response_class=Response,
    name="generate_audit_pdf",
)
async def generate_audit_pdf_route(
    customer_id: str,
    payload: AuditPdfRequest,
    session: AsyncSession = Depends(get_db),
    # ``write`` matches the brief: customer admins generate PDFs. Clerk
    # admins satisfy this through the role map. Staff sessions are
    # rejected below — ``require_permission_with_context("write")``
    # already 403s staff before we get here (staff are read-only at v1)
    # but we double-check explicitly for safety / a clear error code.
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> Response:
    """Generate the HIPAA AI Audit Trail PDF for one Customer.

    Returns ``application/pdf`` bytes on success, or:
      * 400 — date range invalid (``date_from > date_to``) or unknown
              section / branding requested
      * 403 — BAA expired (``error.code = "baa_expired"``)
      * 403 — Vera staff session (``error.code = "staff_read_only"``;
              raised by the auth dependency itself, but we also defend
              here)
      * 404 — Customer not found in caller's org (cross-org-safe)
      * 504 — render exceeded the 30 s budget
              (``error.code = "pdf_render_timeout"``)
    """
    # Defense-in-depth: the dependency already 403s staff for a
    # non-``read`` permission, but a future refactor could relax that.
    # An explicit guard here keeps the IAM rule legible in this file.
    if ctx.is_staff:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "staff_read_only",
                "detail": (
                    "Vera staff sessions are read-only in this tier. "
                    "Customer admins generate audit PDFs from their own "
                    "dashboard."
                ),
            },
        )

    # ── Request validation ───────────────────────────────────
    if payload.date_from > payload.date_to:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "detail": "date_from must be on or before date_to.",
            },
        )

    if payload.branding not in _VALID_BRANDING:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_branding",
                "detail": (
                    f"branding must be one of {sorted(_VALID_BRANDING)}."
                ),
            },
        )

    sections_arg: Optional[list[str]] = None
    if payload.sections is not None:
        # Reject unknowns up front so the dashboard gets a clean 400
        # rather than a 500 from the renderer's ValueError. Empty list
        # is treated as "all sections" — defensive: a request body that
        # round-trips an empty list (e.g. from a form widget that
        # forgot the default) shouldn't produce an empty PDF.
        if payload.sections:
            unknown = [s for s in payload.sections if s not in _VALID_SECTIONS]
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "invalid_sections",
                        "detail": (
                            f"Unknown section(s): {unknown}. Valid: "
                            f"{sorted(_VALID_SECTIONS)}"
                        ),
                    },
                )
            sections_arg = payload.sections

    # ── Resolve Customer + org ───────────────────────────────
    customer = await _resolve_customer_or_404(
        session, org_id=ctx.org_id, customer_id=customer_id
    )
    org = await session.get(Organization, ctx.org_id)
    if org is None:
        # Shouldn't happen — auth resolved org_id — but defending here
        # gives the regulator-ready surface a clear error if a soft-
        # deleted org slipped through.
        raise HTTPException(status_code=404, detail="Organization not found")

    # ── BAA freshness gate ───────────────────────────────────
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
                    "to generate an audit PDF for this Customer."
                ),
                "fix_url": f"/customers/{customer.tenant_id}",
            },
        )

    # ── Render ───────────────────────────────────────────────
    try:
        pdf_bytes = await generate_audit_pdf(
            session,
            org,
            customer,
            date_from=payload.date_from,
            date_to=payload.date_to,
            sections=sections_arg,
            branding=payload.branding,
        )
    except PdfRenderTimeout:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "pdf_render_timeout",
                "detail": (
                    "The audit PDF render exceeded the 30 second "
                    "budget. Consider narrowing the date range and "
                    "retrying."
                ),
            },
        )
    except ValueError as exc:
        # Shouldn't happen — we validated sections above — but a defense-
        # in-depth catch keeps a future refactor from 500ing.
        logger.warning("PDF generator rejected request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_request", "detail": str(exc)},
        )

    # ── Persist history row ─────────────────────────────────
    # C4 (Phase 4 Wave 2). Append a ``generated_audit_pdfs`` row so the
    # Customer detail page's history table can list past renders +
    # offer Re-download. We deliberately swallow INSERT failures: if the
    # history-row write fails (constraint violation, transient DB
    # hiccup), the user's PDF is already in hand and a failed audit-
    # trail row is a strictly worse UX than missing one history entry.
    # The exception is logged so ops can correlate.
    #
    # We use a fresh session for the write so a constraint violation
    # cannot poison the request-scoped session and trip a follow-up
    # ``MissingGreenlet`` on cleanup. Mirrors the
    # ``services.iam.audit_staff_read`` pattern.
    try:
        sections_persisted: list[str] = (
            list(sections_arg)
            if sections_arg is not None
            else list(DEFAULT_SECTION_ORDER)
        )
        # ``ctx.staff_id`` is populated only on staff-Clerk sessions, but
        # staff sessions are already rejected upstream (the ``ctx.is_staff``
        # guard above 403s). For the API-key path we record the key id;
        # for the customer-Clerk path we currently write NULL — v1
        # ``AuthContext`` doesn't surface the customer's Clerk ``sub``
        # claim. Follow-up: expose ``ctx.user_id`` so customer-Clerk
        # renders show "Generated by <Alice>" instead of "—".
        async with AsyncSessionLocal() as write_session:
            history = GeneratedAuditPdf(
                org_id=org.id,
                customer_id=customer.id,
                generated_at=now,
                generated_by_user_id=ctx.staff_id,
                generated_by_api_key_id=(
                    ctx.api_key.id if ctx.api_key is not None else None
                ),
                date_from=payload.date_from,
                date_to=payload.date_to,
                sections_json=sections_persisted,
                branding=payload.branding,
                byte_size=len(pdf_bytes),
                pdf_storage_url=None,  # v1: regenerate on re-download
            )
            write_session.add(history)
            await write_session.commit()
    except Exception:  # noqa: BLE001 — defense-in-depth, see comment above
        logger.exception(
            "Failed to persist generated_audit_pdfs row for "
            "customer_id=%s org_id=%s — PDF was returned regardless.",
            customer.id,
            org.id,
        )

    filename = _safe_filename(customer.tenant_id, payload.date_to)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
