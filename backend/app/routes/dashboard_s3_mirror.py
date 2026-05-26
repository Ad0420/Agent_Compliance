"""Dashboard routes for the customer Off-Vera S3 mirror configuration.

Phase 3 Wave 3D.3 — surfaces the off-Vera S3 mirror configuration UI on
Settings. Lets a customer admin:

  * View the currently-configured ARN (if any) and the rollup of recent
    exports written to the checkpoint_exports forensic table.
  * Set / update / clear the ARN (server-side syntax-validated via the
    Wave 3A.d validator before persistence).
  * Run a pure-validation pass before committing the value (for the
    dashboard's on-blur validation UX).
  * Run a trust probe (HeadBucket + AssumeRole) for environments where
    ``ACTIONLEDGER_S3_TRUST_PROBE_ENABLED=1``. Stubbed-by-default mode
    is faithfully surfaced to the UI so the operator knows the green
    check is syntax-only, not a real AWS round-trip.

RBAC matrix (matches the BAA / alert-email surface):
    GET   /v1/dashboard/s3-export-config            — admin + developer
    PUT   /v1/dashboard/s3-export-arn               — admin only
    DELETE /v1/dashboard/s3-export-arn              — admin only
    POST  /v1/dashboard/s3-export-arn/validate      — admin only
    POST  /v1/dashboard/s3-export-arn/probe         — admin only

The legacy SDK-side endpoint
``POST /v1/organizations/me/off-vera-mirror/validate`` (Wave 3A.d) stays
untouched — that surface is API-key-gated and the SDK uses it for
pre-validation. The /v1/dashboard/* routes are Clerk-gated and mirror
the same validator + probe so the dashboard never has to forward Clerk
credentials to an API-key route.

Error shape: all failures use the flat envelope from PR #201
(``{code, message, hint?}`` at the top level — NOT
``{"detail": {...}}``). The global StarletteHTTPException handler in
``main.py`` performs that flattening.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.clerk_auth import require_clerk_role
from ..models import CheckpointExport, Organization
from ..services.external_store import (
    S3ArnValidationError,
    probe_s3_trust,
    validate_iam_role_arn_syntax,
    validate_s3_arn_syntax,
)


router = APIRouter(prefix="/v1/dashboard", tags=["dashboard-s3-mirror"])


# ── Response / request models ─────────────────────────────────────


class RecentExportRow(BaseModel):
    """One row of the "Recent exports" table on Settings → Off-Vera mirror.

    Mirrors the columns the dashboard renders: short checkpoint id,
    status, exported-at timestamp, duration, and the structured reason
    on non-success rows. ``s3_location`` is intentionally omitted from
    the v1 surface — the bucket location is reconstructible from the
    org's configured ARN, and surfacing the per-key location risks
    leaking forensic detail to the wrong tier of viewer.
    """

    id: str
    checkpoint_id: str
    status: str
    exported_at: Optional[str] = None
    duration_ms: Optional[int] = None
    record_count: Optional[int] = None
    reason: Optional[str] = None


class S3MirrorConfigResponse(BaseModel):
    """``GET /v1/dashboard/s3-export-config`` response.

    ``arn`` is the *raw* configured ARN (or ``None``). The frontend is
    responsible for masking — the rule of thumb is "never mask in the
    API for fields the admin already had access to write" — and we
    avoid masking server-side so the dashboard can still copy/paste the
    full value when needed.

    Counters are computed over the org's full checkpoint_exports
    history; the "Recent exports" table shows the last 10 rows.
    """

    arn: Optional[str] = None
    probe_enabled: bool = Field(
        ...,
        description=(
            "Whether ACTIONLEDGER_S3_TRUST_PROBE_ENABLED is set. The "
            "frontend disables the 'Test connection' button when false "
            "and surfaces the deployment-gating message."
        ),
    )
    iam_role_supported: bool = Field(
        ...,
        description=(
            "Whether the backend supports the optional IAM role-assumption "
            "field. False in v1 — the role-assumption flow was deferred "
            "from Wave 3B.1 to a follow-up. Frontend uses this to gate "
            "the second form field behind 'Coming soon'."
        ),
    )
    success_total: int = 0
    failure_total: int = 0
    skipped_total: int = 0
    pending_total: int = 0
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = None
    recent_exports: list[RecentExportRow] = []


class S3MirrorArnUpdate(BaseModel):
    """``PUT /v1/dashboard/s3-export-arn`` body.

    ``arn`` is mandatory on the PUT — clearing the value uses DELETE
    instead of PUT-with-null so the "I unset this intentionally" intent
    is unambiguous on both the wire and in the dashboard analytics.
    """

    arn: str = Field(
        ...,
        description="S3 bucket ARN, e.g. arn:aws:s3:::my-vera-mirror",
    )


class S3MirrorArnValidateRequest(BaseModel):
    arn: str
    role_arn: Optional[str] = None


class S3MirrorArnValidateResponse(BaseModel):
    """Pure validation response — same shape as
    ``OffVeraMirrorValidateResponse`` on the SDK side, kept locally so
    the dashboard's TS types don't have to depend on the SDK schema."""

    ok: bool
    can_put: bool
    can_get: bool
    stub: bool = False


# ── Helpers ───────────────────────────────────────────────────────


def _trust_probe_enabled() -> bool:
    """Single source of truth for whether the probe gate is live.

    Read here so the response model and the probe endpoint stay in sync;
    if the env var flips at runtime (test harness, ops toggle) both
    surfaces pick it up on the next request.
    """
    return os.environ.get(
        "ACTIONLEDGER_S3_TRUST_PROBE_ENABLED", ""
    ).lower() in {"1", "true", "yes"}


def _iam_role_supported() -> bool:
    """Whether the IAM role-assumption code path is wired through.

    For v1 this returns False — the role-assumption flow was deferred
    from Wave 3B.1. A future PR that lands the AssumeRole pipeline
    flips ``ACTIONLEDGER_S3_IAM_ROLE_SUPPORTED=1`` (or removes the gate
    entirely) and the frontend's "Coming soon" badge disappears.
    """
    return os.environ.get(
        "ACTIONLEDGER_S3_IAM_ROLE_SUPPORTED", ""
    ).lower() in {"1", "true", "yes"}


def _arn_validation_to_http(exc: S3ArnValidationError) -> HTTPException:
    """Convert a validator exception into the flat-error HTTPException.

    The global StarletteHTTPException handler in main.py lifts dict
    ``detail`` to the top of the response body, so the wire envelope
    becomes ``{code, message, hint?}`` — matches the existing
    /v1/organizations/me/off-vera-mirror/validate surface exactly.
    """
    detail: dict[str, str] = {"code": exc.code, "message": exc.message}
    if exc.hint:
        detail["hint"] = exc.hint
    return HTTPException(status_code=400, detail=detail)


def _row_to_recent(row: CheckpointExport) -> RecentExportRow:
    return RecentExportRow(
        id=row.id,
        checkpoint_id=row.checkpoint_id,
        status=row.status,
        exported_at=row.exported_at.isoformat() if row.exported_at else None,
        duration_ms=row.duration_ms,
        record_count=row.record_count,
        reason=row.reason,
    )


# ── Routes ────────────────────────────────────────────────────────


@router.get("/s3-export-config", response_model=S3MirrorConfigResponse)
async def get_s3_export_config(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin", "developer"])),
) -> S3MirrorConfigResponse:
    """Return the org's current S3-mirror configuration + export rollup.

    Visible to admins and developers — developers can read the config
    (useful for SDK integration debugging) but can't mutate it. The
    legacy /v1/organizations/me endpoint already exposes the column
    server-side, so the read tier matches that surface.
    """
    org_id = ctx["org_id"]
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Aggregate counts by status. A single GROUP-BY would be cheaper but
    # keeping four explicit COUNT(*) queries is easier to read and the
    # checkpoint_exports table is small per-org (one row per checkpoint,
    # i.e. dozens to thousands at most).
    counts_q = (
        select(CheckpointExport.status, func.count(CheckpointExport.id))
        .where(CheckpointExport.org_id == org_id)
        .group_by(CheckpointExport.status)
    )
    counts_by_status: dict[str, int] = {}
    for status_val, n in (await session.execute(counts_q)).all():
        counts_by_status[status_val] = int(n or 0)

    # Last success / last failure summaries — the dashboard renders
    # these next to the configured ARN so the operator sees "Mirror is
    # live, last sync 04:00 UTC" or "Last sync 04:00 UTC — access
    # denied" without having to scroll the recent-exports table.
    last_success_q = (
        select(CheckpointExport)
        .where(
            CheckpointExport.org_id == org_id,
            CheckpointExport.status == "success",
        )
        .order_by(desc(CheckpointExport.exported_at))
        .limit(1)
    )
    last_failure_q = (
        select(CheckpointExport)
        .where(
            CheckpointExport.org_id == org_id,
            CheckpointExport.status == "failure",
        )
        .order_by(desc(CheckpointExport.exported_at))
        .limit(1)
    )
    last_success = (await session.execute(last_success_q)).scalar_one_or_none()
    last_failure = (await session.execute(last_failure_q)).scalar_one_or_none()

    recent_q = (
        select(CheckpointExport)
        .where(CheckpointExport.org_id == org_id)
        .order_by(desc(CheckpointExport.exported_at))
        .limit(10)
    )
    recent_rows = (await session.execute(recent_q)).scalars().all()

    return S3MirrorConfigResponse(
        arn=org.s3_export_arn,
        probe_enabled=_trust_probe_enabled(),
        iam_role_supported=_iam_role_supported(),
        success_total=counts_by_status.get("success", 0),
        failure_total=counts_by_status.get("failure", 0),
        skipped_total=counts_by_status.get("skipped", 0),
        pending_total=counts_by_status.get("pending", 0),
        last_success_at=(
            last_success.exported_at.isoformat()
            if last_success and last_success.exported_at
            else None
        ),
        last_failure_at=(
            last_failure.exported_at.isoformat()
            if last_failure and last_failure.exported_at
            else None
        ),
        last_failure_reason=last_failure.reason if last_failure else None,
        recent_exports=[_row_to_recent(r) for r in recent_rows],
    )


@router.put("/s3-export-arn", response_model=S3MirrorConfigResponse)
async def update_s3_export_arn(
    payload: S3MirrorArnUpdate,
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> S3MirrorConfigResponse:
    """Set / update the org's S3 mirror ARN. Admin-only.

    Server-side syntax validation runs before persistence — client-side
    blur validation is a UX nicety, never the authoritative check (per
    the wave brief's "ARN validation is server-side authoritative"
    rule). On syntax failure, a 400 with the flat-error envelope.

    Idempotent: re-PUTting the same value is a no-op (the column
    update is unconditional but writes the same bytes).
    """
    arn = (payload.arn or "").strip()
    try:
        validate_s3_arn_syntax(arn)
    except S3ArnValidationError as exc:
        raise _arn_validation_to_http(exc) from exc

    org_id = ctx["org_id"]
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.s3_export_arn = arn
    await session.commit()
    await session.refresh(org)

    # Mirror the GET shape so the dashboard can update its cached state
    # without a follow-up fetch. The counts re-query is the same as
    # GET — extracted as a helper would just add indirection.
    return await get_s3_export_config(session=session, ctx=ctx)


@router.delete("/s3-export-arn", response_model=S3MirrorConfigResponse)
async def clear_s3_export_arn(
    session: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> S3MirrorConfigResponse:
    """Clear the configured S3 mirror ARN. Admin-only.

    Distinct from PUT-with-null so the "I unset this intentionally"
    intent is unambiguous. Future PRs can attach extra side-effects
    (audit row, webhook notification) without re-piping a magic value
    through the PUT body.
    """
    org_id = ctx["org_id"]
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.s3_export_arn = None
    await session.commit()
    return await get_s3_export_config(session=session, ctx=ctx)


@router.post(
    "/s3-export-arn/validate",
    response_model=S3MirrorArnValidateResponse,
)
async def validate_s3_export_arn(
    payload: S3MirrorArnValidateRequest,
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> S3MirrorArnValidateResponse:
    """Pure validation — never persists, never contacts AWS.

    Used by the dashboard's on-blur validation UX so the customer sees
    "Bucket name must be lowercase" before clicking Save. The probe
    endpoint is the separate "actually hit AWS" surface.

    Returns 200 with ``{ok, can_put, can_get, stub=True}`` on syntax
    pass; 400 with the flat-error envelope on syntax failure.
    """
    try:
        validate_s3_arn_syntax(payload.arn)
    except S3ArnValidationError as exc:
        raise _arn_validation_to_http(exc) from exc

    if payload.role_arn is not None and payload.role_arn.strip():
        try:
            validate_iam_role_arn_syntax(payload.role_arn)
        except S3ArnValidationError as exc:
            raise _arn_validation_to_http(exc) from exc

    # Pure validation is always stub-mode (no AWS call). The probe
    # endpoint is the one that flips stub=False when the env-var gate
    # is live.
    return S3MirrorArnValidateResponse(
        ok=True, can_put=True, can_get=True, stub=True
    )


@router.post(
    "/s3-export-arn/probe",
    response_model=S3MirrorArnValidateResponse,
)
async def probe_s3_export_arn(
    payload: S3MirrorArnValidateRequest,
    ctx: dict = Depends(require_clerk_role(["admin"])),
) -> S3MirrorArnValidateResponse:
    """Run the trust probe — HeadBucket + AssumeRole — against the ARN.

    Respects ``ACTIONLEDGER_S3_TRUST_PROBE_ENABLED``: when unset, the
    probe runs in stub mode and the response carries ``stub=True`` so
    the frontend's badge says "Syntax validated only" instead of
    "Connection verified".

    Syntax validation runs first — a malformed ARN should return the
    structured 400 error rather than a probe failure code, so the
    dashboard's inline field error surfaces correctly.
    """
    try:
        validate_s3_arn_syntax(payload.arn)
    except S3ArnValidationError as exc:
        raise _arn_validation_to_http(exc) from exc

    if payload.role_arn is not None and payload.role_arn.strip():
        try:
            validate_iam_role_arn_syntax(payload.role_arn)
        except S3ArnValidationError as exc:
            raise _arn_validation_to_http(exc) from exc

    role_arn = payload.role_arn.strip() if payload.role_arn else None
    result = await probe_s3_trust(payload.arn, role_arn)
    if not result.get("ok"):
        # Reuse the same flat-envelope shape as the SDK-side route so
        # the dashboard's shared error toast renders both consistently.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "s3_trust_invalid",
                "message": (
                    "Syntax is valid, but Vera could not verify write "
                    "access to the bucket."
                ),
                "hint": (
                    "Check that the bucket policy grants s3:PutObject "
                    "and s3:GetObject to Vera, and that any IAM role "
                    "you supplied allows AssumeRole. AWS reported: "
                    f"{result.get('error_code', 'unknown')}."
                ),
            },
        )

    return S3MirrorArnValidateResponse(
        ok=True,
        can_put=bool(result.get("can_put", False)),
        can_get=bool(result.get("can_get", False)),
        stub=bool(result.get("stub", False)),
    )


__all__ = ["router"]
