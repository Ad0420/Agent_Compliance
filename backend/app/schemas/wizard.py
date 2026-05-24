"""Onboarding wizard schemas (Phase 1 PR 14, Stream F item F5).

Five canonical questions from ``policy-engine-mvp.md`` Appendix A:

  1. Agent type            — radio
  2. Jurisdictions         — multi-select; US Federal always included
  3. Decision volume       — radio (rough monthly bucket)
  4. Channel               — radio (where human review happens)
  5. HIPAA Privacy Officer — text (name + email)

The shape is locked to Appendix A. ``extra="forbid"`` on every model
prevents wizard answers from being polluted with arbitrary keys — the
JSON column is otherwise a free-form blob and we do not want the API to
become an "anything goes" persistence sink.

Generation (Risk Analysis / 1557 / BAA drafts) lands in Phase 5. This
PR only persists answers.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Q1: Agent type ────────────────────────────────────────────────────
# Slugs map to Appendix A's option list:
#   "scribe"        → "AI scribe / chart entry assistant"
#   "receptionist"  → "AI receptionist / voice agent"
#   "prior_auth"    → "AI prior-auth / claims agent"
#   "triage"        → "AI triage / symptom checker"
#   "other"         → "Other clinical AI" (free-text supplement)
AgentType = Literal["scribe", "receptionist", "prior_auth", "triage", "other"]

# ── Q3: Decision volume buckets (monthly) ────────────────────────────
#   lt_10k     → "< 10,000      (Starter)"
#   10k_100k   → "10K - 100K    (Growth)"
#   100k_1m    → "100K - 1M     (Scale)"
#   gt_1m      → "> 1M          (Enterprise)"
DecisionVolume = Literal["lt_10k", "10k_100k", "100k_1m", "gt_1m"]

# ── Q4: Channel for human review ─────────────────────────────────────
#   in_app_webhook  → "In-app webhook (default)"
#   slack           → "Slack (solo practitioners or dev/compliance team)"
#   vera_dashboard  → "Vera dashboard (batch compliance oversight)"
#   multiple        → "Multiple (combine — e.g. webhook for clinical,
#                                dashboard for compliance)"
ReviewChannel = Literal[
    "in_app_webhook", "slack", "vera_dashboard", "multiple"
]

# ── Q2: Jurisdiction tokens ──────────────────────────────────────────
# US Federal is implied / required per Appendix A ("can't deselect") so
# the wire format always includes ``us_federal`` and we accept the
# allow-listed optional add-ons. Extra tokens are rejected at validation
# time — the frontend renders the same allow-list, and the server is the
# enforcement boundary.
_JURISDICTION_ALLOWED = frozenset(
    {"us_federal", "us_ca", "other_state"}
)

# RFC-lightweight check for the "other_state" custom token so we don't
# silently accept "us_xx" garbage. The frontend currently doesn't expose
# per-state selection beyond CA — Appendix A defers "Other state-specific"
# to v2 — so ``other_state`` is the single placeholder marker.


class PrivacyOfficer(BaseModel):
    """Q5 — name + email. PII; never stored in localStorage on the client."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    # Light shape check matches the project pattern in
    # ``schemas/organization.py`` and ``schemas/customer.py`` so we avoid
    # adding ``email-validator`` to requirements just for this field. The
    # dashboard validates more strictly client-side; this is the
    # server-side defence-in-depth.
    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank or whitespace only")
        return v

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("email cannot be blank")
        if v.count("@") != 1:
            raise ValueError("email must contain exactly one '@'")
        local, _, domain = v.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("email is not a valid email address")
        return v


class WizardAnswers(BaseModel):
    """Full payload for a completed (or in-progress) wizard submission.

    All fields are Optional individually so the frontend can persist
    partial answers across reloads. On a ``completed=true`` submission
    the route layer enforces presence of every field (see
    ``routes/wizard.py``).
    """

    model_config = ConfigDict(extra="forbid")

    agent_type: Optional[AgentType] = None
    # Free-text supplement when ``agent_type == "other"``. 200-char limit
    # mirrors what the frontend Textarea allows.
    agent_type_other: Optional[str] = Field(default=None, max_length=200)

    jurisdictions: Optional[list[str]] = Field(default=None)
    decision_volume: Optional[DecisionVolume] = None
    channel: Optional[ReviewChannel] = None
    privacy_officer: Optional[PrivacyOfficer] = None

    @field_validator("jurisdictions")
    @classmethod
    def _validate_jurisdictions(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if not v:
            # Appendix A: US Federal is required and cannot be deselected,
            # so an empty list is never a valid submission.
            raise ValueError("jurisdictions must not be empty")
        seen: set[str] = set()
        cleaned: list[str] = []
        for token in v:
            if not isinstance(token, str):
                raise ValueError("jurisdictions entries must be strings")
            t = token.strip()
            if t not in _JURISDICTION_ALLOWED:
                raise ValueError(
                    f"unknown jurisdiction token: {token!r}; allowed: "
                    f"{sorted(_JURISDICTION_ALLOWED)}"
                )
            if t in seen:
                continue
            seen.add(t)
            cleaned.append(t)
        if "us_federal" not in seen:
            # Appendix A: HIPAA + Section 1557 are always in scope, so the
            # token must always be present on a non-empty list.
            raise ValueError("jurisdictions must include 'us_federal'")
        return cleaned

    @field_validator("agent_type_other")
    @classmethod
    def _strip_other(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None


class WizardAnswersSubmission(BaseModel):
    """Body for ``POST /v1/organizations/me/wizard-answers``.

    ``completed`` flips ``wizard_completed_at`` on the Organization row.
    When true, every wizard field must be populated. When false, the
    server treats the payload as a partial save (any subset OK as long
    as each present field is individually valid).
    """

    model_config = ConfigDict(extra="forbid")

    answers: WizardAnswers
    completed: bool = False


class WizardAnswersResponse(BaseModel):
    """Body for ``GET /v1/organizations/me/wizard-answers`` and the
    POST response. ``answers`` is ``null`` when the org has never opened
    the wizard. ``completed_at`` is ``null`` until the operator clicks
    'Complete setup'."""

    model_config = ConfigDict(extra="forbid")

    answers: Optional[WizardAnswers] = None
    completed_at: Optional[datetime] = None


# Re-exported for tests + the route layer.
JURISDICTION_TOKENS = _JURISDICTION_ALLOWED
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")  # noqa: F401 — kept for parity
