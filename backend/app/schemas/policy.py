from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Policy schemas ──────────────────────────────────────────────────────────

CONDITION_TYPES = ("unknown_agent", "missing_reasoning", "failure_rate", "high_failure_burst", "consecutive_failures")
ACTION_TYPES = ("flag", "email", "block")
SEVERITY_LEVELS = ("critical", "high", "medium", "low")


class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    condition_type: str = Field(..., pattern="^(unknown_agent|missing_reasoning|failure_rate|high_failure_burst|consecutive_failures)$")
    condition_params: dict = Field(default_factory=dict)
    action: str = Field(..., pattern="^(flag|email|block)$")
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    is_active: bool = True


class PolicyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    condition_params: Optional[dict] = None
    action: Optional[str] = Field(default=None, pattern="^(flag|email|block)$")
    severity: Optional[str] = Field(default=None, pattern="^(critical|high|medium|low)$")
    is_active: Optional[bool] = None


class PolicyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    org_id: str
    name: str
    description: Optional[str] = None
    condition_type: str
    condition_params: dict
    action: str
    severity: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PolicyListResponse(BaseModel):
    policies: list[PolicyResponse]
    total: int


# ── Violation schemas ───────────────────────────────────────────────────────


class ViolationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    org_id: str
    policy_id: Optional[str] = None
    record_id: Optional[str] = None
    triggered_at: datetime
    severity: str
    context: dict
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class ViolationResolve(BaseModel):
    resolved_by: Optional[str] = Field(default=None, max_length=500)


class ViolationListResponse(BaseModel):
    violations: list[ViolationResponse]
    total: int
