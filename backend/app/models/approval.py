import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
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

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="approvals"
    )
