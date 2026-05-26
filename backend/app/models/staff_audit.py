"""Staff audit log — append-only record of every Vera-staff read against
customer data.

Phase 3 Wave 3A.c — IAM hardening (v1-implementation-plan.md §Phase 3
line 145: "Vera staff cannot read customer PHI payloads; can read aggregate
metrics, chain integrity, gate metadata. Enforced and audited.")

Why a separate table (not ActionRecord chain):
    The hash chain is customer-owned compliance evidence. Vera-staff reads
    are an operational/audit concern that lives outside the customer's
    evidence trail; comingling would (a) pollute the chain with non-action
    events and (b) tempt staff into mutating evidence to hide a read.
    Append-only enforcement on this table is at the application layer
    (no UPDATE/DELETE codepath exists in routes); the IMMUTABILITY trigger
    pattern used by ActionRecord could be extended here as a follow-up.

Indexes:
    * ``(staff_id, read_at DESC)`` — staff-activity dashboard query.
    * ``(org_id, read_at DESC)`` — customer-admin "who read my data?"
      query (Phase 4 polish surface; the data is captured today).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StaffAuditLog(Base):
    __tablename__ = "staff_audit_log"
    __table_args__ = (
        # Staff-activity query: "what has this support engineer accessed
        # in the last 30 days?"
        Index(
            "idx_staff_audit_staff_read",
            "staff_id",
            "read_at",
        ),
        # Customer-visible "who at Vera read my data" query.
        Index(
            "idx_staff_audit_org_read",
            "org_id",
            "read_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Clerk user ID of the staff member. NOT a backend OrgMembership row —
    # staff identity is sourced from Clerk's identity provider, not the
    # backend's per-customer membership table.
    staff_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Path that was read, e.g. ``/v1/actions/{id}`` or
    # ``/v1/customers/{tenant_id}/decisions``. Stored as the templated
    # path so dashboards don't have to dedupe IDs in URL strings.
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    # Customer Organization whose data was accessed. FK-cascade keeps
    # audit history bounded by org lifecycle — if a customer leaves and
    # their org row is removed, the audit log goes with it (HIPAA data
    # minimisation: no orphaned audit rows linking to gone-orgs).
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Coarse category — ``action_record`` / ``approval`` / ``checkpoint``
    # / ``aggregate_metric``. Lets the dashboard filter by data class
    # without parsing the endpoint string.
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL for aggregate-list reads (which expose no single record).
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Wave 3B.3 — number of records returned for list reads. NULL for
    # single-record reads (``resource_id`` set) and for legacy rows
    # written before the column existed. The pair (resource_id IS NULL,
    # resource_count = N) is the canonical "list-of-N" shape; the pair
    # (resource_id = X, resource_count IS NULL) is the canonical
    # "single-record" shape. Customer dashboards rendering the
    # who-read-my-data surface key off these two shapes.
    resource_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Whether PHI was redacted in the response. Always TRUE for v1
    # (STAFF_READ_ONLY is the only staff tier we ship). Kept as a column
    # so a future STAFF_FULL break-glass tier can write rows with
    # ``redacted=False`` and the audit surface differentiates them.
    redacted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true(), default=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
