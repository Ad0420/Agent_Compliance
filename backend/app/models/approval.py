import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


RISK_TIERS = ("low", "medium", "high", "critical")
APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "risk_tier IN ('low','medium','high','critical')",
            name="ck_approval_risk_tier",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','cancelled')",
            name="ck_approval_status",
        ),
        CheckConstraint(
            "approvers_required >= 1",
            name="ck_approval_approvers_required",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    request_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True
    )
    resolution_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_agent: Mapped[str] = mapped_column(String(500), nullable=False)
    data_subject_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    action_name: Mapped[str] = mapped_column(String(500), nullable=False)
    action_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    approvers_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decisions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ── Wave 2B PR A5: HITL workflow timing ───────────────────────────
    # Schema-only in this PR. Populated by downstream PRs:
    #   client_review_started_at  → PR C2 (dashboard open event)
    #   decided_at                → PR A4 (reviewer completion)
    #   webhook_sent_at           → PR A3 (webhook dispatcher)
    #   callback_received_at      → PR A4 (POST /v1/reviews/{id}/complete)
    #   reviewed_below_threshold  → PR A4 (role-vs-required_role comparison)
    # All timestamps are naive UTC to match the project-wide convention
    # (see services/approvals.py::_now, services/hashing.py::_normalize).
    # The Alembic migration `q7k8l9m0n1o2_add_approval_workflow_timing`
    # is the source of truth for indexes; `index=True` is intentionally
    # omitted here to keep autogenerate diffs clean.
    #
    # NAMING NOTE: ``decided_at`` here is the ROW-LEVEL decision timestamp
    # (set once when the approval terminates). It is distinct from the
    # per-vote ``decided_at`` inside ``Approval.decisions`` (each signed
    # vote carries its own timestamp; see ``services/approvals.py``).
    # PR A4 must set ``approval.decided_at`` from the SAME ``_now()``
    # value passed into ``_decision_signature_bytes`` so the row-level
    # timestamp matches the chain-anchored vote signature.
    client_review_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    webhook_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    callback_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    reviewed_below_threshold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="approvals"
    )
