"""POST /vera/webhooks — incoming Vera callbacks (W2.1 in-band HITL).

Public, unauthenticated route protected by HMAC signature verification.
The HMAC secret lives in ``SCRIBEMD_VERA_WEBHOOK_SECRET``; missing →
503 so a misconfigured deployment fails loud rather than trusting bad
payloads.

Idempotency on ``(approval_id, event_type)`` is enforced inside
``webhook_handler.handle_event``.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from simulator.customers.scribemd.backend.config import Settings, get_settings
from simulator.customers.scribemd.backend.db import get_session
from simulator.customers.scribemd.backend.webhook_handler import (
    SignatureError,
    handle_event,
    verify_signature,
)


logger = logging.getLogger(__name__)

# Hard cap on inbound webhook bodies. Vera's payloads are tiny (≤ a few KB
# for the redacted context excerpt + envelope); 64 KB is comfortably above
# the largest realistic delivery. Above this we 413 without reading the
# body so a malformed/malicious caller can't force us to buffer megabytes
# of bytes before HMAC verification.
MAX_WEBHOOK_BODY_BYTES = 64 * 1024


router = APIRouter(prefix="/vera/webhooks", tags=["vera-webhooks"])


@router.post("", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    session=Depends(get_session),
) -> dict:
    secret = settings.vera_webhook_secret
    if not secret:
        # No secret configured — fail closed. Operating without
        # signature verification would be a HIPAA-grade footgun: anyone
        # who knows the URL could plant fake "this review is approved"
        # callbacks and trigger a chart write.
        logger.error(
            "SCRIBEMD_VERA_WEBHOOK_SECRET is not set; refusing to "
            "accept webhook deliveries."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook_secret_not_configured",
        )

    # Reject oversized payloads BEFORE buffering them. Content-Length is
    # advisory, so we also bail out post-read if the actual byte length
    # exceeds the cap (Starlette streams chunks internally; a hostile
    # caller can lie about the header).
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_WEBHOOK_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="payload_too_large",
                )
        except ValueError:
            # Malformed header — let the body read decide.
            pass

    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="payload_too_large",
        )
    signature = request.headers.get("X-Vera-Signature", "")
    try:
        verify_signature(secret, raw, signature)
    except SignatureError as exc:
        logger.warning("rejected webhook with bad signature: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_signature",
        ) from None

    try:
        envelope = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_json",
        ) from exc

    if not isinstance(envelope, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="envelope_must_be_object",
        )

    event_type = envelope.get("event_type")
    event_id = envelope.get("event_id") or envelope.get("delivery_id")
    data = envelope.get("data") or {}

    if not event_type or not isinstance(event_type, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing_event_type",
        )

    return await handle_event(
        session,
        event_type=event_type,
        event_id=event_id if isinstance(event_id, str) else None,
        payload=data if isinstance(data, dict) else {},
    )
