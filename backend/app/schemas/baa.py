"""BAA agreement + scope API schemas (Phase 1 PR 1).

The actual BAA upload endpoint lands in Phase 1 PR 10. These schemas
exist now so the model + migration substrate is shippable in isolation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

BAAAgreementStatus = Literal["draft", "active", "expired", "terminated"]


class BAAAgreementCreate(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=36)
    document_uri: Optional[str] = Field(default=None, max_length=512)
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    status: BAAAgreementStatus = "draft"


class BAAAgreementResponse(BaseModel):
    id: str
    org_id: str
    customer_id: str
    document_uri: Optional[str] = None
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    status: BAAAgreementStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BAAScopeCreate(BaseModel):
    """Scope payload for a BAA — Codex E2 requires this be machine-readable.

    ``is_unrestricted=True`` makes the two list columns advisory: the BAA
    covers everything. Defaults to False so new BAAs get the strict
    enumerated semantics; PR 4/5 will backfill historical unrestricted
    BAAs explicitly.
    """

    baa_agreement_id: str = Field(..., min_length=1, max_length=36)
    covered_services: list[str] = Field(..., min_length=1)
    covered_agent_types: list[str] = Field(..., min_length=1)
    granted_at: datetime
    is_unrestricted: bool = False


class BAAScopeResponse(BaseModel):
    id: str
    baa_agreement_id: str
    covered_services: list[str]
    covered_agent_types: list[str]
    is_unrestricted: bool = False
    granted_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
