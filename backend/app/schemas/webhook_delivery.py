"""Pydantic schemas for the webhook delivery admin endpoints.

Wave 2B PR A3 ships a read-only admin surface so operators can triage
"why didn't my customer get this webhook?" without dropping into a DB
console. Two endpoints:

  * ``GET /v1/webhooks/{webhook_id}/deliveries`` — paginated list,
    newest first.
  * ``POST /v1/webhooks/{webhook_id}/deliveries/{delivery_id}/replay``
    — re-attempt a terminal delivery. Resets attempt_count to 0, flips
    status to pending, and lets the sweeper pick it up on the next tick.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WebhookDeliveryAttemptResponse(BaseModel):
    """One HTTP attempt in a delivery's history."""

    id: str
    attempt_number: int
    attempted_at: datetime
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    next_retry_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    """One ``WebhookDelivery`` row with its attempts."""

    id: str
    subscription_id: str
    event_type: str
    status: str
    attempt_count: int
    next_retry_at: Optional[datetime] = None
    created_at: datetime
    succeeded_at: Optional[datetime] = None
    aborted_at: Optional[datetime] = None
    last_status_code: Optional[int] = None
    idempotency_key: str
    attempts: list[WebhookDeliveryAttemptResponse] = []

    model_config = {"from_attributes": True}


class WebhookDeliveryListResponse(BaseModel):
    deliveries: list[WebhookDeliveryResponse]
    total: int


class WebhookDeliveryReplayResponse(BaseModel):
    """Returned by the replay endpoint."""

    id: str
    status: str
    attempt_count: int
    next_retry_at: Optional[datetime] = None
