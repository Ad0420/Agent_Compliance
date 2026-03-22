import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import JSON

from .base import Base


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sequence_at_checkpoint: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hash_at_checkpoint: Mapped[str] = mapped_column(Text, nullable=False)
    merkle_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    external_receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="checkpoints"
    )
