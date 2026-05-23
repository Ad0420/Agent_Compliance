import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        # Phase 1 PR 1: ``kind`` splits keys into sandbox vs production.
        # BAA-gating on ``kind='live'`` lands in Phase 1 PR 4 — this PR only
        # stands up the column + check + index.
        CheckConstraint("kind IN ('test', 'live')", name="ck_api_keys_kind"),
        Index("idx_api_keys_org_kind", "org_id", "kind"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    permissions: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: ["write", "read"]
    )
    # Phase 1 PR 1: ``test`` (al_test_*) vs ``live`` (al_live_*). Existing
    # keys backfilled to ``test`` per migration n4h5i6j7k8l9.
    kind: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="test", default="test"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="api_keys")

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            # SQLite returns naive datetimes; treat them as UTC for comparison.
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                return False
        return True
