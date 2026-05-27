"""GeneratedAuditPdf — append-only history row per ``POST /v1/audits`` render.

Phase 4 Wave 2 C4. Every successful audit PDF render writes one row here
so the Customer detail page can list past renders and offer a
Re-download action.

Storage decision (v1)
---------------------
We do NOT persist the rendered PDF bytes. Re-download regenerates from
scratch using the persisted ``(date_from, date_to, sections_json,
branding)`` tuple. The ``pdf_storage_url`` column is reserved for a
future v1.x switch to S3 mirroring; NULL for every v1 row.

Append-only at the application layer
------------------------------------
No route mutates rows after insert. The list and regenerate endpoints
are read-only and re-render from the persisted parameters respectively.
No DELETE in v1 — operators can't strike audit history. That's a
regulator-readiness feature (HIPAA § 164.312(b) audit-control retention).

Identity capture
----------------
``generated_by_user_id`` and ``generated_by_api_key_id`` are BOTH
nullable. Exactly one is populated per row (enforced at the write
site, not the DB):

  * Clerk session → ``generated_by_user_id`` = Clerk ``sub`` claim.
  * API key path → ``generated_by_api_key_id`` = APIKey row id.

We do NOT FK the api-key id because keys can be revoked + cleaned but
the history row should outlive the credential.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GeneratedAuditPdf(Base):
    __tablename__ = "generated_audit_pdfs"
    __table_args__ = (
        # Dashboard hot path: list this Customer's audit PDFs newest
        # first. Postgres scans this in DESC order without an explicit
        # DESC clause — SQLite likewise.
        Index(
            "idx_generated_audit_pdfs_customer_generated",
            "customer_id",
            "generated_at",
        ),
        # Future ops query: "all audit PDFs generated for org X in the
        # last 30 days." Not used by the v1 dashboard but cheap.
        Index(
            "idx_generated_audit_pdfs_org_generated",
            "org_id",
            "generated_at",
        ),
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
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Clerk user id (sub claim) for Clerk-session renders. NULL for
    # API-key renders. We don't FK because Clerk identities live outside
    # the backend DB.
    generated_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # APIKey.id (UUID) for API-key renders. NULL for Clerk renders. No
    # FK — keys can be revoked + cleaned but the history row should
    # outlive the credential.
    generated_by_api_key_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    date_from: Mapped[date_cls] = mapped_column(Date, nullable=False)
    date_to: Mapped[date_cls] = mapped_column(Date, nullable=False)
    # JSON list of section keys (e.g. ["cover", "scope", ...]). Typed
    # ``Any`` here because SQLAlchemy's JSON column returns Python
    # ``Any`` — the API layer narrows it to ``list[str]`` on response.
    sections_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    # "customer" or "vera-neutral". String not ENUM so adding a third
    # branding option doesn't require a migration.
    branding: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # NULL in v1. Reserved for a future S3-mirror switch.
    pdf_storage_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )
