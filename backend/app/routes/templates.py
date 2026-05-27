"""Generated Templates CRUD + counsel-attestation (Phase 5 PR A).

Five endpoints under ``/v1/templates``:

  * ``POST /v1/templates/generate``           — idempotent generate.
  * ``GET  /v1/templates``                    — list summary (5 items).
  * ``GET  /v1/templates/{template_key}``     — detail (body + status).
  * ``PUT  /v1/templates/{template_key}``     — edit body + clear
                                                attestation atomically.
  * ``POST /v1/templates/{template_key}/attest`` — counsel attestation.

All endpoints require the ``write`` permission. The ``org_id`` is
always sourced from the auth context — never from a request body or
URL parameter. Staff sessions are rejected (write-only surface);
customers see only their own org's templates.

Atomic attestation triple
-------------------------
``attested_at``, ``attested_by_user_id``, ``attested_by_name``, and
``content_hash_at_attestation`` are written together by the attest
handler and cleared together by the PUT handler. There is no codepath
that touches one without the others — see the model docstring for the
rationale.

Idempotent regeneration
-----------------------
``POST /generate`` is idempotent on every key:

  * Missing row     → INSERT a freshly-generated body, key in ``generated``.
  * Un-attested row → UPDATE markdown_body, key in ``generated``.
  * Attested row    → SKIP (never destroy attested work), key in
                      ``skipped_attested``.

The ``wizard_completed_at`` check gates the whole call — if the
wizard hasn't been completed, we 400 with ``code='wizard_incomplete'``.
That guards against generating policy templates from a half-filled
answer set.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import GeneratedTemplate, Organization
from ..schemas.template import (
    GeneratedTemplateDetail,
    GeneratedTemplateSummary,
    TemplateAttestRequest,
    TemplateGenerateResponse,
    TemplatePutRequest,
)
from ..schemas.wizard import WizardAnswers
from ..services.auth import AuthContext, require_permission_with_context
from ..services.templates import TEMPLATE_KEYS, generate as generate_template_body

logger = logging.getLogger("vera.templates")

router = APIRouter(prefix="/templates", tags=["templates"])


_VALID_KEYS = frozenset(TEMPLATE_KEYS)


# ── Helpers ──────────────────────────────────────────────────────────


def _status_for(row: Optional[GeneratedTemplate]) -> str:
    """Compute the three-state status from a row (or its absence)."""
    if row is None:
        return "not_started"
    if row.attested_at is not None:
        return "counsel_attested"
    return "in_progress"


def _detail_from_row(row: GeneratedTemplate) -> GeneratedTemplateDetail:
    return GeneratedTemplateDetail(
        template_key=row.template_key,
        markdown_body=row.markdown_body,
        status=_status_for(row),
        generated_at=row.generated_at,
        updated_at=row.updated_at,
        attested_at=row.attested_at,
        attested_by_user_id=row.attested_by_user_id,
        attested_by_name=row.attested_by_name,
        content_hash_at_attestation=row.content_hash_at_attestation,
    )


def _validate_template_key(template_key: str) -> None:
    """422 if ``template_key`` is not in ``TEMPLATE_KEYS``.

    Locked-key validation matches the pattern in
    ``app/routes/audits.py`` for the branding enum: rejected at the
    route layer with a structured 4xx rather than letting the DB
    surface a generic constraint error.
    """
    if template_key not in _VALID_KEYS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unknown_template_key",
                "detail": (
                    f"Unknown template_key {template_key!r}. Allowed: "
                    f"{sorted(_VALID_KEYS)}"
                ),
            },
        )


async def _load_org_or_404(session: AsyncSession, org_id: str) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _parse_wizard_answers(org: Organization) -> WizardAnswers:
    """Validate the persisted JSON blob into a ``WizardAnswers`` model.

    The wizard route enforces shape at write-time, but a hand-edited
    DB row or a forward-compat addition could yield a blob that
    fails validation. Treat that as ``wizard_incomplete`` — the
    generator can't reason over a half-validated answer set, and
    we'd rather force the operator to revisit the wizard than emit
    a malformed template.
    """
    raw = org.wizard_answers
    if raw is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "wizard_incomplete",
                "detail": (
                    "Complete the onboarding wizard before generating "
                    "templates."
                ),
            },
        )
    try:
        return WizardAnswers.model_validate(raw)
    except Exception as exc:
        logger.warning(
            "wizard_answers failed re-validation for org=%s: %s", org.id, exc
        )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "wizard_incomplete",
                "detail": (
                    "Onboarding wizard answers did not validate. "
                    "Consider revisiting the wizard before generating "
                    "templates."
                ),
            },
        )


def _resolve_actor_id(ctx: AuthContext) -> str:
    """Return the stable identifier for the caller (Clerk sub or API key id)."""
    if ctx.api_key is not None:
        return ctx.api_key.id
    if ctx.staff_id is not None:
        # Staff sessions never reach a write route in v1, but be
        # defensive — if a future tier lets staff attest, the
        # ``staff_id`` is the right surrogate.
        return ctx.staff_id
    # Clerk customer session. ``AuthContext`` doesn't carry the Clerk
    # sub for non-staff sessions today; surface a sentinel so the row
    # still records "a Clerk user did this" without crashing the
    # attest endpoint.
    return "clerk-session"


# ── POST /generate ───────────────────────────────────────────────────


@router.post("/generate", response_model=TemplateGenerateResponse)
async def generate_templates(
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> TemplateGenerateResponse:
    """Generate (or refresh) all five templates for the caller's org.

    Idempotent. See module docstring for the per-row policy. Returns
    400 ``code='wizard_incomplete'`` if the org has not yet completed
    the onboarding wizard.
    """
    org = await _load_org_or_404(session, ctx.org_id)
    if org.wizard_completed_at is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "wizard_incomplete",
                "detail": (
                    "Complete the onboarding wizard before generating "
                    "templates."
                ),
            },
        )
    answers = _parse_wizard_answers(org)

    existing_result = await session.execute(
        select(GeneratedTemplate).where(GeneratedTemplate.org_id == org.id)
    )
    existing = {row.template_key: row for row in existing_result.scalars().all()}

    generated: list[str] = []
    skipped: list[str] = []

    for key in TEMPLATE_KEYS:
        row = existing.get(key)
        if row is not None and row.attested_at is not None:
            skipped.append(key)
            continue
        body = generate_template_body(key, answers, org)
        if row is None:
            session.add(
                GeneratedTemplate(
                    org_id=org.id,
                    template_key=key,
                    markdown_body=body,
                )
            )
        else:
            row.markdown_body = body
        generated.append(key)

    await session.commit()
    return TemplateGenerateResponse(
        generated=generated,
        skipped_attested=skipped,
    )


# ── GET / (list) ─────────────────────────────────────────────────────


@router.get("/", response_model=list[GeneratedTemplateSummary])
async def list_templates(
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> list[GeneratedTemplateSummary]:
    """List the org's five template rows (always exactly five).

    Missing rows are synthesised as ``not_started`` stubs so the
    frontend can render the full grid without branching on
    "row exists yet?". Order matches ``TEMPLATE_KEYS``.
    """
    rows_result = await session.execute(
        select(GeneratedTemplate).where(GeneratedTemplate.org_id == ctx.org_id)
    )
    by_key = {row.template_key: row for row in rows_result.scalars().all()}

    items: list[GeneratedTemplateSummary] = []
    for key in TEMPLATE_KEYS:
        row = by_key.get(key)
        items.append(
            GeneratedTemplateSummary(
                template_key=key,
                status=_status_for(row),
                attested_at=row.attested_at if row else None,
                attested_by_name=row.attested_by_name if row else None,
                updated_at=row.updated_at if row else None,
            )
        )
    return items


# ── GET /{template_key} ──────────────────────────────────────────────


@router.get("/{template_key}", response_model=GeneratedTemplateDetail)
async def get_template(
    template_key: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> GeneratedTemplateDetail:
    """Return the full body + status for one template.

    404 if the row doesn't exist (call ``POST /generate`` first).
    422 if ``template_key`` is unknown.
    """
    _validate_template_key(template_key)
    row = await _load_row(session, org_id=ctx.org_id, template_key=template_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _detail_from_row(row)


# ── PUT /{template_key} ──────────────────────────────────────────────


@router.put("/{template_key}", response_model=GeneratedTemplateDetail)
async def update_template(
    template_key: str,
    payload: TemplatePutRequest,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> GeneratedTemplateDetail:
    """Replace the markdown body and atomically clear attestation.

    A PUT means "the body has been edited" — and an attested body
    that has been edited is no longer attested. We clear all four
    attestation fields in one transaction so a partial state can
    never be observed.

    404 if the row doesn't exist (must ``POST /generate`` first).
    422 if ``template_key`` is unknown.
    """
    _validate_template_key(template_key)
    row = await _load_row(session, org_id=ctx.org_id, template_key=template_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")

    row.markdown_body = payload.markdown_body
    # Atomic clear of the attestation triple + the hash. ``onupdate``
    # on ``updated_at`` bumps the timestamp automatically.
    row.attested_at = None
    row.attested_by_user_id = None
    row.attested_by_name = None
    row.content_hash_at_attestation = None

    await session.commit()
    await session.refresh(row)
    return _detail_from_row(row)


# ── POST /{template_key}/attest ──────────────────────────────────────


@router.post(
    "/{template_key}/attest", response_model=GeneratedTemplateDetail
)
async def attest_template(
    template_key: str,
    payload: TemplateAttestRequest,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("write")),
) -> GeneratedTemplateDetail:
    """Mark a template as counsel-attested.

    ``counsel_attested`` must be ``True``; we 400 otherwise to make
    the affirmative click load-bearing. On success we hash the
    current body, persist the attestation triple, and return the
    refreshed detail.

    404 if the row doesn't exist (must ``POST /generate`` first).
    422 if ``template_key`` is unknown.
    """
    _validate_template_key(template_key)
    if not payload.counsel_attested:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "counsel_attestation_required",
                "detail": "Counsel must confirm review before sign-off.",
            },
        )

    row = await _load_row(session, org_id=ctx.org_id, template_key=template_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Hash the body at the moment of attestation so the dashboard can
    # render "attested at this exact content" with confidence. The PUT
    # handler clears this alongside the other attestation fields when
    # the body changes.
    digest = hashlib.sha256(row.markdown_body.encode("utf-8")).hexdigest()

    # Atomic write of the attestation triple + hash. UTC naive datetime
    # matches the project convention for ``DateTime`` columns (see
    # ``services/auth.generate_api_key``).
    row.attested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.attested_by_user_id = _resolve_actor_id(ctx)
    row.attested_by_name = payload.reviewer_name.strip()
    row.content_hash_at_attestation = digest

    await session.commit()
    await session.refresh(row)
    return _detail_from_row(row)


# ── Internal helpers ─────────────────────────────────────────────────


async def _load_row(
    session: AsyncSession, *, org_id: str, template_key: str
) -> Optional[GeneratedTemplate]:
    """Org-scoped lookup by template_key. None if no row matches."""
    result = await session.execute(
        select(GeneratedTemplate).where(
            GeneratedTemplate.org_id == org_id,
            GeneratedTemplate.template_key == template_key,
        )
    )
    return result.scalar_one_or_none()
