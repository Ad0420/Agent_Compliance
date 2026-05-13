"""Audit-of-the-audit-log model (Workstream F3).

Every action taken by a Clerk user with role ``compliance_reviewer`` is
recorded here. Compliance teams can prove their reviews happened.
Admin and developer actions are NOT recorded — only ``compliance_reviewer``
(per F3 in ``mvp-hardening-plan.md``).

The recorder lives in ``app.middleware.clerk_auth``:

  1. ``compliance_review_audit`` (dep): runs role gating, then stashes
     an audit context on ``request.state.compliance_audit_ctx`` when the
     active membership is a ``compliance_reviewer`` and the route hasn't
     opted out via ``exclude_path_audit=True``.
  2. ``ComplianceAuditMiddleware``: reads the context after the route
     returns, augments it with the REAL ``response.status_code``, and
     writes the row from a fresh DB session.

Failures inside the middleware are logged and swallowed so the audit-of-
audit never breaks the originating request.

PHI safety (post-PR #172 audit, CRITICAL #4):
  ``target_id``, ``http_path``, ``action`` are PHI-redacted by the dep:
  values from path-params known to carry patient IDs / subject IDs are
  HMAC-SHA-256-hashed with a per-org salt. ``query_params`` is allowlist-
  filtered. Same value within the same org → same hash, so analysts
  retain correlation power; raw PHI never lands in the audit table.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _crr_id() -> str:
    return f"crr_{secrets.token_urlsafe(16)}"


class ComplianceReviewRecord(Base):
    __tablename__ = "compliance_review_records"
    __table_args__ = (
        Index(
            "ix_compliance_review_records_org_occurred",
            "org_id",
            "occurred_at",
        ),
        Index(
            "ix_compliance_review_records_user_occurred",
            "clerk_user_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_crr_id)
    org_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # membership_id is NULLABLE + SET NULL on delete: when an org is deleted
    # by Clerk, the ``organization.deleted`` webhook hard-deletes all
    # ``org_memberships`` rows. The previous RESTRICT FK turned that into a
    # FK violation → webhook 500 → Clerk retries forever. SET NULL keeps the
    # audit row intact (which is the entire point of an audit-of-audit log)
    # while letting the membership go. Identity is still recoverable via
    # ``clerk_user_id`` below, which never gets NULLed.
    membership_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("org_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    clerk_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Use the generic JSON type rather than JSONB so SQLite (used in CI) can
    # store the same shape Postgres does. Postgres maps JSON → JSONB
    # implicitly via the SQLAlchemy variant when needed.
    query_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    response_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    http_method: Mapped[str] = mapped_column(String, nullable=False)
    http_path: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.utcnow()
    )
