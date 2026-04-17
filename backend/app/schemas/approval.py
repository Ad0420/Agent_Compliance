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
    """A human reviewer approves or rejects a pending request."""

    decision: str = Field(..., pattern="^(approve|reject)$")
    approver: str = Field(..., min_length=1, max_length=500)
    note: Optional[str] = Field(default=None, max_length=5000)


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


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]
    total: int
