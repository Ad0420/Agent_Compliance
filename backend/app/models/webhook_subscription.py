"""Webhook subscription model — outbound delivery for compliance events.

Customers register a URL + secret + a list of event types. When a matching
event fires (policy violation, approval lifecycle, etc.), the dispatcher
posts a signed JSON envelope to the URL.

The signing secret is stored plaintext (NOT hashed) because the dispatcher
must be able to retrieve it to compute the HMAC signature on every send.
This mirrors how Stripe / GitHub / Resend handle webhook secrets — they're
operational tokens, not user credentials. The secret is returned exactly
once on creation and never exposed via list/get endpoints. Customers rotate
via the dedicated POST /v1/webhooks/{id}/rotate endpoint.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="ck_webhook_url_scheme",
        ),
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
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Plaintext signing secret. Returned ONCE on create; never exposed via
    # list/get endpoints. See module docstring for rationale.
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    event_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 'success' | 'failure' | None (never delivered)
    last_delivery_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
