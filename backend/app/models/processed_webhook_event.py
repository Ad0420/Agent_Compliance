"""Dedupe table for Clerk (and future inbound) webhook events.

Svix delivers events at-least-once: the same ``svix-id`` may arrive twice
if our handler crashes mid-processing or returns slowly enough to trip a
retry. We store the event ID here and use INSERT … ON CONFLICT DO NOTHING
semantics — if the row already exists, the handler treats the delivery as
a replay and returns 200 OK without re-applying side effects.

We do NOT re-use ``idempotency_records``: that table is keyed by
``(org_id, key)`` and assumes the caller already has an org context. A
Clerk webhook may arrive before the backend org exists (the very event
that creates it), so there's no org to scope the dedupe by.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProcessedWebhookEvent(Base):
    __tablename__ = "processed_webhook_events"

    # The Svix message ID (``svix-id`` header). Globally unique per Clerk
    # message; primary key is sufficient for the dedupe primitive.
    svix_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Event type at processing time — kept for forensics, not used for dedupe.
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # ``True`` once the handler ran without raising. ``False`` rows are
    # retained for operator visibility but are NOT treated as deduped —
    # Svix retries are allowed to retry the handler. Deterministically-broken
    # handlers therefore eventually exhaust the Svix retry budget instead of
    # infinite-retrying (the row stays as a tombstone for investigation).
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
