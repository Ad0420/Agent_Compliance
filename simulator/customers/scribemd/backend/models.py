"""Operational state for the ScribeMD backend.

A single `Encounter` row tracks the lifecycle of a workflow run from
"running" → "awaiting_approval" → "approved"/"rejected"/"committed"/etc.
The `events` JSON column persists every `on_step` payload so a reconnecting
SSE client can replay history. Vera, not us, holds the cryptographic chain.

W2.1 adds a `ReviewInboxItem` row populated by `POST /vera/webhooks`
deliveries (in-band HITL flow): the clinician opens the EHR's Review
Inbox, sees the pending item, and clicks Approve/Reject which calls
Vera's `/v1/reviews/{id}/complete` via the SDK.

`ProcessedWebhookEvent` provides idempotency on `(approval_id, event_type)`
so a Vera webhook retry never double-applies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from simulator.customers.scribemd.backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # "fixture:pancreatitis" | "fixture:followup" | "fixture:chest_pain" | "custom"
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fixture_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Patient summary (safe subset only — never PHI/PII detail).
    patient_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    last_event: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Captured Vera identifiers — the hash chain references for this encounter.
    vera_approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vera_record_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Terminal-state details once the workflow has completed.
    terminal_outcome: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Append-only event stream for SSE replay.
    events: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, default=list)

    # The original input the encounter was created with (custom transcript or
    # fixture echo). Useful for the dashboard sidebar.
    input_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "fixture_key": self.fixture_key,
            "patient_summary": self.patient_summary,
            "status": self.status,
            "last_event": self.last_event,
            "vera_approval_id": self.vera_approval_id,
            "vera_record_ids": self.vera_record_ids or [],
            "terminal_outcome": self.terminal_outcome,
            "events": self.events or [],
            "input_payload": self.input_payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReviewInboxItem(Base):
    """A pending HITL review the clinician needs to act on.

    Populated by the `approval.requested` / `review.requested` webhook
    delivery from Vera. Resolved (in place) when the matching
    `approval.resolved` / `review.completed` / `review.expired` event
    arrives, or when the clinician acts via the in-band Review Inbox
    (which calls Vera's `/v1/reviews/{id}/complete` via the SDK and
    then waits for the corresponding webhook callback to confirm).

    The `(approval_id)` is unique — a row already exists if a duplicate
    `approval.requested` webhook arrives, in which case we treat it as
    idempotent.
    """

    __tablename__ = "review_inbox_items"

    # Vera's approval_id (a.k.a. review_id — same primary identifier).
    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Local encounter this approval was raised for. Best-effort —
    # populated from the webhook payload's `context.encounter_id` if
    # present, otherwise null (still useful: a clinician can act on the
    # row without it).
    encounter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Lifecycle. `pending` while awaiting clinician action;
    # `approved` / `rejected` / `expired` once resolved by either the
    # in-band Approve/Reject button OR an upstream webhook
    # (`review.completed` / `review.expired`).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )

    # Gate-derived metadata for the clinician's view.
    risk_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Patient subject id, if Vera surfaced it.
    data_subject_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # The redacted context snapshot Vera sent in the webhook (diagnoses
    # / orders summary). Distinct from the full note — that lives in
    # the encounter row.
    context_excerpt: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # When the clinician acts in-band the resolved fields go here.
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Timestamps from the upstream webhook payload (so the UI can show
    # "requested 2 min ago" or "expires in 1h").
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "encounter_id": self.encounter_id,
            "status": self.status,
            "risk_tier": self.risk_tier,
            "required_role": self.required_role,
            "action_name": self.action_name,
            "agent_name": self.agent_name,
            "data_subject_id": self.data_subject_id,
            "context_excerpt": self.context_excerpt,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
            "requested_at": (
                self.requested_at.isoformat() if self.requested_at else None
            ),
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ProcessedWebhookEvent(Base):
    """Idempotency ledger for incoming Vera webhook deliveries.

    Keyed on `(approval_id, event_type)` per the W2.1 acceptance criterion:
    the same webhook redelivered (Vera retries failed POSTs) must produce
    a no-op on the second hit.

    We also stash `event_id` (Vera's delivery id) for trace correlation.
    """

    __tablename__ = "processed_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "approval_id", "event_type", name="uq_processed_event"
        ),
    )

    # Surrogate PK — composite uniqueness lives in the constraint above.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
