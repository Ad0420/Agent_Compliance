import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, JSON, ForeignKey, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class PolicyViolation(Base):
    __tablename__ = "policy_violations"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="ck_violation_severity",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True
    )
    record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="policy_violations")
    policy: Mapped[Optional["Policy"]] = relationship("Policy", back_populates="violations")
