"""Pydantic request/response schemas for the public API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    passkey: str


class MeResponse(BaseModel):
    signed_in_as: str


# ── Sessions ──────────────────────────────────────────────────────────────


class CustomSessionInput(BaseModel):
    symptoms: str = Field(..., min_length=1)
    chief_complaint: str = Field(..., min_length=1)


FixtureKey = Literal["easy_self_care", "red_flag_chest_pain", "ambiguous"]


class CreateSessionRequest(BaseModel):
    """Either `fixture` (one of the canned sessions) OR `custom`."""

    fixture: Optional[FixtureKey] = None
    custom: Optional[CustomSessionInput] = None


class CreateSessionResponse(BaseModel):
    id: str
    status: str


class SessionSnapshot(BaseModel):
    id: str
    source: str
    fixture_key: Optional[str]
    patient_summary: Optional[dict[str, Any]]
    status: str
    last_event: Optional[str]
    vera_approval_id: Optional[str]
    vera_record_ids: list[str]
    terminal_outcome: Optional[dict[str, Any]]
    events: list[dict[str, Any]]
    input_payload: Optional[dict[str, Any]]
    created_at: Optional[str]
    updated_at: Optional[str]


class SessionListResponse(BaseModel):
    sessions: list[SessionSnapshot]
    total: int
    limit: int
    offset: int


# ── Reviews ───────────────────────────────────────────────────────────────


class DecideReviewRequest(BaseModel):
    """Nurse's decision on a pending review.

    `confirm` → use AI's level. `escalate` → use the red-flag detector's
    recommended_override (the workflow falls back to `urgent_care` if
    the detector did not propose one).
    """

    decision: Literal["confirm", "escalate"]
    nurse: str = Field(..., min_length=1)
    note: Optional[str] = None
