"""Pydantic request/response schemas for the public API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Auth ────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    passkey: str


class MeResponse(BaseModel):
    signed_in_as: str


# ── Encounters ──────────────────────────────────────────────────────────────


class CustomEncounterInput(BaseModel):
    transcript: str = Field(..., min_length=1)
    chief_complaint: str = Field(..., min_length=1)
    visit_type: Literal["office", "urgent", "telehealth"] = "office"
    expected_risk: Literal["low", "medium", "high", "critical"] = "medium"


FixtureKey = Literal["pancreatitis", "followup", "chest_pain"]


class CreateEncounterRequest(BaseModel):
    """Either `fixture` (one of the canned encounters) OR `custom`."""

    fixture: Optional[FixtureKey] = None
    custom: Optional[CustomEncounterInput] = None


class CreateEncounterResponse(BaseModel):
    id: str
    status: str


class EncounterSnapshot(BaseModel):
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


class EncounterListResponse(BaseModel):
    encounters: list[EncounterSnapshot]
    total: int
    limit: int
    offset: int


# ── Approvals ───────────────────────────────────────────────────────────────


class DecideApprovalRequest(BaseModel):
    decision: Literal["approve", "reject"]
    approver: str = Field(..., min_length=1)
    note: Optional[str] = None
