"""Vera webhook receiver — in-band HITL (W2.1).

ScribeMD subscribes to Vera's webhook stream so the EHR can:

1. Render a Review Inbox row when an approval is requested
   (``approval.requested`` / ``review.requested``).
2. Resolve the matching pending encounter when the clinician (or anyone
   else with the right scope) attests via Vera's
   ``/v1/reviews/{id}/complete`` — Vera fires ``approval.resolved`` /
   ``review.completed`` back to confirm.
3. Mark the row expired when the approval times out
   (``review.expired``).

Wire contract: HMAC-SHA256 over the raw request body using the secret
stashed in ``SCRIBEMD_VERA_WEBHOOK_SECRET``. Signature carried in
``X-Vera-Signature`` as ``sha256=<hex>``. Bad signature → 401 with no
mutation. The webhook dispatcher canonicalises with sorted keys and
compact separators — see ``backend/app/services/webhooks._canonical_body``
in the Vera repo — but the receiver should HMAC the RAW bytes received,
which match canonical form byte-for-byte for genuine deliveries.

Idempotency: keyed on ``(approval_id, event_type)``. The same callback
redelivered → unique constraint hits → handler returns the existing
state instead of double-applying.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.customers.scribemd.backend.models import (
    Encounter,
    ProcessedWebhookEvent,
    ReviewInboxItem,
)


logger = logging.getLogger(__name__)


# Event-type aliases. We handle both the legacy ``approval.*`` payloads
# and the customer-facing ``review.*`` rename — Vera emits both in
# parallel for one release cycle. Treating them as aliases means we
# never double-apply when both arrive for the same logical event.
REQUESTED_EVENTS = frozenset({"approval.requested", "review.requested"})
COMPLETED_EVENTS = frozenset({"approval.resolved", "review.completed"})
EXPIRED_EVENTS = frozenset({"review.expired"})

ALL_HANDLED_EVENTS = REQUESTED_EVENTS | COMPLETED_EVENTS | EXPIRED_EVENTS


class SignatureError(Exception):
    """Raised when HMAC verification fails."""


def verify_signature(secret: str, body: bytes, signature_header: str) -> None:
    """Verify the ``X-Vera-Signature`` header against the raw body bytes.

    Vera's contract: header value is ``"sha256=<hex>"``; signature is
    HMAC-SHA256 of the canonical body bytes using the shared secret.

    Constant-time compare. Raises :class:`SignatureError` on any mismatch.
    """
    if not signature_header:
        raise SignatureError("missing X-Vera-Signature header")
    if not signature_header.startswith("sha256="):
        raise SignatureError(
            "X-Vera-Signature must use the 'sha256=<hex>' format"
        )
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    presented = signature_header.split("=", 1)[1]
    if not hmac.compare_digest(expected, presented):
        raise SignatureError("HMAC signature mismatch")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; tolerate trailing ``Z`` and naive ts."""
    if not value or not isinstance(value, str):
        return None
    try:
        # ``fromisoformat`` doesn't handle the trailing ``Z`` until 3.11.
        normalised = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        logger.warning("could not parse timestamp from webhook: %r", value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _approval_id_from_payload(event_type: str, data: dict) -> Optional[str]:
    """Pull the approval/review id off the event payload.

    ``approval.*`` carries ``approval_id``; ``review.*`` carries
    ``review_id``. They reference the same row.
    """
    if event_type in REQUESTED_EVENTS or event_type in COMPLETED_EVENTS:
        return data.get("approval_id") or data.get("review_id")
    if event_type in EXPIRED_EVENTS:
        return data.get("review_id") or data.get("approval_id")
    return None


async def _already_processed(
    session: AsyncSession, approval_id: str, event_type: str
) -> bool:
    """Check the idempotency ledger before we mutate."""
    stmt = select(ProcessedWebhookEvent).where(
        ProcessedWebhookEvent.approval_id == approval_id,
        ProcessedWebhookEvent.event_type == event_type,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _record_processed(
    session: AsyncSession,
    approval_id: str,
    event_type: str,
    event_id: Optional[str],
) -> bool:
    """Insert the idempotency ledger row. Returns False if the unique
    constraint fires (someone else got here first → caller treats as a
    no-op redelivery)."""
    row = ProcessedWebhookEvent(
        id=uuid.uuid4().hex,
        approval_id=approval_id,
        event_type=event_type,
        event_id=event_id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def _handle_requested(
    session: AsyncSession, approval_id: str, data: dict
) -> None:
    """Insert a pending Review Inbox row (or reuse the existing one)."""
    context = data.get("context_excerpt") or data.get("context") or {}
    encounter_id = None
    if isinstance(context, dict):
        encounter_id = context.get("encounter_id")

    existing = await session.get(ReviewInboxItem, approval_id)
    if existing is not None:
        # Same review re-announced — leave the row alone.
        return

    item = ReviewInboxItem(
        approval_id=approval_id,
        encounter_id=encounter_id if isinstance(encounter_id, str) else None,
        status="pending",
        risk_tier=data.get("risk_tier"),
        required_role=data.get("required_role"),
        action_name=data.get("action_name"),
        agent_name=data.get("agent_name"),
        data_subject_id=data.get("data_subject_id"),
        context_excerpt=context if isinstance(context, dict) else None,
        requested_at=_parse_iso(data.get("requested_at")),
        expires_at=_parse_iso(data.get("expires_at")),
    )
    session.add(item)


async def _handle_completed(
    session: AsyncSession, approval_id: str, data: dict
) -> None:
    """Flip the inbox row + downstream encounter to terminal state."""
    final_status = data.get("final_status") or data.get("status")
    if final_status not in {"approved", "rejected"}:
        # Vera shouldn't send anything else as a completion; defensive.
        logger.warning(
            "review.completed with unexpected final_status=%r approval=%s",
            final_status,
            approval_id,
        )
        return

    item = await session.get(ReviewInboxItem, approval_id)
    if item is not None:
        # Don't downgrade an already-resolved row — duplicate webhook.
        if item.status == "pending":
            item.status = final_status
            decisions = data.get("decisions") or []
            if isinstance(decisions, list) and decisions:
                last = decisions[-1]
                if isinstance(last, dict):
                    item.decided_by = last.get("reviewer_id") or last.get(
                        "approver"
                    )
                    item.decision_note = last.get("note") or last.get(
                        "comment"
                    )
                    item.decided_at = _parse_iso(last.get("decided_at"))
            if item.decided_at is None:
                item.decided_at = _parse_iso(data.get("resolved_at"))

    # Cascade to the encounter if we have a back-pointer.
    encounter_id = item.encounter_id if item is not None else None
    if encounter_id is None and isinstance(data.get("context"), dict):
        encounter_id = data["context"].get("encounter_id")
    if encounter_id:
        enc = await session.get(Encounter, encounter_id)
        if enc is not None and enc.status in {"running", "awaiting_approval"}:
            enc.status = "committed" if final_status == "approved" else "blocked"
            enc.last_event = (
                "chart_committed" if final_status == "approved" else "chart_blocked"
            )


async def _handle_expired(
    session: AsyncSession, approval_id: str, data: dict
) -> None:
    """Mark a pending review expired + return its encounter to scribe."""
    item = await session.get(ReviewInboxItem, approval_id)
    if item is not None and item.status == "pending":
        item.status = "expired"
        item.decided_at = _parse_iso(data.get("expired_at"))

    encounter_id = item.encounter_id if item is not None else None
    if encounter_id is None and isinstance(data.get("context"), dict):
        encounter_id = data["context"].get("encounter_id")
    if encounter_id:
        enc = await session.get(Encounter, encounter_id)
        if enc is not None and enc.status in {"running", "awaiting_approval"}:
            # "Returned to scribe" — the brief's language for an expired
            # review. We surface it as the same blocked terminal state
            # (no chart write) with a distinct last_event for the UI.
            enc.status = "blocked"
            enc.last_event = "review_expired"


async def handle_event(
    session: AsyncSession,
    *,
    event_type: str,
    event_id: Optional[str],
    payload: dict,
) -> dict:
    """Apply a verified webhook to the local store.

    Returns a structured response dict the route handler echoes back to
    Vera. ``{"status": "ok", "applied": bool, "reason": str | None}``.

    No exceptions for unknown event types — we return ``ignored`` so an
    over-eager subscription doesn't 500 the dispatcher. Unknown payloads
    are dropped (the idempotency ledger is not advanced) so a future
    fix-and-retry remains possible.
    """
    data = payload if isinstance(payload, dict) else {}

    if event_type not in ALL_HANDLED_EVENTS:
        return {"status": "ok", "applied": False, "reason": "event_ignored"}

    approval_id = _approval_id_from_payload(event_type, data)
    if not approval_id:
        return {"status": "ok", "applied": False, "reason": "no_approval_id"}

    if await _already_processed(session, approval_id, event_type):
        return {"status": "ok", "applied": False, "reason": "duplicate"}

    if not await _record_processed(session, approval_id, event_type, event_id):
        # Lost a unique-constraint race with a sibling request — same as
        # the explicit `_already_processed` branch.
        return {"status": "ok", "applied": False, "reason": "duplicate"}

    if event_type in REQUESTED_EVENTS:
        await _handle_requested(session, approval_id, data)
    elif event_type in COMPLETED_EVENTS:
        await _handle_completed(session, approval_id, data)
    elif event_type in EXPIRED_EVENTS:
        await _handle_expired(session, approval_id, data)

    await session.commit()
    return {"status": "ok", "applied": True, "reason": None}
