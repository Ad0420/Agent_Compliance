import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


_MAX_JSON_BYTES = 1_000_000


def _validate_json_size(v: dict | list, field_name: str) -> dict | list:
    if v and len(json.dumps(v, default=str)) > _MAX_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum size of {_MAX_JSON_BYTES} bytes")
    return v


class ApprovalCreate(BaseModel):
    """Agent asks a human to approve an action before it's taken."""

    agent_name: str = Field(..., min_length=1, max_length=500)
    action_name: str = Field(..., min_length=1, max_length=500)
    action_summary: Optional[str] = Field(default=None, max_length=2000)
    data_subject_id: Optional[str] = Field(default=None, max_length=500)
    context: dict = Field(default_factory=dict)
    risk_tier: str = Field(default="high", pattern="^(low|medium|high|critical)$")
    approvers_required: int = Field(default=1, ge=1, le=5)
    expires_in_seconds: Optional[int] = Field(default=None, ge=1, le=86_400)

    @field_validator("context")
    @classmethod
    def check_context_size(cls, v, info):
        return _validate_json_size(v, info.field_name)


class ApprovalDecision(BaseModel):
    """A human reviewer approves or rejects a pending request.

    Phase 2 Wave 2D follow-up W1.1 — ``reviewer_role`` was backported
    from A4's ``ReviewCompletionInput`` so the legacy
    ``POST /v1/approvals/{id}/decide`` endpoint can enforce the same
    reviewer-role hierarchy ``/v1/reviews/{id}/complete`` does. The
    field is ``Optional`` for backward-compat with callers deciding on
    un-gated approvals (``Approval.context.required_role is None``), but
    when the approval IS gated the service layer rejects calls that
    omit the field (400 ``reviewer_role_required``). See
    ``services.approvals.decide_approval`` for the enforcement and
    ``backend/tests/test_legacy_decide_role_enforcement.py`` for the
    contract tests. Length constraint mirrors A4's
    ``ReviewCompletionInput.reviewer_role`` (max 64) so a single human
    acting through either endpoint sees the same validation surface.
    """

    decision: str = Field(..., pattern="^(approve|reject)$")
    approver: str = Field(..., min_length=1, max_length=500)
    note: Optional[str] = Field(default=None, max_length=5000)
    reviewer_role: Optional[str] = Field(
        default=None,
        # min_length=1 mirrors A4's ReviewCompletionInput.reviewer_role
        # and gives an empty string a clean 422 rejection at the schema
        # boundary instead of falling through to the service's
        # fail-closed 403. The Optional + min_length combination is
        # Pydantic-valid: None passes (legacy callers), "" is rejected,
        # any non-empty string is forwarded to is_role_sufficient.
        min_length=1,
        max_length=64,
        description=(
            "Optional reviewer-role claim. When the target Approval has "
            "``context.required_role`` set, the service layer compares "
            "this via ``services.reviewer_roles.is_role_sufficient`` and "
            "rejects insufficient or missing values. When the Approval "
            "is un-gated (no ``required_role``), this field is ignored "
            "— preserves legacy behaviour for callers that pre-date W1.1."
        ),
    )


class ApprovalDecisionRecord(BaseModel):
    """One reviewer's vote within an approval, cryptographically signed."""

    decision: str
    approver: str
    note: Optional[str] = None
    decided_at: datetime
    signature: str
    key_id: str


class ApprovalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    org_id: str
    request_record_id: Optional[str] = None
    resolution_record_id: Optional[str] = None
    requested_by_agent: str
    data_subject_id: Optional[str] = None
    action_name: str
    action_summary: Optional[str] = None
    context: dict
    risk_tier: str
    approvers_required: int
    status: str
    decisions: list
    requested_at: datetime
    expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    # ── Wave 2B PR A5: HITL workflow timing ───────────────────────────
    # System-managed; populated by downstream PRs (A3/A4/C2). NOT
    # exposed on ApprovalCreate because clients should not be able to
    # set decision-timing or reviewer-threshold metadata.
    client_review_started_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    webhook_sent_at: Optional[datetime] = None
    callback_received_at: Optional[datetime] = None
    reviewed_below_threshold: bool = False


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]
    total: int
