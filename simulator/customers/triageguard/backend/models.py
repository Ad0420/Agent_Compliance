"""Operational state for the TriageGuard backend.

A single `TriageSession` row tracks the lifecycle of a workflow run from
"running" → "awaiting_review" → "routed"/"routing_blocked"/"error".
The `events` JSON column persists every `on_step` payload so a
reconnecting SSE client can replay history. Vera, not us, holds the
cryptographic chain.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from simulator.customers.triageguard.backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TriageSession(Base):
    __tablename__ = "triage_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # "fixture:easy_self_care" | "fixture:red_flag_chest_pain" |
    # "fixture:ambiguous" | "custom"
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fixture_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Patient summary (safe subset only — never raw PHI/PII detail).
    patient_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    last_event: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Captured Vera identifiers — the hash chain references for this session.
    vera_approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vera_record_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Terminal-state details once the workflow has completed.
    terminal_outcome: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Append-only event stream for SSE replay.
    events: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, default=list)

    # The original input the session was created with (custom symptoms or
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
