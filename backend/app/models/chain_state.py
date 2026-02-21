import uuid
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class ChainState(Base):
    __tablename__ = "chain_state"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    latest_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latest_hash: Mapped[str] = mapped_column(String, nullable=False, default="GENESIS")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="chain_state"
    )
