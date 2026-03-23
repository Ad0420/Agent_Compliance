from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


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
