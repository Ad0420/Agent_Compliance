"""BAAAgreement model — the signed BAA between operator org and customer.

One BAA row per (org, customer) signing event. Lifecycle fields are
mostly nullable on draft and fill in as the agreement flows through
upload → effective → expiry. The actual PDF lives at ``document_uri``
(populated by the BAA upload endpoint in Phase 1 PR 10).

Status transitions are policy-enforced upstream (Phase 1 PR 4 gates
``kind='live'`` keys on at least one ``status='active'`` BAA), but the
column-level CHECK constraint here keeps the data shape honest.
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class BAAAgreement(Base):
    __tablename__ = "baa_agreements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'expired', 'terminated')",
            name="ck_baa_status",
        ),
        # Reject ops-typo BAAs where ``effective_at`` is after ``expires_at``.
        # Both NULL on draft is allowed (constraint short-circuits to TRUE);
        # a partial spec (one side NULL) is also allowed.
        CheckConstraint(
            "effective_at IS NULL OR expires_at IS NULL "
            "OR effective_at <= expires_at",
            name="ck_baa_temporal_order",
        ),
        Index("idx_baa_customer_status", "customer_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # S3 URL of the signed BAA PDF. Populated by the upload endpoint
    # (Phase 1 PR 10), not by this schema PR.
    document_uri: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    effective_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Python-side ``onupdate`` matches the ChainState / Customer pattern so
    # ``updated_at`` tracks status / signed_at changes (otherwise it freezes
    # at INSERT).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────
    organization: Mapped["Organization"] = relationship("Organization")
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="baa_agreements"
    )
    scopes: Mapped[list["BAAScope"]] = relationship(
        "BAAScope",
        back_populates="agreement",
        cascade="all, delete-orphan",
    )
