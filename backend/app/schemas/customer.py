"""Customer API schemas (Phase 1 PR 1).

The CRUD endpoints land in Phase 1 PR 2. These schemas exist now so the
model + migration substrate is shippable in isolation and PR 2 can layer
the endpoints on top without further schema churn.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

CustomerStatus = Literal["pending_setup", "active", "suspended", "archived"]
BAAStatus = Literal["missing", "pending", "active", "expired"]


class CustomerCreate(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=255)
    contact_email: Optional[str] = Field(default=None, max_length=255)
    jurisdictions: Optional[list[str]] = None

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id_format(cls, v: str) -> str:
        if not _TENANT_ID_RE.match(v):
            raise ValueError(
                "tenant_id must match ^[a-zA-Z0-9_-]{1,64}$"
            )
        return v


class CustomerUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=255)
    contact_email: Optional[str] = Field(default=None, max_length=255)
    jurisdictions: Optional[list[str]] = None
    status: Optional[CustomerStatus] = None
    baa_status: Optional[BAAStatus] = None


class CustomerResponse(BaseModel):
    id: str
    org_id: str
    tenant_id: str
    display_name: Optional[str] = None
    status: CustomerStatus
    baa_status: BAAStatus
    contact_email: Optional[str] = None
    jurisdictions: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]
    total: int
    limit: int
    offset: int
