import uuid
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import JSON, String, DateTime, Text, func
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
    # Soft-delete marker. Set when Clerk fires ``organization.deleted`` or
    # when an operator marks the org as deleted via admin tooling. Routes
    # that resolve org context MUST filter ``deleted_at IS NULL`` for
    # operational paths; admin / historical paths can opt out.
    #
    # We soft-delete (rather than hard-delete) because ``action_records``
    # uses ``ondelete=RESTRICT`` against this table — an audit-trail product
    # must outlive the org that produced the records. Hard-delete previously
    # raised ``ForeignKeyViolation`` on Postgres whenever an org with any
    # action records was deleted.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    # When we soft-delete via the Clerk webhook we move the Clerk org ID into
    # this column (and NULL out ``clerk_org_id``). This frees the unique
    # constraint so the same Clerk org ID could be reused later, while keeping
    # the forensic link from the surviving audit records back to the Clerk
    # tombstone.
    scrubbed_clerk_org_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    # Phase 1 PR 14 (Stream F item F5) — 5-question onboarding wizard.
    # ``wizard_answers`` is a JSON blob whose shape is validated server-side
    # by ``app/schemas/wizard.py``. Nullable: rows created before the
    # p6j7k8l9m0n1 migration have NULL; rows whose org has opened the wizard
    # but not completed have a partial dict; rows whose org submitted with
    # ``completed=true`` have all five keys populated and ``wizard_completed_at``
    # stamped. Generic ``sa.JSON()`` (not ``JSONB``) keeps SQLite compat.
    wizard_answers: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    # Stamped when the org submits the final wizard step. Distinguishes
    # "in-progress" from "done" without parsing the JSON blob. Phase 5's
    # template-generation work reads this to gate template downloads.
    wizard_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
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
    # Phase 1 PR 1: customer-of-the-customer tenancy.
    customers: Mapped[list["Customer"]] = relationship(
        "Customer",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
