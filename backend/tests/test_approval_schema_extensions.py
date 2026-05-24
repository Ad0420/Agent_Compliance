"""Schema-layer tests for Wave 2B PR A5 (HITL workflow timing).

These tests pin the contract:
- ``ApprovalResponse`` exposes the five new fields and round-trips them
  cleanly from an ORM row (``from_attributes=True``).
- Default values match the migration: timestamps default to ``None``,
  ``reviewed_below_threshold`` defaults to ``False``.
- ``ApprovalCreate`` does NOT accept the new fields as model attributes
  (system-managed; clients must not set them).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.approval import ApprovalCreate, ApprovalResponse


# ── ApprovalResponse round-trip ────────────────────────────────────────


class _ApprovalRow:
    """Minimal ORM-shaped stand-in for ``Approval`` that satisfies
    ``model_config = {"from_attributes": True}``."""

    def __init__(self, **kwargs):
        self.id = kwargs.pop("id", "appr-1")
        self.org_id = kwargs.pop("org_id", "org-1")
        self.request_record_id = kwargs.pop("request_record_id", None)
        self.resolution_record_id = kwargs.pop("resolution_record_id", None)
        self.requested_by_agent = kwargs.pop("requested_by_agent", "agent-x")
        self.data_subject_id = kwargs.pop("data_subject_id", None)
        self.action_name = kwargs.pop("action_name", "do-thing")
        self.action_summary = kwargs.pop("action_summary", None)
        self.context = kwargs.pop("context", {})
        self.risk_tier = kwargs.pop("risk_tier", "high")
        self.approvers_required = kwargs.pop("approvers_required", 1)
        self.status = kwargs.pop("status", "pending")
        self.decisions = kwargs.pop("decisions", [])
        self.requested_at = kwargs.pop("requested_at", datetime(2026, 1, 1))
        self.expires_at = kwargs.pop("expires_at", None)
        self.resolved_at = kwargs.pop("resolved_at", None)
        # New A5 fields.
        self.client_review_started_at = kwargs.pop("client_review_started_at", None)
        self.decided_at = kwargs.pop("decided_at", None)
        self.webhook_sent_at = kwargs.pop("webhook_sent_at", None)
        self.callback_received_at = kwargs.pop("callback_received_at", None)
        self.reviewed_below_threshold = kwargs.pop("reviewed_below_threshold", False)
        # Drop any unrecognised kwargs to keep the helper strict.
        assert not kwargs, f"Unexpected kwargs: {kwargs}"


def test_approval_response_serializes_new_fields():
    """All five A5 fields round-trip through ApprovalResponse."""
    ts = datetime(2026, 5, 24, 12, 0, 0)
    row = _ApprovalRow(
        client_review_started_at=ts,
        decided_at=ts,
        webhook_sent_at=ts,
        callback_received_at=ts,
        reviewed_below_threshold=True,
    )

    resp = ApprovalResponse.model_validate(row)
    dumped = resp.model_dump()

    assert dumped["client_review_started_at"] == ts
    assert dumped["decided_at"] == ts
    assert dumped["webhook_sent_at"] == ts
    assert dumped["callback_received_at"] == ts
    assert dumped["reviewed_below_threshold"] is True


def test_approval_response_defaults_when_unset():
    """An ORM row with no A5 values present produces None timestamps
    and False flag — matches the migration's column defaults."""
    row = _ApprovalRow()

    resp = ApprovalResponse.model_validate(row)
    dumped = resp.model_dump()

    assert dumped["client_review_started_at"] is None
    assert dumped["decided_at"] is None
    assert dumped["webhook_sent_at"] is None
    assert dumped["callback_received_at"] is None
    assert dumped["reviewed_below_threshold"] is False


# ── ApprovalCreate must NOT accept new fields ──────────────────────────


def test_approval_create_does_not_expose_new_fields():
    """The new fields are system-managed. ApprovalCreate must not list
    them as fields, so clients cannot set decided_at, reviewed_below_threshold,
    etc., from the wire payload."""
    field_names = set(ApprovalCreate.model_fields.keys())
    for forbidden in (
        "client_review_started_at",
        "decided_at",
        "webhook_sent_at",
        "callback_received_at",
        "reviewed_below_threshold",
    ):
        assert forbidden not in field_names, (
            f"ApprovalCreate must not expose system-managed field {forbidden!r}"
        )


def test_approval_create_silently_drops_new_fields_in_payload():
    """Pydantic v2 default behaviour ignores unknown fields. Confirm a
    payload that attempts to set decided_at on create does not surface
    on the constructed model."""
    payload = ApprovalCreate(
        agent_name="loan-agent",
        action_name="approve_loan",
        decided_at=datetime.now(timezone.utc),  # type: ignore[call-arg]
        reviewed_below_threshold=True,  # type: ignore[call-arg]
    )
    assert not hasattr(payload, "decided_at") or getattr(payload, "decided_at", None) is None
    assert not hasattr(payload, "reviewed_below_threshold") or getattr(
        payload, "reviewed_below_threshold", None
    ) in (None, False)
