"""Idempotency record model for deduplicating action writes.

The SDK generates a UUID4 ``Idempotency-Key`` per logical write and re-sends
the same key on retries. The server caches the (org_id, key) -> response_body
for 24 hours so duplicate requests replay the original response instead of
inserting a second action_records row with adjacent sequence numbers.

The composite uniqueness on ``(org_id, key)`` is the dedupe primitive.
``request_hash`` (SHA-256 of canonical JSON of the request body) lets the
route reject same-key/different-body misuse with HTTP 409.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_idem_org_key"),
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
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
