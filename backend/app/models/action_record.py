import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Integer, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, func, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class ActionRecord(Base):
    __tablename__ = "action_records"
    __table_args__ = (
        UniqueConstraint("org_id", "sequence_number", name="uq_ar_org_sequence"),
        CheckConstraint(
            "result IN ('success', 'failure', 'partial', 'pending', 'blocked')",
            name="ck_ar_result"
        ),
        # Phase 1 PR 1: indexes for the promoted columns. Names match the
        # migration ``l2f3g4h5i6j7`` so create_all + alembic upgrade paths
        # produce the same on-disk shape.
        Index("idx_ar_tenant_id", "tenant_id"),
        Index("idx_ar_org_tenant_seq", "org_id", "tenant_id", "sequence_number"),
        Index("idx_ar_action_class", "action_class"),
    )

    # ── Identity & Integrity ──────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_hash: Mapped[str] = mapped_column(Text, nullable=False)
    record_hash: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # ── Authorization ─────────────────────────────────────
    authorized_by: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delegation_chain: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ── Agent Identity ────────────────────────────────────
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    data_subject_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    agent_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    framework: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    framework_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Action Details ────────────────────────────────────
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    action_name: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )
    target_system: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_resource: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Phase 1 PR 1: promoted from metadata blob to indexed columns ──
    # ``tenant_id`` = the customer-of-the-customer (e.g. Cleveland Clinic).
    # Distinct from ``data_subject_id`` (= the patient under HIPAA Right of
    # Access). The two coexist; do NOT conflate.
    # ``domain`` = vertical bucket (``clinical_decision``, ``lending``,
    # ``hiring``) used by pack selection.
    # ``action_class`` = coarse semantic category (``chart_entry``,
    # ``controlled_substance_order``) used by Phase 2 gates.
    # All nullable for backwards compat with rows created before this PR.
    tenant_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Result ────────────────────────────────────────────
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Flexible JSON blobs ──────────────────────────────
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policies_applied: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reasoning: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    # ── Optional Cryptographic Signature ─────────────────
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="action_records"
    )
    agent: Mapped[Optional["Agent"]] = relationship(
        "Agent", back_populates="action_records"
    )
