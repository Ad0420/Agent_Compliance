"""Customer API schemas (Phase 1 PR 1 + PR 2).

PR 1 introduced the substrate (Create / Update / Response / List) so the
model + migration could ship without route churn. PR 2 layers the CRUD
endpoints (``GET / PATCH /v1/customers``) on top and adds the
``contact_name`` / ``first_seen_at`` / ``last_seen_at`` /
``decision_count_30d`` fields the dashboard's AI Coverage Matrix renders.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

CustomerStatus = Literal["pending_setup", "active", "suspended", "archived"]
# ``terminated`` was added in Phase 1 PR 1 to distinguish a rescinded BAA
# from one that simply expired. Matches the model + migration CHECK.
BAAStatus = Literal["missing", "pending", "active", "expired", "terminated"]


class CustomerCreate(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=255)
    contact_email: Optional[str] = Field(default=None, max_length=255)
    contact_name: Optional[str] = Field(default=None, max_length=255)
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
    """Partial-update payload for ``PATCH /v1/customers/{tenant_id}``.

    The PR-2 route only honours ``display_name``, ``contact_email``, and
    ``contact_name``. ``status`` / ``baa_status`` / ``jurisdictions`` remain
    on the schema for forward compatibility with the lifecycle work in
    Phase 1 PR 3 + the BAA upload flow in PR 10. A caller that supplies
    them today gets a 400 — see ``routes/customers.py``.
    """

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    contact_email: Optional[str] = Field(default=None, max_length=255)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    jurisdictions: Optional[list[str]] = None
    status: Optional[CustomerStatus] = None
    baa_status: Optional[BAAStatus] = None

    @field_validator("contact_email")
    @classmethod
    def _validate_email_shape(cls, v: Optional[str]) -> Optional[str]:
        """Light RFC-ish shape check.

        Pydantic's ``EmailStr`` requires the ``email-validator`` package,
        which the project pins for ``AlertEmailUpdate``. Using the same
        approach here would add an import surface for one field; instead
        we do a minimal shape check (must contain a single ``@``, with
        non-empty local + domain parts and at least one ``.`` in the
        domain). The endpoint owner can tighten in PR 3 if needed.
        """
        if v is None or v == "":
            return v
        # Reject obvious garbage quickly. The dashboard validates more
        # strictly client-side; this is a server-side defence-in-depth.
        if v.count("@") != 1:
            raise ValueError("contact_email must contain exactly one '@'")
        local, _, domain = v.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("contact_email is not a valid email address")
        return v


class CustomerResponse(BaseModel):
    id: str
    org_id: str
    tenant_id: str
    display_name: Optional[str] = None
    status: CustomerStatus
    baa_status: BAAStatus
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    jurisdictions: Optional[list[str]] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    # ``decision_count_30d`` is computed at response time, not stored. In
    # Phase 1 it's always 0 — the real aggregation lands in Phase 2 once
    # the per-customer query path is hot. Surfacing the field today keeps
    # the dashboard contract stable across phases.
    decision_count_30d: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerListResponse(BaseModel):
    """List response for ``GET /v1/customers``."""

    items: list[CustomerResponse]
    total: int
    limit: int
    offset: int
