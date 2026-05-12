"""Bridge between Clerk users and backend organizations.

The dashboard authenticates users via Clerk (humans), but compliance data —
action records, policies, API keys — lives under backend ``Organization``
rows (machines). When a user signs up via Clerk and creates an org, Clerk
fires an ``organization.created`` webhook; the handler creates a matching
``Organization`` row with ``clerk_org_id`` set, plus an ``OrgMembership``
row linking the creating user (as admin) to the backend org.

Role values are the *backend* role names (``admin`` / ``developer`` /
``compliance_reviewer``), not Clerk's ``org:admin`` / ``org:member``
strings. The webhook handler maps Clerk roles → backend roles at write
time so RBAC checks elsewhere never have to know about Clerk's naming.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization


# Allowed backend role values. ``admin`` can mint API keys and manage
# org settings; ``developer`` can list/use keys but not create/revoke;
# ``compliance_reviewer`` is read-only across compliance surfaces (approvals,
# violations) without API-key-mint privileges. Mirrored in
# ``BACKEND_ROLES`` for the webhook role-mapping table.
BACKEND_ROLES = ("admin", "developer", "compliance_reviewer")


class OrgMembership(Base):
    __tablename__ = "org_memberships"
    __table_args__ = (
        UniqueConstraint("clerk_user_id", "clerk_org_id", name="uq_user_per_org"),
        CheckConstraint(
            "role IN ('admin', 'developer', 'compliance_reviewer')",
            name="ck_org_membership_role",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clerk_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    clerk_org_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="memberships"
    )
