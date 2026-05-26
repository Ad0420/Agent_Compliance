from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Organization, ChainState, APIKey
from ..models.organization import CHECKPOINT_CADENCES
from ..schemas.organization import AlertEmailUpdate, OrganizationCreate, OrganizationResponse
from ..schemas.wizard import (
    WizardAnswers,
    WizardAnswersResponse,
    WizardAnswersSubmission,
)
from ..services.auth import require_permission
from ..services.baa import is_org_baa_active
from ..services.external_store import (
    S3ArnValidationError,
    probe_s3_trust,
    validate_iam_role_arn_syntax,
    validate_s3_arn_syntax,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


class CheckpointCadenceResponse(BaseModel):
    """Response for the cadence read endpoint (and the PATCH success
    response, so the frontend can render the new value without a
    follow-up GET).
    """

    cadence: str


class CheckpointCadenceUpdate(BaseModel):
    """PATCH body. The ``cadence`` literal is validated in the handler
    against ``CHECKPOINT_CADENCES`` so we can emit a structured 422
    with the full ``valid_cadences`` list — pydantic's default literal
    error doesn't surface that as cleanly to a UI.
    """

    cadence: str


class BAAStatusResponse(BaseModel):
    """Response for ``GET /v1/organizations/me/baa-status``.

    Single boolean (``active``) is enough for the API-key dialog's
    "Production" tab gating in Phase 1 PR 4 (Stream C item C5). We
    deliberately do NOT include the BAA's ``document_uri`` or any
    customer-identifying fields here — the API-key surface should not
    leak the org's customer roster.
    """

    active: bool
    fix_url: str = "/customers"


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    data: OrganizationCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Create a new organization. Requires admin API key."""
    org = Organization(name=data.name)
    session.add(org)
    await session.flush()

    # Initialize chain state for this org
    chain_state = ChainState(org_id=org.id)
    session.add(chain_state)

    await session.commit()
    await session.refresh(org)
    return OrganizationResponse.model_validate(org)


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse.model_validate(org)


@router.get("/me/baa-status", response_model=BAAStatusResponse)
async def get_current_organization_baa_status(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Whether the active org has at least one active+scoped BAA right now.

    Used by the API-keys dialog (frontend `/api-keys`) to enable or
    disable the "Create production key" button before the user hits
    submit. The mint endpoint (`POST /v1/dashboard/api-keys`) does the
    real enforcement; this endpoint is purely UX so the operator sees
    the gate state inline instead of guessing after a 403.

    Bypasses the BAA freshness cache so a newly-uploaded BAA is visible
    immediately — the cost is one extra DB query per dialog open, which
    is fine for a low-frequency user-initiated flow.
    """
    org_id, _ = auth
    active = await is_org_baa_active(session, org_id, bypass_cache=True)
    return BAAStatusResponse(active=active)


@router.get(
    "/me/checkpoint-cadence", response_model=CheckpointCadenceResponse
)
async def get_checkpoint_cadence(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Return the active org's checkpoint cadence.

    Phase 3 Wave 3A.b (Eng review finding 1D). Surfaced under
    ``read`` so any org member — including the developer + compliance
    reviewer Clerk roles — can fetch the current setting. Only
    ``admin`` may PATCH (the sibling endpoint below).
    """
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return CheckpointCadenceResponse(cadence=org.checkpoint_cadence)


@router.patch(
    "/me/checkpoint-cadence", response_model=CheckpointCadenceResponse
)
async def update_checkpoint_cadence(
    data: CheckpointCadenceUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Update the active org's checkpoint cadence.

    Admin-only — the cadence directly affects the audit-trail's
    regulator-ready posture, so this sits alongside ``alert-email`` in
    the ``admin`` permission scope. Validation:

    * The cadence value must be one of ``CHECKPOINT_CADENCES``. We
      return a structured 422 with ``valid_cadences`` so a frontend
      can render a dropdown without hard-coding the list.
    * The model-layer CHECK constraint backs us up if a future caller
      bypasses this validator (e.g. via a raw SQL update or a future
      bulk-config endpoint).
    """
    org_id, _ = auth
    if data.cadence not in CHECKPOINT_CADENCES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_cadence",
                "detail": (
                    f"checkpoint_cadence must be one of "
                    f"{list(CHECKPOINT_CADENCES)}; got {data.cadence!r}"
                ),
                "valid_cadences": list(CHECKPOINT_CADENCES),
            },
        )
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    org.checkpoint_cadence = data.cadence
    await session.commit()
    await session.refresh(org)
    return CheckpointCadenceResponse(cadence=org.checkpoint_cadence)


@router.patch("/me/alert-email", response_model=OrganizationResponse)
async def update_alert_email(
    data: AlertEmailUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Set or clear the tamper-alert email address for this organization."""
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    org.alert_email = str(data.alert_email) if data.alert_email else None
    await session.commit()
    await session.refresh(org)
    return OrganizationResponse.model_validate(org)


# ── Wizard answers (Phase 1 PR 14, Stream F item F5) ───────────────
#
# The 5-question onboarding wizard ([policy-engine-mvp.md Appendix A]).
# Answers persist on the Organization row as a JSON blob. The route
# layer enforces multi-tenancy (org_id from auth, never from the body)
# and tier-appropriate permissions:
#
#   - GET is ``read`` so any org member can fetch and rehydrate the
#     in-progress wizard across browser sessions.
#   - POST is ``admin`` so only org admins can mutate the persisted
#     answer set. Lines up with how Customer + BAA admin actions are
#     gated elsewhere in this router.
#
# When ``completed=true`` we require every wizard field be populated;
# partial saves (``completed=false``) accept any subset of valid
# fields. Idempotency: submitting twice with the same answers leaves
# the row unchanged except for an updated ``wizard_completed_at`` only
# if the row wasn't already completed (we don't bump the timestamp on
# a re-submit of an already-completed wizard).


def _require_all_fields(answers: WizardAnswers) -> None:
    """Raise HTTPException(400) if any wizard field is missing.

    Called for ``completed=true`` submissions. Partial saves bypass this
    so the wizard can persist mid-flow without forcing the operator to
    answer every question up front.
    """
    missing: list[str] = []
    if answers.agent_type is None:
        missing.append("agent_type")
    if answers.agent_type == "other" and not answers.agent_type_other:
        missing.append("agent_type_other")
    if not answers.jurisdictions:
        missing.append("jurisdictions")
    if answers.decision_volume is None:
        missing.append("decision_volume")
    if answers.channel is None:
        missing.append("channel")
    if answers.privacy_officer is None:
        missing.append("privacy_officer")
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "wizard_incomplete",
                "detail": (
                    "Cannot mark wizard complete: missing answers for "
                    f"{missing}"
                ),
                "missing_fields": missing,
            },
        )


@router.get(
    "/me/wizard-answers", response_model=WizardAnswersResponse
)
async def get_wizard_answers(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Return the org's persisted onboarding-wizard answers (or null).

    Any org member can read so the wizard rehydrates across browser
    sessions and devices. The response shape is stable across
    "never opened", "in progress", and "complete" so the frontend
    branches on ``completed_at`` rather than on payload presence.
    """
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # The JSON column accepts any dict — validate on read so a manually
    # mutated row (or a stale partial save written by an older schema)
    # surfaces as an empty wizard rather than crashing the frontend.
    answers: WizardAnswers | None
    if org.wizard_answers is None:
        answers = None
    else:
        try:
            answers = WizardAnswers.model_validate(org.wizard_answers)
        except Exception:
            # Forward-compat: an older or hand-edited blob shouldn't
            # crash the GET. Treat as "never opened" so the wizard
            # re-prompts cleanly.
            answers = None

    return WizardAnswersResponse(
        answers=answers,
        completed_at=org.wizard_completed_at,
    )


@router.post(
    "/me/wizard-answers", response_model=WizardAnswersResponse
)
async def submit_wizard_answers(
    payload: WizardAnswersSubmission,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Persist the org's onboarding-wizard answers.

    Admin-only — only org admins should be reshaping compliance posture
    declarations. ``completed=true`` requires every field populated and
    stamps ``wizard_completed_at`` on first completion. Subsequent
    re-submissions update the answer blob but do NOT bump
    ``wizard_completed_at`` once already set (so the "first complete"
    timestamp survives later edits).
    """
    org_id, _ = auth
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if payload.completed:
        _require_all_fields(payload.answers)

    # Persist the validated, normalised answers as a plain dict so the
    # JSON column round-trips cleanly on both SQLite (TEXT) and
    # Postgres (JSON).
    org.wizard_answers = payload.answers.model_dump(mode="json")

    if payload.completed and org.wizard_completed_at is None:
        # First completion: stamp now (UTC, naive — the column type is
        # ``DateTime`` without timezone for SQLite portability, matching
        # the project pattern in ``services/auth.generate_api_key``).
        # Re-completions are a no-op on the timestamp so the "first
        # completed at" history is preserved.
        org.wizard_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await session.commit()
    await session.refresh(org)

    # Re-validate before returning so the response is always shape-true.
    answers = WizardAnswers.model_validate(org.wizard_answers)
    return WizardAnswersResponse(
        answers=answers,
        completed_at=org.wizard_completed_at,
    )


# ── Off-Vera mirror — S3 ARN validation (Wave 3A.d) ────────────────
#
# Customers configure an off-Vera S3 mirror (Settings → Compliance) so
# the checkpoint stream lands in a bucket Vera cannot delete. v1-test-
# plan.md Phase 3 flags "Customer S3 ARN mistyped" as a gap: without
# this endpoint, the typo only surfaces at the *first checkpoint write*
# (hours to days later), and the operator has long since closed the
# Settings page. This endpoint lets the dashboard validate at save time.
#
# Two-stage flow:
#   1. Syntax check — pure regex, no AWS call. Always runs.
#   2. Trust probe — optional STS AssumeRole + HeadBucket. Stubbed for
#      v1; the dashboard renders the stub result as a "Syntax OK" badge.
#
# Errors are emitted with the flat-error envelope from PR #201
# (``{code, message, hint?}`` at the response top level) so the SDK and
# the dashboard's shared error toast can render them without
# de-nesting.


class OffVeraMirrorValidateRequest(BaseModel):
    """Payload for ``POST /v1/organizations/me/off-vera-mirror/validate``.

    ``role_arn`` is optional — customers who haven't created the
    AssumeRole role yet can still validate the bucket ARN syntactically
    before they finish the IAM dance.
    """

    arn: str = Field(..., description="Customer S3 bucket ARN, e.g. arn:aws:s3:::my-mirror")
    role_arn: str | None = Field(
        default=None,
        description="Optional IAM role ARN Vera should assume to write checkpoints.",
    )


class OffVeraMirrorValidateResponse(BaseModel):
    """200 response — syntax OK and (optionally) trust probe ran cleanly."""

    ok: bool
    can_put: bool
    can_get: bool
    # ``stub=True`` when the trust probe ran in stub mode (no real AWS
    # round-trip). Frontend renders this as a "syntax validated only"
    # badge so the operator knows the green check isn't a full probe.
    stub: bool = False


@router.post(
    "/me/off-vera-mirror/validate",
    response_model=OffVeraMirrorValidateResponse,
)
async def validate_off_vera_mirror(
    payload: OffVeraMirrorValidateRequest,
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Validate a candidate off-Vera mirror S3 ARN (+ optional role ARN).

    Returns ``200 {ok, can_put, can_get, stub}`` on success.

    On any validation failure, raises ``HTTPException(400)`` with a flat
    error envelope::

        {"code": "<stable-code>", "message": "...", "hint": "..."}

    The codes are stable contract surface — the dashboard maps them to
    inline field-level errors, and ``code`` should never change for a
    given failure mode. ``hint`` is optional and may evolve copy.

    Admin-only — mirror configuration touches compliance posture so we
    gate it the same way BAA / alert-email writes are gated.
    """
    try:
        validate_s3_arn_syntax(payload.arn)
    except S3ArnValidationError as exc:
        detail: dict[str, str] = {"code": exc.code, "message": exc.message}
        if exc.hint:
            detail["hint"] = exc.hint
        raise HTTPException(status_code=400, detail=detail) from exc

    if payload.role_arn is not None:
        try:
            validate_iam_role_arn_syntax(payload.role_arn)
        except S3ArnValidationError as exc:
            detail = {"code": exc.code, "message": exc.message}
            if exc.hint:
                detail["hint"] = exc.hint
            raise HTTPException(status_code=400, detail=detail) from exc

    # Trust probe is best-effort and never raises; a failed probe maps
    # to a 400 with ``code='s3_trust_invalid'`` so the dashboard can
    # surface the AWS-side problem (revoked role, missing HeadBucket
    # permission, …) without the customer leaving the page.
    result = await probe_s3_trust(payload.arn, payload.role_arn)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "s3_trust_invalid",
                "message": (
                    "S3 ARN is syntactically valid but Vera could not "
                    "verify write access to the bucket."
                ),
                "hint": (
                    "Check that the IAM role grants s3:PutObject and "
                    "s3:GetObject on this bucket and that Vera's "
                    "service principal can AssumeRole into it. "
                    f"AWS reported: {result.get('error_code', 'unknown')}."
                ),
            },
        )

    return OffVeraMirrorValidateResponse(
        ok=True,
        can_put=bool(result.get("can_put", False)),
        can_get=bool(result.get("can_get", False)),
        stub=bool(result.get("stub", False)),
    )
