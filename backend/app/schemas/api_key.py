from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

VALID_PERMISSIONS = {"read", "write", "admin"}
VALID_KINDS = ("test", "live")


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    permissions: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_at: Optional[datetime] = None
    # Phase 1 PR 1: ``test`` = sandbox / al_test_* prefix; ``live`` = production
    # / al_live_* prefix. BAA-gating on live keys lands in PR 4; here the
    # schema accepts both values, defaulting to ``test``.
    kind: Literal["test", "live"] = Field(default="test")

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v):
        if not v:
            raise ValueError("permissions must not be empty")
        invalid = set(v) - VALID_PERMISSIONS
        if invalid:
            raise ValueError(f"invalid permissions: {invalid}. Must be from: {VALID_PERMISSIONS}")
        return list(set(v))  # deduplicate


class APIKeyCreateResponse(BaseModel):
    """Returned once when a key is created — includes the raw key."""
    id: str
    name: str
    raw_key: str
    key_prefix: str
    permissions: list[str]
    kind: str = "test"
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class APIKeyResponse(BaseModel):
    """Returned when listing keys — no raw key."""
    id: str
    name: str
    key_prefix: str
    permissions: list[str]
    kind: str = "test"
    created_at: datetime
    revoked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}
