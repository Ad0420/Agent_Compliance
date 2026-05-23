"""CustomerAgent model — historical (customer, agent_type) coverage rows.

Codex E1: ``agent_type`` MUST be stamped historically at first observation.
Changing Agent metadata later must NOT rewrite past compliance coverage.
So ``agent_type`` lives on this row (not on the ``agents`` row), and
``agent_id`` is SET NULL on delete so deleting an Agent does not delete
its historical coverage record.

One row per (customer_id, agent_type) tuple. Auto-discovery (Phase 1 PR 3)
inserts/updates rows; declared / CSV-import sources are also supported for
operator-managed onboarding.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class CustomerAgent(Base):
    __tablename__ = "customer_agents"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "agent_type", name="uq_customer_agent_type"
        ),
        CheckConstraint(
            "source IN ('auto_discovered', 'declared', 'csv_import')",
            name="ck_customer_agent_source",
        ),
        CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_customer_agent_confidence",
        ),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_customer_agent_status",
        ),
        Index("idx_ca_customer", "customer_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Nullable: auto-discovery may create this row before any Agent row
    # exists, in which case agent_id stays NULL until backfilled. SET NULL
    # on delete preserves historical coverage when the Agent row is removed.
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The historical stamp (Codex E1). E.g. "scribe", "receptionist",
    # "prior_auth". Free-form for now; a controlled vocabulary may land in
    # Phase 2 alongside pack definitions.
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="auto_discovered"
    )
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="high"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # ── Relationships ─────────────────────────────────────────
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="agents"
    )
    agent: Mapped[Optional["Agent"]] = relationship("Agent")
