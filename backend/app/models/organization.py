import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    alert_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Bridge column to Clerk organizations. Nullable so legacy / API-only orgs
    # created before the Clerk bridge continue to work; unique-when-set so
    # one Clerk org maps to at most one backend org row.
    clerk_org_id: Mapped[Optional[str]] = mapped_column(
        String, unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="organization")
    action_records: Mapped[list["ActionRecord"]] = relationship(
        "ActionRecord", back_populates="organization"
    )
    api_keys: Mapped[list["APIKey"]] = relationship("APIKey", back_populates="organization")
    chain_state: Mapped["ChainState"] = relationship(
        "ChainState", back_populates="organization", uselist=False
    )
    checkpoints: Mapped[list["Checkpoint"]] = relationship(
        "Checkpoint", back_populates="organization"
    )
    policies: Mapped[list["Policy"]] = relationship(
        "Policy", back_populates="organization"
    )
    policy_violations: Mapped[list["PolicyViolation"]] = relationship(
        "PolicyViolation", back_populates="organization"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="organization"
    )
    memberships: Mapped[list["OrgMembership"]] = relationship(
        "OrgMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
