import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, JSON, Boolean, ForeignKey, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

CONDITION_TYPES = ("unknown_agent", "missing_reasoning", "failure_rate", "high_failure_burst", "consecutive_failures")
ACTION_TYPES = ("flag", "email", "block")
SEVERITY_LEVELS = ("critical", "high", "medium", "low")


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "condition_type IN ('unknown_agent','missing_reasoning','failure_rate','high_failure_burst','consecutive_failures')",
            name="ck_policy_condition_type",
        ),
        CheckConstraint(
            "action IN ('flag','email','block')",
            name="ck_policy_action",
        ),
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="ck_policy_severity",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    condition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    condition_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="policies")
    violations: Mapped[list["PolicyViolation"]] = relationship(
        "PolicyViolation", back_populates="policy"
    )
