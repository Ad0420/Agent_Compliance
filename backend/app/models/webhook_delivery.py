"""Webhook delivery — the parent row for one logical event delivery.

A ``WebhookDelivery`` is one (subscription, event) pair. It is the
scheduling/dedupe anchor for the retry pipeline. Each *attempt* is a
child ``WebhookDeliveryAttempt`` row (append-only).

See Wave 2B A3 plan §2 for the two-table rationale (Sidekiq / Oban
pattern). The sweeper only locks the parent row; children never
contend.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# Terminal + transient statuses. ``in_progress`` carries a soft lease
# (``locked_until``/``locked_by``) so a crashed sweeper instance does not
# orphan rows. See services/webhook_sweeper.py.
DELIVERY_STATUSES: tuple[str, ...] = (
    "pending",
    "in_progress",
    "succeeded",
    "aborted",
)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # Idempotency anchor — the producer side uses an INSERT…ON CONFLICT
        # DO NOTHING (or savepoint+IntegrityError on SQLite) keyed on
        # (subscription_id, idempotency_key) so double-emission is a no-op.
        UniqueConstraint(
            "subscription_id",
            "idempotency_key",
            name="uq_webhook_deliveries_sub_idem",
        ),
        # Sweeper's primary lookup. Postgres gets a partial index in the
        # migration; the in-model definition is the plain composite so
        # SQLite's create_all path matches the migration's SQLite branch.
        Index(
            "idx_webhook_deliveries_next_retry_at",
            "status",
            "next_retry_at",
        ),
        # Dashboard's "recent deliveries for a subscription" view.
        Index(
            "idx_webhook_deliveries_subscription",
            "subscription_id",
            "created_at",
        ),
    )

    # ``id`` doubles as the customer-facing ``event_id`` sent in the
    # webhook envelope. One UUID per logical event-to-subscriber; survives
    # every retry.
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the subscription row so the sweeper's hot query
    # doesn't need a join. Keeps cross-org isolation auditable in raw SQL.
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # NULL once the row is terminal (succeeded / aborted). The sweeper
    # filters on ``status='pending' AND next_retry_at <= now`` so a NULL
    # here is *not* a "due now" signal — it means "no more attempts".
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    # Soft lease — sweeper-instance-scoped. Reclaim-on-expiry handles a
    # crashed in_progress row.
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    locked_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    succeeded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    aborted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_status_code: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Defaults to ``id`` for non-review events; ``f"{approval_id}:{event_type}"``
    # for ``review.*``. Producer-side double dispatch becomes a no-op via the
    # composite unique index above.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    attempts: Mapped[list["WebhookDeliveryAttempt"]] = relationship(
        "WebhookDeliveryAttempt",
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="WebhookDeliveryAttempt.attempt_number",
    )
