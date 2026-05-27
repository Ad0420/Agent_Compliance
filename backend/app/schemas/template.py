"""Pydantic schemas for the Phase 5 PR A templates surface.

Mirrors the route shapes in ``app/routes/templates.py``. The status
enum captures the three states a template row can be in:

  * ``not_started``       — no row exists for this (org, key) pair yet;
                            ``GET /v1/templates`` synthesises a stub item.
  * ``in_progress``       — row exists, body has been generated or
                            edited, but ``attested_at`` is NULL.
  * ``counsel_attested``  — row exists, body is locked-by-policy, the
                            attestation triple is populated.

The status is computed by the route layer from the persisted columns;
nothing else writes it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TemplateStatus = Literal["not_started", "in_progress", "counsel_attested"]


class GeneratedTemplateSummary(BaseModel):
    """One row in the ``GET /v1/templates`` list response.

    Always exactly five items in the list (one per
    ``TEMPLATE_KEYS`` entry), even when no DB row exists for a key —
    the route layer synthesises a ``not_started`` stub. The shape
    deliberately omits ``markdown_body`` to keep the list payload
    small; clients fetch the body via the per-key GET.
    """

    model_config = ConfigDict(extra="forbid")

    template_key: str
    status: TemplateStatus
    attested_at: Optional[datetime] = None
    attested_by_name: Optional[str] = None
    # ``updated_at`` is the persisted ``updated_at`` for materialised
    # rows; for ``not_started`` stubs it is None so the frontend can
    # render "Not started" without inventing a timestamp.
    updated_at: Optional[datetime] = None


class GeneratedTemplateDetail(BaseModel):
    """Per-key GET / PUT / attest response.

    Carries the full Markdown body + attestation triple. Returned by
    ``GET /v1/templates/{key}``, ``PUT /v1/templates/{key}``, and
    ``POST /v1/templates/{key}/attest``.
    """

    model_config = ConfigDict(extra="forbid")

    template_key: str
    markdown_body: str
    status: TemplateStatus
    generated_at: datetime
    updated_at: datetime
    attested_at: Optional[datetime] = None
    attested_by_user_id: Optional[str] = None
    attested_by_name: Optional[str] = None
    content_hash_at_attestation: Optional[str] = None


class TemplatePutRequest(BaseModel):
    """Body for ``PUT /v1/templates/{key}``.

    ``min_length=1`` so an empty body is a clean 422 rather than a
    silent "I just cleared my attested template by submitting blank".
    ``max_length=200_000`` is a generous cap: real-world Markdown
    rarely exceeds 50 KB; 200 KB leaves headroom for unusually long
    documents while bounding memory.
    """

    model_config = ConfigDict(extra="forbid")

    markdown_body: str = Field(..., min_length=1, max_length=200_000)


class TemplateAttestRequest(BaseModel):
    """Body for ``POST /v1/templates/{key}/attest``.

    ``counsel_attested`` MUST be ``True`` to proceed; the route layer
    400s with ``code='counsel_attestation_required'`` if it is False.
    The boolean is a deliberate ceremony — a click on a "Counsel has
    reviewed" checkbox before the attestation lands.
    """

    model_config = ConfigDict(extra="forbid")

    counsel_attested: bool
    reviewer_name: str = Field(..., min_length=3, max_length=255)


class TemplateGenerateResponse(BaseModel):
    """Body for ``POST /v1/templates/generate``.

    ``generated`` = template_keys whose rows were created or refreshed
    on this call.
    ``skipped_attested`` = template_keys whose rows existed AND were
    attested — these are NEVER overwritten by generate (the operator
    must explicitly PUT to clear the attestation first).
    """

    model_config = ConfigDict(extra="forbid")

    generated: list[str]
    skipped_attested: list[str]
