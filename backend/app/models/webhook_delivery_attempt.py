"""Webhook delivery attempt — append-only audit trail for HTTP tries.

One row per HTTP attempt. Never updated after insert. The sweeper updates
the parent ``WebhookDelivery`` row only; ``WebhookDeliveryAttempt`` is
purely additive so it never contends for locks.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WebhookDeliveryAttempt(Base):
    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        # One row per (delivery, attempt_number). Tests use this to assert
        # exactly-once retry accounting.
        UniqueConstraint(
            "delivery_id",
            "attempt_number",
            name="uq_webhook_delivery_attempts_delivery_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    delivery_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1-indexed. ``attempt_number == 1`` is the initial in-process delivery
    # the producer schedules; the sweeper produces 2..MAX_ATTEMPTS.
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # ``None`` on transport-level failure (DNS, connect timeout, etc.). The
    # ``error_message`` column carries the ``repr(exc)`` in that case.
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # First 1 KB of the customer's response body. Hard truncate — we never
    # store more, because the audit trail is for triage, not content.
    response_body_excerpt: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Snapshot of the *scheduled* next retry. NULL if this attempt
    # succeeded or exhausted the retry budget.
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    delivery: Mapped["WebhookDelivery"] = relationship(
        "WebhookDelivery", back_populates="attempts"
    )
