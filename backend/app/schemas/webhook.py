"""Pydantic schemas for the webhook subscription API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class WebhookCreate(BaseModel):
    url: str = Field(..., max_length=2000)
    event_types: list[str] = Field(...)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        if len(v) > 2000:
            raise ValueError("url must be at most 2000 characters")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        # Imported here to avoid circular import (services/webhooks imports models).
        from ..services.webhooks import ALLOWED_EVENT_TYPES

        if not v:
            raise ValueError("event_types must be a non-empty list")
        invalid = set(v) - ALLOWED_EVENT_TYPES
        if invalid:
            raise ValueError(
                f"invalid event_types: {sorted(invalid)}. "
                f"Must be a subset of: {sorted(ALLOWED_EVENT_TYPES)}"
            )
        # Deduplicate while preserving order
        seen = set()
        out: list[str] = []
        for et in v:
            if et not in seen:
                seen.add(et)
                out.append(et)
        return out


class WebhookUpdate(BaseModel):
    """All fields optional — partial updates via PATCH."""
    url: Optional[str] = Field(default=None, max_length=2000)
    event_types: Optional[list[str]] = None
    is_active: Optional[bool] = None
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        from ..services.webhooks import ALLOWED_EVENT_TYPES

        if not v:
            raise ValueError("event_types must be a non-empty list")
        invalid = set(v) - ALLOWED_EVENT_TYPES
        if invalid:
            raise ValueError(
                f"invalid event_types: {sorted(invalid)}. "
                f"Must be a subset of: {sorted(ALLOWED_EVENT_TYPES)}"
            )
        seen = set()
        out: list[str] = []
        for et in v:
            if et not in seen:
                seen.add(et)
                out.append(et)
        return out


class WebhookCreateResponse(BaseModel):
    """Returned once when a webhook is created — includes the secret."""
    id: str
    url: str
    event_types: list[str]
    secret: str
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookResponse(BaseModel):
    """Returned when listing/fetching webhooks — never includes the secret."""
    id: str
    url: str
    event_types: list[str]
    is_active: bool
    description: Optional[str] = None
    created_at: datetime
    last_delivery_at: Optional[datetime] = None
    last_delivery_status: Optional[str] = None
    consecutive_failures: int

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    webhooks: list[WebhookResponse]


class WebhookRotateResponse(BaseModel):
    """Returned when rotating a webhook secret — includes the new secret."""
    id: str
    secret: str
