"""Pydantic schemas for the dev-only org-provisioning endpoint.

Used exclusively by ``backend/app/routes/dev.py``. Gated behind
``ENVIRONMENT=development`` at the route layer — these schemas exist
in production builds but are never reachable.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DevOrgCreateInput(BaseModel):
    """Body for ``POST /v1/dev/orgs``.

    Two knobs:

    - ``name``: free-form org name. Unique across the platform per the
      ``uq_organizations_name`` constraint (W1.6 migration
      ``t0o2p3q4r5s6``). Re-using a name returns 409.
    - ``with_baa``: when True, also seeds a placeholder Customer +
      active BAA + wildcard BAAScope so the new org passes Phase 2
      gates that aren't specifically testing ``stale_baa``. Phase 2
      acceptance test discovered every non-BAA scenario silently
      blocked without this seed (Gate 3 fires on everything).
    """

    name: str = Field(..., min_length=1, max_length=255)
    with_baa: bool = False


class DevOrgCreateResponse(BaseModel):
    """Response for a successful ``POST /v1/dev/orgs``.

    ``api_key`` is shown ONCE — the backend hashes it before storage and
    cannot reproduce it. The dev script writes it to
    ``simulator/.env.local`` immediately.
    """

    org_id: str
    name: str
    api_key: str
    api_key_prefix: str
    has_baa: bool


class DevOrgInfo(BaseModel):
    """Slim org descriptor returned by ``GET /v1/dev/orgs``.

    Deliberately omits the API key — once minted the raw key is lost.
    Used by the bootstrap script to check whether a name is already
    taken (idempotency) before attempting a create.
    """

    org_id: str
    name: str
    has_baa: bool


class DevOrgListResponse(BaseModel):
    """Envelope for ``GET /v1/dev/orgs``."""

    orgs: list[DevOrgInfo]
