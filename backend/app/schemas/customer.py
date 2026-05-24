"""Customer API schemas (Phase 1 PR 1 + PR 2 + PR 13).

PR 1 introduced the substrate (Create / Update / Response / List) so the
model + migration could ship without route churn. PR 2 layers the CRUD
endpoints (``GET / PATCH /v1/customers``) on top and adds the
``contact_name`` / ``first_seen_at`` / ``last_seen_at`` /
``decision_count_30d`` fields the dashboard's AI Coverage Matrix renders.
PR 13 adds the per-customer agents response shape used by the AI
Coverage Matrix in the Customer detail page, plus the BAA upload
contract used by the inline "Complete setup" wizard.
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


# ── PR 13: per-customer agents (AI Coverage Matrix) ──────────────────────


class CustomerAgentCoverage(BaseModel):
    """One row in the AI Coverage Matrix for a customer.

    The columns in ``dashboard-design.md`` §Coverage Matrix are derived
    from this shape:

    * ``detected_at`` → first time we saw this (customer, agent_type)
    * ``coverage`` → covered / partial / none, computed from ``status``
    * ``has_capture`` → ActionRecords exist for this pair
    * ``hitl_gate_count`` → Phase 2 (gates ship later); always 0 today
    * ``pdf_included`` → Phase 4 (PDF generator ships later); always False
    * ``posture_included`` → Phase 4 (org posture compute); always False

    The "placeholder" columns are surfaced today rather than hidden so
    the dashboard's contract stays stable when PR 2/4 actually populate
    them — only the values change.
    """

    id: str
    agent_type: str
    agent_id: Optional[str] = None
    source: Literal["auto_discovered", "declared", "csv_import"]
    confidence: Literal["low", "medium", "high"]
    status: Literal["active", "retired"]
    first_seen_at: datetime
    last_seen_at: datetime
    coverage: Literal["covered", "partial", "none"]
    has_capture: bool
    hitl_gate_count: int = 0
    pdf_included: bool = False
    posture_included: bool = False


class CustomerAgentsResponse(BaseModel):
    """Wrapper for ``GET /v1/customers/{tenant_id}/agents``."""

    items: list[CustomerAgentCoverage]
    total: int


# ── PR 13: BAA upload endpoint ───────────────────────────────────────────


class BAAUploadRequest(BaseModel):
    """Body of ``POST /v1/customers/{tenant_id}/baa``.

    Phase 1 ships the upload contract with a pre-signed ``document_uri``
    rather than wiring a full multipart-to-S3 path. The dashboard widget
    will hand the user's selected file to a follow-up signed-URL endpoint
    (Phase 2 work); for the acceptance gate ("one BAA upload completes
    setup") all we need is the row to exist + the freshness cache to
    invalidate so the customer's status flips to ``active`` immediately.

    ``effective_at`` and ``expires_at`` are optional. If omitted, the
    BAA is treated as effective immediately + indefinite (matching the
    ``is_org_baa_active`` semantics in ``services/baa.py``).

    ``is_unrestricted`` defaults to True for Phase 1 — granular service /
    agent-type scoping ships in Phase 2 once the gate path is wired.
    """

    document_uri: str = Field(..., min_length=1, max_length=512)
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    is_unrestricted: bool = True
    covered_services: Optional[list[str]] = None
    covered_agent_types: Optional[list[str]] = None

    @field_validator("document_uri")
    @classmethod
    def _validate_uri_shape(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("document_uri must not be empty")
        # Light defence-in-depth: must look like a URL (http/https/s3).
        # PHI-safety guard: reject obviously suspicious filenames embedded
        # in the URI (a PHI-laden filename is a leak even if the file
        # content is encrypted). Caller-side widget strips PHI before
        # upload; this is the server-side belt-and-braces check.
        if not re.match(r"^(https?|s3)://", v, flags=re.IGNORECASE):
            raise ValueError(
                "document_uri must be an http(s):// or s3:// URL"
            )
        return v


class BAAUploadResponse(BaseModel):
    """Response from ``POST /v1/customers/{tenant_id}/baa``.

    Returns the freshly-active BAA's identifiers + the customer's new
    ``baa_status`` so the dashboard can re-render without a second
    fetch.
    """

    agreement_id: str
    scope_id: str
    customer_baa_status: BAAStatus
    customer_status: CustomerStatus
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class BAADocumentUploadResponse(BaseModel):
    """Response from uploading a signed BAA PDF into Vera-owned S3."""

    document_uri: str
    bucket: str
    key: str
    size_bytes: int
    content_type: str
