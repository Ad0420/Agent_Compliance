"""BAAScope model — covered_services + covered_agent_types per BAA.

Codex E2: BAA scope MUST be machine-readable so Phase 2/3 gate checks
can be scope-aware (i.e. "is this action_class allowed under this BAA?",
"is this agent_type covered?"). Without explicit scope, gate checks
would have to fail-open or fail-closed uniformly.

Legacy BAAs (none exist today; this is forward-looking) backfill as
broad scope — both lists wildcard-equivalent or "all known types".

Multiple BAAScope rows MAY exist per BAA (e.g. an addendum extends the
covered_agent_types list); the resolver picks the most recent applicable
row by ``granted_at``. For Phase 1 PR 1 the schema permits 0..N scopes
per agreement; enforcement of "must have at least one" lives in the
Phase 2 gate-evaluation path.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class BAAScope(Base):
    __tablename__ = "baa_scopes"
    __table_args__ = (Index("idx_scope_baa", "baa_agreement_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    baa_agreement_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("baa_agreements.id", ondelete="CASCADE"),
        nullable=False,
    )
    # List of service names this BAA covers, e.g. ["chart_entry",
    # "scheduling"]. Maps to ActionRecord.action_class strings in Phase 2.
    covered_services: Mapped[list] = mapped_column(JSON, nullable=False)
    # List of agent_types this BAA covers, e.g. ["scribe", "receptionist"].
    # Maps to CustomerAgent.agent_type strings.
    covered_agent_types: Mapped[list] = mapped_column(JSON, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # ── Relationships ─────────────────────────────────────────
    agreement: Mapped["BAAAgreement"] = relationship(
        "BAAAgreement", back_populates="scopes"
    )
