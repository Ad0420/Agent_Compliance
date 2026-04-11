from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    alert_email: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertEmailUpdate(BaseModel):
    alert_email: Optional[str] = None

    @field_validator("alert_email")
    @classmethod
    def validate_email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v


class RegisterRequest(BaseModel):
    org_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("org_name")
    @classmethod
    def strip_and_require_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("org_name cannot be blank or whitespace only")
        return v


class RegisterResponse(BaseModel):
    org_id: str
    org_name: str
    api_key: str   # raw key — shown once, never stored
    key_prefix: str
    created_at: datetime
