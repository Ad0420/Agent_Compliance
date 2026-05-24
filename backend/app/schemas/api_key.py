from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

VALID_PERMISSIONS = {"read", "write", "admin"}
VALID_KINDS = ("test", "live")


class APIKeyCreate(BaseModel):
    """Create payload for an API key.

    Phase 1 PR 4 (Stream C item C1) reintroduces ``kind`` on the create
    path: callers explicitly opt into ``'live'`` and the
    ``dashboard_api_keys.create_api_key`` handler refuses without an
    active BAA. ``'test'`` is the default so the safe fallback is also
    the easiest one — sandbox keys never require a BAA. The legacy
    behaviour where the schema silently dropped ``kind`` (Phase 1 PR 1)
    is gone for good.
    """

    name: str = Field(..., min_length=1, max_length=200)
    permissions: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_at: Optional[datetime] = None
    # ``Literal`` so a misspelled tier (``"prod"``, ``"production"``,
    # ``"sandbox"``) returns a 422 from Pydantic before the route handler
    # ever runs. Default 'test' so omitting the field stays safe.
    kind: Literal["test", "live"] = "test"

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
