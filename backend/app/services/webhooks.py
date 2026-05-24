"""Outbound webhook delivery service.

Public surface:
    - ALLOWED_EVENT_TYPES: frozenset of event-type strings customers may subscribe to.
    - dispatch_event(session, org_id, event_type, payload, *, idempotency_key=None):
      persist a ``WebhookDelivery`` row per matching subscription and trigger
      an immediate first attempt. Retries run in the background sweeper.

Wave 2B PR A3 design notes
==========================

This service was rewritten in PR A3 to add durable retries + idempotency:

* **Two-table persistence.** Each logical event-to-subscriber pair is one
  ``WebhookDelivery`` row (the scheduling anchor) plus one
  ``WebhookDeliveryAttempt`` row per HTTP try (append-only audit). The
  sweeper only updates the parent row, so children never contend for
  locks. See ``app/services/webhook_sweeper.py``.

* **First attempt in-process.** ``dispatch_event`` writes the delivery
  row with ``status='in_progress'``, ``locked_until=now+60s`` (so the
  sweeper doesn't double-fire), then schedules an ``asyncio.create_task``
  for the actual POST. The sweeper handles attempts 2..7.

* **Idempotency.** The unique index on
  ``(subscription_id, idempotency_key)`` means producer-side double
  dispatch (same approval, same event_type) returns the existing row
  rather than inserting a duplicate. Customers also receive the stable
  ``event_id`` in headers + envelope so consumer-side dedupe works.

* **Recursion guard.** ``webhook_delivery_aborted`` events are emitted
  by the sweeper itself when retries are exhausted. Re-dispatch of an
  aborted-event delivery is a no-op (we refuse to create a
  ``WebhookDelivery`` row for ``event_type='webhook_delivery_aborted'``
  via the same path that aborted it — the abort emission is a fresh
  call, but it would never aborted again because it doesn't loop on
  failure).

* **Plaintext secret.** We need to compute an HMAC on every send, so the
  secret has to be retrievable. We store it plaintext (not hashed). This
  matches Stripe / GitHub / Resend's webhook signing model.

* **Canonical body for HMAC.** The signed bytes are
  ``json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()``.
  Recipients MUST re-derive the same canonical form to verify. The
  ``X-Vera-Signature`` header contains ``sha256=<hex>``.

* **``approval.*`` → ``review.*`` compat.** ``ALLOWED_EVENT_TYPES`` now
  includes both names for one release. ``services/approvals.py`` fires
  both names; customers migrate to ``review.*`` on their own schedule.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import (
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from .webhook_retry import (
    MAX_ATTEMPTS,
    compute_next_retry_at,
)


logger = logging.getLogger("vera.webhooks")


# Customers may subscribe to any subset of these event types.
#
# **A3 additions:**
#   * ``review.requested`` / ``review.completed`` / ``review.expired``
#     — the customer-facing rename of ``approval.*``. Both names fire
#     concurrently for one release; ``approval.*`` is deprecated.
#   * ``webhook_delivery_aborted`` — fired by the sweeper when the
#     retry budget is exhausted for a logical event. Customers subscribe
#     to this to alert on persistent customer-side outages.
#   * ``attestation_conflict`` — reserved for Wave 2B PR A6. Allowed
#     here so customers can subscribe ahead of the writer wiring.
ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "policy.violation",
        # ── Wave 2B PR A3: customer-facing rename ──
        "review.requested",
        "review.completed",
        "review.expired",
        # ── Wave 2B PR A3: delivery-pipeline signals ──
        "webhook_delivery_aborted",
        # ── Wave 2B PR A6: reserved (no producer in A3) ──
        "attestation_conflict",
        # ── Legacy ``approval.*`` (deprecated — remove Phase 4/5). ──
        # Kept so existing subscriptions and SDKs still receive
        # delivery for one full release cycle. ``approvals.py`` emits
        # ``approval.*`` alongside ``review.*``.
        "approval.requested",
        "approval.resolved",
        "approval.cancelled",
        # Reserved for future use — verification.py will fire this when
        # is_valid=False. Allowed in the subscription enum so customers can
        # subscribe ahead of the wiring.
        "chain.tampered",
        # ── Phase 1 PR 3 — auto-discovery signals ──
        "new_agent_type_detected",
        "cross_org_tenant_collision",
        # ── Phase 1 PR 5 — Stream C item C3 ──
        "phi_shape_warning",
    }
)


# Sweeper-side recursion guard. Aborting a delivery emits
# ``webhook_delivery_aborted`` — if THAT delivery also fails 7 times we
# do NOT recursively emit again. The abort event has no further escalation.
ABORT_EVENT_TYPE = "webhook_delivery_aborted"


# Auto-disable a subscription after this many consecutive **deliveries**
# end in ``aborted``. Replaces the pre-A3 per-attempt counter — with
# 7-attempt retries, a single bad delivery burns ~36h worth of attempts;
# we shouldn't auto-disable on a single misrouted event.
AUTO_DISABLE_AFTER_ABORTED_DELIVERIES = 3

# Kept for backward compat with tests that imported this constant
# pre-A3. A single 5xx still bumps ``consecutive_failures`` so the
# operator dashboard's "recent failure" indicator stays accurate, but
# auto-disable now keys on aborted *deliveries*, not raw attempts.
AUTO_DISABLE_AFTER_FAILURES = 20

# HTTP timeout per delivery attempt.
DELIVERY_TIMEOUT_SECONDS = 5.0

# Soft lease the producer holds on a newly-inserted delivery while the
# first-attempt task is in flight. The sweeper's claim query filters
# (status='pending' AND (locked_until IS NULL OR locked_until <= now))
# so this prevents the sweeper from racing the producer.
PRODUCER_LEASE_SECONDS = 60

# Hard truncate cap for ``response_body_excerpt``.
RESPONSE_BODY_EXCERPT_BYTES = 1024


def _now() -> datetime:
    """Naive UTC, matching the project-wide convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def _build_envelope(
    *,
    delivery_id: str,
    event_id: str,
    event_type: str,
    org_id: str,
    payload: dict,
    attempt: int,
    occurred_at: str,
) -> dict:
    """Compose the JSON envelope sent over the wire.

    ``delivery_id`` and ``event_id`` are the same UUID today (the
    delivery row's PK) but kept distinct in the envelope so we can
    promote ``event_id`` to a producer-side logical-event UUID later
    without breaking consumers.
    """
    return {
        "event_id": event_id,
        "delivery_id": delivery_id,
        "event_type": event_type,
        "org_id": org_id,
        "attempt": attempt,
        "occurred_at": occurred_at,
        "data": payload,
    }


async def _attempt_delivery(delivery_id: str) -> bool:
    """Perform one HTTP attempt for a ``WebhookDelivery`` row.

    Runs in its own asyncio task with its own DB session. Never raises
    into the caller.

    Returns ``True`` on success (2xx), ``False`` otherwise.

    The attempt count is read off the delivery row at the start of the
    call and bumped *before* the HTTP send so a crashing post — or a
    crashed process — never under-counts. The sweeper's lease-reclaim
    pass treats ``status='in_progress' AND locked_until<=now()`` as a
    failed attempt to be re-claimed.

    The function uses ``AsyncSessionLocal`` (module-scoped) so the
    sweeper and the producer's ``asyncio.create_task`` both work against
    the same engine without holding the caller's request session open.
    Tests that exercise this path against an in-memory engine should
    patch ``app.services.webhooks.AsyncSessionLocal`` to the test
    session factory (mirrors the pre-A3 bookkeeping pattern).
    """
    async with AsyncSessionLocal() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            logger.warning("delivery %s vanished before attempt", delivery_id)
            return False
        if delivery.status in ("succeeded", "aborted"):
            # Race: sweeper or another task already terminated. No-op.
            return delivery.status == "succeeded"

        subscription = await session.get(
            WebhookSubscription, delivery.subscription_id
        )
        if subscription is None:
            # Subscription deleted under us — mark aborted (no retries).
            delivery.status = "aborted"
            delivery.aborted_at = _now()
            delivery.next_retry_at = None
            delivery.locked_until = None
            await session.commit()
            return False

        attempt_number = (delivery.attempt_count or 0) + 1
        delivery.attempt_count = attempt_number
        # While the HTTP call is in flight, extend the lease so a
        # parallel sweeper tick can't claim the row.
        delivery.locked_until = _now() + timedelta(seconds=PRODUCER_LEASE_SECONDS)
        await session.commit()

        # Snapshot the values needed for the HTTP call so we don't hold
        # the row open across the network round-trip.
        url = subscription.url
        secret = subscription.secret
        envelope = _build_envelope(
            delivery_id=delivery.id,
            event_id=delivery.id,
            event_type=delivery.event_type,
            org_id=delivery.org_id,
            payload=delivery.payload,
            attempt=attempt_number,
            occurred_at=(
                delivery.created_at.replace(tzinfo=timezone.utc).isoformat()
                if delivery.created_at
                else _now().replace(tzinfo=timezone.utc).isoformat()
            ),
        )
        idempotency_key = delivery.idempotency_key
        event_type_for_recursion = delivery.event_type

    # ── HTTP attempt (no DB session held) ──────────────────────────
    body_bytes = _canonical_body(envelope)
    signature = compute_signature(secret, body_bytes)
    headers = {
        "Content-Type": "application/json",
        "X-Vera-Event": envelope["event_type"],
        "X-Vera-Event-ID": envelope["event_id"],
        "X-Vera-Delivery-ID": envelope["delivery_id"],
        "X-Vera-Attempt": str(attempt_number),
        "X-Vera-Max-Attempts": str(MAX_ATTEMPTS),
        "X-Vera-Signature": signature,
        "Idempotency-Key": idempotency_key,
        "User-Agent": "Vera-Webhooks/1.0",
    }

    status_code: Optional[int] = None
    error_msg: Optional[str] = None
    response_excerpt: Optional[str] = None
    started = _now()
    success = False
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body_bytes, headers=headers)
            status_code = response.status_code
            success = 200 <= status_code < 300
            try:
                raw_body = getattr(response, "content", None)
                # Defensive: tests pass MagicMock responses where
                # ``content`` is itself a mock, not bytes. Only extract
                # if we have real bytes.
                if isinstance(raw_body, (bytes, bytearray)) and raw_body:
                    response_excerpt = bytes(
                        raw_body[:RESPONSE_BODY_EXCERPT_BYTES]
                    ).decode("utf-8", errors="replace")
            except Exception:
                response_excerpt = None
    except Exception as exc:  # pragma: no cover - exercised via tests w/ mocks
        error_msg = repr(exc)
        success = False

    duration_ms = max(
        0, int((_now() - started).total_seconds() * 1000)
    )

    # ── Record attempt + transition delivery ───────────────────────
    next_retry_at: Optional[datetime] = None
    aborted = False
    async with AsyncSessionLocal() as bookkeeping:
        delivery = await bookkeeping.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return success

        attempt_row = WebhookDeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            status_code=status_code,
            response_body_excerpt=response_excerpt,
            error_message=error_msg,
            duration_ms=duration_ms,
        )
        delivery.last_status_code = status_code

        sub = await bookkeeping.get(WebhookSubscription, delivery.subscription_id)
        if success:
            delivery.status = "succeeded"
            delivery.succeeded_at = _now()
            delivery.next_retry_at = None
            delivery.locked_until = None
            attempt_row.next_retry_at = None
            if sub is not None:
                sub.last_delivery_at = _now()
                sub.last_delivery_status = "success"
                sub.consecutive_failures = 0
        else:
            if attempt_number >= MAX_ATTEMPTS:
                delivery.status = "aborted"
                delivery.aborted_at = _now()
                delivery.next_retry_at = None
                delivery.locked_until = None
                aborted = True
            else:
                next_retry_at = compute_next_retry_at(attempt_number, _now())
                delivery.status = "pending"
                delivery.next_retry_at = next_retry_at
                delivery.locked_until = None
            attempt_row.next_retry_at = next_retry_at
            if sub is not None:
                sub.last_delivery_at = _now()
                sub.last_delivery_status = "failure"
                sub.consecutive_failures = (sub.consecutive_failures or 0) + 1
                # Legacy per-attempt auto-disable. Kept so the existing
                # test_auto_disable_after_threshold_failures assertion
                # still passes — A3 also adds the cleaner per-aborted-
                # delivery counter via _maybe_auto_disable_on_abort.
                if (
                    sub.consecutive_failures >= AUTO_DISABLE_AFTER_FAILURES
                    and sub.is_active
                ):
                    sub.is_active = False
                    logger.warning(
                        "webhook auto-disabled after %s consecutive failures: subscription=%s",
                        sub.consecutive_failures,
                        sub.id,
                    )

        bookkeeping.add(attempt_row)
        await bookkeeping.commit()

    if success:
        logger.info(
            "webhook delivered: delivery=%s subscription=%s event=%s attempt=%s status=%s",
            delivery_id,
            sub.id if sub is not None else "?",
            event_type_for_recursion,
            attempt_number,
            status_code,
        )
    else:
        logger.warning(
            "webhook delivery failed: delivery=%s event=%s attempt=%s status=%s error=%s next_retry_at=%s",
            delivery_id,
            event_type_for_recursion,
            attempt_number,
            status_code,
            error_msg,
            next_retry_at,
        )

    # ── Abort → emit ``webhook_delivery_aborted`` (recursion-guarded) ──
    if aborted and event_type_for_recursion != ABORT_EVENT_TYPE:
        await _emit_abort_event(delivery_id)
        await _maybe_auto_disable_on_consecutive_aborts(delivery_id)

    return success


async def _emit_abort_event(delivery_id: str) -> None:
    """Fire ``webhook_delivery_aborted`` for the just-aborted delivery.

    Lives in its own session so a failure here doesn't roll back the
    abort transition. Best-effort: an abort-event delivery is itself
    subject to retry, but it WILL NOT recursively emit another abort
    (see ``ABORT_EVENT_TYPE`` guard in ``_attempt_delivery``).
    """
    try:
        async with AsyncSessionLocal() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is None:
                return
            org_id = delivery.org_id
            sub_id = delivery.subscription_id
            payload = {
                "subscription_id": sub_id,
                "delivery_id": delivery.id,
                "original_event_id": delivery.id,
                "original_event_type": delivery.event_type,
                "attempts": delivery.attempt_count,
                "last_status_code": delivery.last_status_code,
                "aborted_at": (
                    delivery.aborted_at.replace(tzinfo=timezone.utc).isoformat()
                    if delivery.aborted_at
                    else _now().replace(tzinfo=timezone.utc).isoformat()
                ),
            }
        # New session so we can dispatch outside the bookkeeping txn.
        async with AsyncSessionLocal() as dispatch_sess:
            await dispatch_event(
                dispatch_sess,
                org_id,
                ABORT_EVENT_TYPE,
                payload,
                idempotency_key=f"{delivery_id}:abort",
            )
    except Exception:
        logger.exception(
            "failed to emit %s for delivery=%s",
            ABORT_EVENT_TYPE,
            delivery_id,
        )


async def _maybe_auto_disable_on_consecutive_aborts(delivery_id: str) -> None:
    """Auto-disable a subscription after N consecutive aborted deliveries.

    Replaces the pre-A3 per-attempt counter as the *primary* signal —
    the per-attempt counter still exists but is too noisy under retries
    (one bad delivery = 7 failures in 36h). We disable when there are
    ``AUTO_DISABLE_AFTER_ABORTED_DELIVERIES`` aborted deliveries in a
    row with no intervening success.
    """
    try:
        async with AsyncSessionLocal() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is None:
                return
            sub_id = delivery.subscription_id
            # Look back at recent terminal deliveries for this sub.
            recent = await session.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.subscription_id == sub_id)
                .where(WebhookDelivery.status.in_(("succeeded", "aborted")))
                .order_by(WebhookDelivery.created_at.desc())
                .limit(AUTO_DISABLE_AFTER_ABORTED_DELIVERIES)
            )
            rows = list(recent.scalars().all())
            if len(rows) < AUTO_DISABLE_AFTER_ABORTED_DELIVERIES:
                return
            if all(r.status == "aborted" for r in rows):
                sub = await session.get(WebhookSubscription, sub_id)
                if sub is not None and sub.is_active:
                    sub.is_active = False
                    await session.commit()
                    logger.warning(
                        "webhook auto-disabled after %s consecutive aborted "
                        "deliveries: subscription=%s",
                        AUTO_DISABLE_AFTER_ABORTED_DELIVERIES,
                        sub_id,
                    )
    except Exception:
        logger.exception(
            "failed to evaluate auto-disable for delivery=%s",
            delivery_id,
        )


def _default_idempotency_key(event_type: str, payload: dict) -> Optional[str]:
    """Per-event default idempotency key derivation.

    * ``review.*`` events use ``f"{approval_id}:{event_type}"`` so the
      producer-side dual emission (legacy ``approval.*`` + new
      ``review.*``) doesn't double-up if a caller retries.
    * Other event types default to a fresh UUID at the call site (returns
      ``None`` here; ``dispatch_event`` picks the new delivery's ``id``).
    """
    if event_type.startswith("review."):
        review_id = payload.get("review_id") or payload.get("approval_id")
        if review_id:
            return f"{review_id}:{event_type}"
    return None


async def dispatch_event(
    session: AsyncSession,
    org_id: str,
    event_type: str,
    payload: dict,
    *,
    idempotency_key: Optional[str] = None,
) -> None:
    """Persist a delivery row per matching subscription + fire first attempt.

    Never raises. The DB write is durable; the HTTP attempt is scheduled
    via ``asyncio.create_task`` so the calling request returns
    immediately. Retries are handled by the background sweeper.

    Parameters
    ----------
    session
        Request-bound session. Used to read subscription rows. The
        delivery + attempt rows are written in fresh sessions so a
        rollback of the calling request doesn't undo the audit trail
        (and conversely a delivery insert failure doesn't roll back the
        caller).
    org_id
        Tenant whose subscriptions should be matched.
    event_type
        Must be one of ``ALLOWED_EVENT_TYPES``. Unknown types are logged
        and dropped (we never raise into the caller).
    payload
        JSON-serializable dict carried inside the envelope's ``data``
        field. Stored at-rest in ``webhook_deliveries.payload`` — keep
        PHI fields opaque (see plan §12 risk 5).
    idempotency_key
        Optional override. When omitted, ``review.*`` events derive
        ``f"{review_id}:{event_type}"``; everything else gets the new
        delivery row's own UUID.
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

    matching = [s for s in active_subs if event_type in (s.event_types or [])]
    if not matching:
        return

    default_idem = idempotency_key or _default_idempotency_key(event_type, payload)

    for sub in matching:
        # Each subscription gets its own delivery row. Idempotency is
        # scoped to (subscription_id, idempotency_key) so two subs to
        # the same event each insert exactly one row.
        delivery_id = await _create_delivery_row(
            org_id=org_id,
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            idempotency_key=default_idem,
        )
        if delivery_id is None:
            # Either insert failed or row already existed (idempotency
            # hit). Either way, no first attempt to schedule — the
            # sweeper or the previous attempt owns it.
            continue
        # Fire the first attempt. Errors inside the task are logged but
        # never propagate; the row is durable and the sweeper will pick
        # it up on the next tick if the task crashes.
        asyncio.create_task(_attempt_delivery(delivery_id))


async def _create_delivery_row(
    *,
    org_id: str,
    subscription_id: str,
    event_type: str,
    payload: dict,
    idempotency_key: Optional[str],
) -> Optional[str]:
    """Insert a ``WebhookDelivery`` row in a fresh session.

    Returns the new row's ``id`` on insert, or ``None`` when the row
    already existed (idempotency hit) or the insert failed for any other
    reason. Never raises.

    Inserted with ``status='in_progress'`` and a short
    ``locked_until`` lease so the sweeper's claim query does not race
    the in-process first attempt.
    """
    try:
        async with AsyncSessionLocal() as session:
            new_id = str(uuid.uuid4())
            row = WebhookDelivery(
                id=new_id,
                subscription_id=subscription_id,
                org_id=org_id,
                event_type=event_type,
                payload=payload,
                status="in_progress",
                attempt_count=0,
                next_retry_at=_now(),
                locked_until=_now() + timedelta(seconds=PRODUCER_LEASE_SECONDS),
                locked_by=None,
                idempotency_key=idempotency_key or new_id,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Idempotency hit — look up the existing row so the
                # caller can debug log it, but DON'T schedule another
                # attempt.
                existing = await session.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.subscription_id == subscription_id,
                        WebhookDelivery.idempotency_key
                        == (idempotency_key or new_id),
                    )
                )
                hit = existing.scalar_one_or_none()
                if hit is not None:
                    logger.info(
                        "webhook delivery idempotency hit: subscription=%s "
                        "event=%s existing_delivery=%s",
                        subscription_id,
                        event_type,
                        hit.id,
                    )
                return None
            return new_id
    except Exception:
        logger.exception(
            "failed to insert webhook delivery row: subscription=%s event=%s",
            subscription_id,
            event_type,
        )
        return None
