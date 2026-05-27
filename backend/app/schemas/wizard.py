"""Onboarding wizard schemas — redesigned 2-question shape (Phase 5).

The original 5-question wizard (``policy-engine-mvp.md`` Appendix A) was
trimmed in Phase 5 polish after user testing surfaced that only two of
the five questions actually drove template output. The other three
(``agent_type``, ``decision_volume``, ``channel``) were pretend-
customisation that wasted operator time.

The current shape:

  1. Jurisdictions     — multi-select; US Federal always required
  2. HIPAA Privacy Officer — name + email (substituted into HIPAA Risk
                              Analysis + Section 1557 NDP templates)

The ``wizard_answers`` column is a JSON blob, so no migration is needed
to retire the old fields. Existing completed orgs that wrote
``agent_type`` / ``decision_volume`` / ``channel`` keep those entries
harmlessly (the model ignores them on load — see
``_drop_legacy_fields`` below). New submissions only write the current
shape.

The legacy ``california`` slug is rewritten to ``california_ab489`` on
load via a ``model_validator`` so AI Care Disclosure regeneration keeps
emitting the CA AB 489 clause for orgs that completed the wizard before
the Phase 5 jurisdiction expansion.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Q2: Jurisdiction tokens ──────────────────────────────────────────
# Expanded in Phase 5 polish from the original CA-only set to cover the
# states + supranational regimes the AI Care Disclosure generator now
# branches on.
#
# Slug → conditional clause emitted in ``ai_care_disclosure.py``:
#   us_federal         → (baseline — HIPAA + Section 1557, always)
#   california_ab489   → CA AB 489 clinical decision support clause
#   california_sb942   → CA SB 942 AI consumer disclosure clause
#   texas              → TX TRAIGA healthcare AI clause
#   utah               → UT AIPA generative AI clause
#   colorado           → CO SB 24-205 consequential AI clause
#   eu                 → EU AI Act Art. 50(1) high-risk AI clause
#   new_york           → NY placeholder ("coordinate with counsel")
#   other              → partner to ``jurisdictions_other`` free-text
#
# Legacy ``california`` / ``us_ca`` slugs are coerced to
# ``california_ab489`` on load (see ``_normalise_jurisdictions`` below)
# so orgs that completed the wizard before Phase 5 keep round-tripping.
_JURISDICTION_ALLOWED = frozenset(
    {
        "us_federal",
        "california_ab489",
        "california_sb942",
        "texas",
        "utah",
        "colorado",
        "eu",
        "new_york",
        "other",
    }
)

# Legacy aliases — accepted on input, rewritten to the canonical slug
# before storage / validation. ``us_ca`` was the original Phase 1 token;
# ``california`` was the Phase 5 PR A token; both become
# ``california_ab489`` now.
_LEGACY_CALIFORNIA_SLUGS = frozenset({"california", "us_ca"})


class PrivacyOfficer(BaseModel):
    """Q2 — name + email. PII; never stored in localStorage on the client."""

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


# Subset of fields the model accepts. Anything else (including the
# retired ``agent_type`` / ``decision_volume`` / ``channel`` keys from
# the original 5-question shape) is silently dropped on load so a row
# written before the Phase 5 redesign deserialises cleanly.
_ALLOWED_INPUT_KEYS = frozenset(
    {
        "jurisdictions",
        "jurisdictions_other",
        "privacy_officer",
    }
)


class WizardAnswers(BaseModel):
    """Full payload for a completed (or in-progress) wizard submission.

    Both fields are Optional individually so the frontend can persist
    partial answers across reloads. On a ``completed=true`` submission
    the route layer enforces presence of every field (see
    ``routes/organizations._require_all_fields``).
    """

    # ``extra="ignore"`` — was ``forbid`` on the original 5-question
    # model. Loosened in Phase 5 polish so a wizard_answers row written
    # before the redesign (carrying ``agent_type`` etc.) round-trips
    # without raising. New submissions still come through the route
    # layer, which uses ``Submission`` (below) with ``extra="forbid"``
    # to reject pollution at the API boundary.
    model_config = ConfigDict(extra="ignore")

    jurisdictions: Optional[list[str]] = Field(default=None)
    jurisdictions_other: Optional[list[str]] = Field(default=None)
    privacy_officer: Optional[PrivacyOfficer] = None

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_fields(cls, data):
        """Strip retired keys from the input before validation runs.

        Legacy rows on the ``wizard_answers`` JSON column carry
        ``agent_type`` / ``agent_type_other`` / ``decision_volume`` /
        ``channel`` from the original 5-question shape. Drop them
        silently so model construction succeeds without raising on
        unexpected keys.
        """
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k in _ALLOWED_INPUT_KEYS}
        return data

    @field_validator("jurisdictions")
    @classmethod
    def _validate_jurisdictions(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if not v:
            # US Federal is required and cannot be deselected, so an
            # empty list is never a valid submission.
            raise ValueError("jurisdictions must not be empty")
        seen: set[str] = set()
        cleaned: list[str] = []
        for token in v:
            if not isinstance(token, str):
                raise ValueError("jurisdictions entries must be strings")
            t = token.strip()
            # Legacy slugs — coerce to canonical so AI Care Disclosure
            # regen for older orgs still emits the CA AB 489 clause.
            if t in _LEGACY_CALIFORNIA_SLUGS:
                t = "california_ab489"
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
            # HIPAA + Section 1557 are always in scope, so the
            # token must always be present on a non-empty list.
            raise ValueError("jurisdictions must include 'us_federal'")
        return cleaned

    @field_validator("jurisdictions_other")
    @classmethod
    def _validate_jurisdictions_other(
        cls, v: Optional[list[str]]
    ) -> Optional[list[str]]:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("jurisdictions_other accepts at most 10 entries")
        cleaned: list[str] = []
        for entry in v:
            if not isinstance(entry, str):
                raise ValueError("jurisdictions_other entries must be strings")
            e = entry.strip()
            if not e:
                continue
            if len(e) > 64:
                raise ValueError(
                    "jurisdictions_other entries must be 64 chars or fewer"
                )
            cleaned.append(e)
        return cleaned


class WizardAnswersSubmission(BaseModel):
    """Body for ``POST /v1/organizations/me/wizard-answers``.

    ``completed`` flips ``wizard_completed_at`` on the Organization row.
    When true, every wizard field must be populated. When false, the
    server treats the payload as a partial save (any subset OK as long
    as each present field is individually valid).

    Uses ``extra="forbid"`` on both the wrapper and the nested answers
    so a client cannot pollute the answer blob at the API boundary.
    The ``WizardAnswers`` model itself ignores extras to tolerate
    legacy rows on read.
    """

    model_config = ConfigDict(extra="forbid")

    answers: WizardAnswers
    completed: bool = False

    @field_validator("answers", mode="before")
    @classmethod
    def _reject_unknown_answer_keys(cls, v):
        """Forbid unknown keys at the API boundary.

        ``WizardAnswers`` itself ignores extras to round-trip legacy
        rows, but a fresh API submission with arbitrary keys is almost
        certainly a client bug — reject it explicitly so the contract
        stays tight.
        """
        if isinstance(v, dict):
            unknown = [k for k in v.keys() if k not in _ALLOWED_INPUT_KEYS]
            if unknown:
                raise ValueError(
                    f"unknown answer keys: {unknown}; allowed: "
                    f"{sorted(_ALLOWED_INPUT_KEYS)}"
                )
        return v


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
