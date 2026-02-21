import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="organization")
    action_records: Mapped[list["ActionRecord"]] = relationship(
        "ActionRecord", back_populates="organization"
    )
    api_keys: Mapped[list["APIKey"]] = relationship("APIKey", back_populates="organization")
    chain_state: Mapped["ChainState"] = relationship(
        "ChainState", back_populates="organization", uselist=False
    )
    checkpoints: Mapped[list["Checkpoint"]] = relationship(
        "Checkpoint", back_populates="organization"
    )
