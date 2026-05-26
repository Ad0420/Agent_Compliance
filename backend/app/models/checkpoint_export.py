"""CheckpointExport — idempotency + audit row for the customer S3 mirror.

Phase 3 Wave 3B.1. Every time the checkpoint exporter touches a customer's
off-Vera S3 mirror it writes a row here: success, failure, or skipped.
This serves three purposes:

  1. **Idempotency.** Before pushing a checkpoint to S3 the exporter
     SELECTs from this table for an existing ``status='success'`` row;
     if one exists, the export is short-circuited. Critical for the
     "sweeper restarts mid-tick" case where the in-process strong-ref
     set is gone.

  2. **Forensic record.** Customer compliance teams can query
     ``SELECT * FROM checkpoint_exports WHERE org_id=? ORDER BY exported_at
     DESC`` to see exactly what evidence Vera has pushed to their bucket
     and when.

  3. **Ops triage.** Failure rows carry a structured ``reason`` (e.g.
     ``object_lock_missing``, ``bucket_not_configured``,
     ``credentials_unavailable``) plus free-form ``error_detail`` so a
     pager-duty incident can be triaged without re-running the job.

Status values
-------------
* ``success``  — JSON document landed in S3 with Object Lock COMPLIANCE
                 mode + retain-until date 7 years out.
* ``failure``  — Boto3 call raised; ``reason`` carries the structured
                 code (see ``services.checkpoint_export`` for the
                 closed set).
* ``skipped``  — Exporter ran but decided not to push (e.g. org has no
                 ``s3_export_arn`` configured). Kept as a real row so
                 ops can prove "we considered exporting and chose not
                 to" rather than silently no-oping.

Schema notes
------------
* The unique-on-success-per-checkpoint invariant is enforced at the
  application layer (savepoint-protected SELECT-then-INSERT inside
  the exporter). A partial unique index would be cleaner but isn't
  portable to SQLite without raw SQL.
* ``s3_location`` is ``bucket/key`` only for success rows; failure /
  skipped rows leave it NULL.
* ``document_hash`` is the SHA-256 of the canonical-JSON document body
  — lets customers verify what Vera wrote without trusting S3
  round-trip.
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
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# Single source of truth for the allowed status values. Imported by the
# exporter service so the route + service + migration CHECK all agree.
#
# ``pending`` is the row state between scheduling and S3 round-trip
# completion. We write the pending row BEFORE the boto3 call so a
# process crash mid-flight leaves a forensic row rather than a silent
# gap. Ops can query "pending older than N minutes" to find lost
# exports and retry.
EXPORT_STATUSES: tuple[str, ...] = (
    "pending",
    "success",
    "failure",
    "skipped",
)


class CheckpointExport(Base):
    __tablename__ = "checkpoint_exports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'success', 'failure', 'skipped')",
            name="ck_checkpoint_exports_status",
        ),
        # Idempotency hot path — used by every exporter call to ask
        # "have we already exported checkpoint X?".
        Index("idx_checkpoint_exports_checkpoint_id", "checkpoint_id"),
        # Ops query — "show me failed exports for org X."
        Index(
            "idx_checkpoint_exports_org_status",
            "org_id",
            "status",
            "exported_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    checkpoint_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("checkpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    s3_location: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )
    document_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    record_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exported_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
