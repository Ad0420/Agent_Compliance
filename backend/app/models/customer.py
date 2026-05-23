"""Customer model — the customer-of-the-customer (Phase 1 PR 1).

A Customer is the hospital / bank / employer that the operator org (Vera's
actual customer) serves. The SDK passes a free-form ``tenant_id`` string
via ``vera.tenant()`` and the backend resolves that to a Customer row for
display in the AI Coverage Matrix and BAA enforcement in Phase 2/3.

Distinct from ``ActionRecord.data_subject_id``, which is the patient /
affected person under HIPAA Right of Access. Customer = the operator's
customer; data_subject_id = the patient. Do NOT conflate the two.
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
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("org_id", "tenant_id", name="uq_customer_org_tenant"),
        CheckConstraint(
            "status IN ('pending_setup', 'active', 'suspended', 'archived')",
            name="ck_customer_status",
        ),
        CheckConstraint(
            "baa_status IN ('missing', 'pending', 'active', 'expired')",
            name="ck_customer_baa_status",
        ),
        Index("idx_customer_org_status", "org_id", "status"),
        Index("idx_customer_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Customer identifier passed by the SDK. Format regex is enforced at the
    # API boundary in Phase 1 PR 4: ``^[a-zA-Z0-9_-]{1,64}$``.
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending_setup"
    )
    baa_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="missing"
    )
    contact_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Jurisdictions covered for this customer (e.g. ``["CA", "TX"]``).
    # Drives state-by-state report filtering in Phase 3.
    jurisdictions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # ── Relationships ─────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="customers"
    )
    agents: Mapped[list["CustomerAgent"]] = relationship(
        "CustomerAgent",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    baa_agreements: Mapped[list["BAAAgreement"]] = relationship(
        "BAAAgreement",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
