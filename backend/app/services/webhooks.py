"""Outbound webhook delivery service.

Public surface:
    - ALLOWED_EVENT_TYPES: frozenset of event-type strings customers may subscribe to.
    - dispatch_event(session, org_id, event_type, payload): fire-and-forget delivery
      to all matching active subscriptions for the org.

Design notes
============
* **No retries in v1.** A non-2xx response increments `consecutive_failures`.
  Twenty consecutive failures auto-disables the subscription. Customers
  re-enable via PATCH after fixing their endpoint.
* **Plaintext secret.** We need to compute an HMAC on every send, so the
  secret has to be retrievable. We store it plaintext (not hashed). This
  matches Stripe / GitHub / Resend's webhook signing model.
* **Canonical body for HMAC.** The signed bytes are
  ``json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()``.
  Recipients MUST re-derive the same canonical form to verify. The
  ``X-Vera-Signature`` header contains ``sha256=<hex>``.
* **Fire-and-forget.** ``dispatch_event`` schedules ``asyncio.create_task``
  per matching subscription and returns. The calling request is NOT blocked
  on HTTP delivery. Each delivery uses its own DB session because the
  request's session is gone by the time the task runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import WebhookSubscription


logger = logging.getLogger("vera.webhooks")


# Customers may subscribe to any subset of these event types.
ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "policy.violation",
        "approval.requested",
        "approval.resolved",
        "approval.cancelled",
        # Reserved for future use — verification.py will fire this when
        # is_valid=False. Allowed in the subscription enum so customers can
        # subscribe ahead of the wiring.
        "chain.tampered",
    }
)

# Auto-disable a subscription after this many consecutive failures.
AUTO_DISABLE_AFTER_FAILURES = 20

# HTTP timeout per delivery attempt.
DELIVERY_TIMEOUT_SECONDS = 5.0


def generate_webhook_secret() -> str:
    """Generate a fresh signing secret. URL-safe, ~43 chars."""
    return secrets.token_urlsafe(32)


def _canonical_body(envelope: dict) -> bytes:
    """Canonical JSON encoding used for HMAC signing.

    Recipients must re-derive this exact byte sequence to verify the
    signature. We use ``sort_keys=True`` and the most compact separators.
    """
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compute_signature(secret: str, body_bytes: bytes) -> str:
    """Return ``"sha256=<hex>"`` HMAC-SHA256 signature for the body."""
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


async def _deliver(
    subscription_id: str,
    url: str,
    secret: str,
    envelope: dict,
) -> None:
    """Single delivery attempt + bookkeeping.

    Runs in its own asyncio task with its own DB session. Never raises.
    """
    body_bytes = _canonical_body(envelope)
    signature = compute_signature(secret, body_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-Vera-Event": envelope["event_type"],
        "X-Vera-Event-ID": envelope["event_id"],
        "X-Vera-Signature": signature,
        "User-Agent": "Vera-Webhooks/1.0",
    }

    success = False
    status_code: Optional[int] = None
    error_msg: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body_bytes, headers=headers)
            status_code = response.status_code
            success = 200 <= status_code < 300
    except Exception as exc:  # pragma: no cover - exercised via tests w/ mocks
        error_msg = repr(exc)
        success = False

    if success:
        logger.info(
            "webhook delivered: subscription=%s event=%s status=%s",
            subscription_id,
            envelope["event_type"],
            status_code,
        )
    else:
        logger.warning(
            "webhook delivery failed: subscription=%s event=%s status=%s error=%s",
            subscription_id,
            envelope["event_type"],
            status_code,
            error_msg,
        )

    # Update bookkeeping in a fresh session.
    try:
        async with AsyncSessionLocal() as bookkeeping_session:
            sub = await bookkeeping_session.get(WebhookSubscription, subscription_id)
            if sub is None:
                # Subscription was deleted while delivery was in flight.
                return
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            sub.last_delivery_at = now
            if success:
                sub.last_delivery_status = "success"
                sub.consecutive_failures = 0
            else:
                sub.last_delivery_status = "failure"
                sub.consecutive_failures = (sub.consecutive_failures or 0) + 1
                if sub.consecutive_failures >= AUTO_DISABLE_AFTER_FAILURES:
                    sub.is_active = False
                    logger.warning(
                        "webhook auto-disabled after %s consecutive failures: subscription=%s",
                        sub.consecutive_failures,
                        subscription_id,
                    )
            await bookkeeping_session.commit()
    except Exception:
        logger.exception(
            "failed to update delivery bookkeeping for subscription=%s",
            subscription_id,
        )


async def dispatch_event(
    session: AsyncSession,
    org_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Fire-and-forget delivery to all matching active subscriptions.

    Never raises. Schedules HTTP work via ``asyncio.create_task`` so the
    calling request returns immediately.

    Parameters
    ----------
    session
        Request-bound session, used only to read the subscription rows.
        Each delivery task uses its own session for bookkeeping.
    org_id
        Tenant whose subscriptions should be matched.
    event_type
        Must be one of ``ALLOWED_EVENT_TYPES``. Unknown types are logged and
        dropped (we never raise into the caller).
    payload
        JSON-serializable dict carried inside the envelope's ``data`` field.
    """
    if event_type not in ALLOWED_EVENT_TYPES:
        logger.warning("dispatch_event called with unknown event_type=%s", event_type)
        return

    try:
        result = await session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.org_id == org_id,
                WebhookSubscription.is_active.is_(True),
            )
        )
        active_subs = list(result.scalars().all())
    except Exception:
        logger.exception(
            "failed to load webhook subscriptions for org=%s event=%s",
            org_id,
            event_type,
        )
        return

    # Filter event_types in Python — JSON-containment differs across
    # SQLite vs Postgres, and the row count per org is small.
    matching = [s for s in active_subs if event_type in (s.event_types or [])]
    if not matching:
        return

    occurred_at = datetime.now(timezone.utc).isoformat()
    for sub in matching:
        envelope = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "org_id": org_id,
            "occurred_at": occurred_at,
            "data": payload,
        }
        # Capture mutable fields locally to avoid races with row updates.
        asyncio.create_task(
            _deliver(
                subscription_id=sub.id,
                url=sub.url,
                secret=sub.secret,
                envelope=envelope,
            )
        )
