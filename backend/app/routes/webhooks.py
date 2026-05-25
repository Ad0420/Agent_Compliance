"""Webhook subscription management endpoints."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    APIKey,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from ..schemas.webhook import (
    WebhookCreate,
    WebhookCreateResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookRotateResponse,
    WebhookUpdate,
)
from ..schemas.webhook_delivery import (
    WebhookDeliveryAttemptResponse,
    WebhookDeliveryListResponse,
    WebhookDeliveryReplayResponse,
    WebhookDeliveryResponse,
)
from ..services.auth import require_permission
from ..services.webhooks import (
    _attempt_delivery,
    _track_task,
    generate_webhook_secret,
)


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _to_response(sub: WebhookSubscription) -> WebhookResponse:
    return WebhookResponse(
        id=sub.id,
        url=sub.url,
        event_types=list(sub.event_types or []),
        is_active=sub.is_active,
        description=sub.description,
        created_at=sub.created_at,
        last_delivery_at=sub.last_delivery_at,
        last_delivery_status=sub.last_delivery_status,
        consecutive_failures=sub.consecutive_failures,
    )


@router.post("", response_model=WebhookCreateResponse)
async def create_webhook(
    data: WebhookCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Register a new webhook subscription.

    The signing ``secret`` is returned exactly once. The caller MUST persist
    it on their side — Vera will never expose it again. Use the rotate
    endpoint to replace it.
    """
    org_id, _ = auth
    secret = generate_webhook_secret()
    sub = WebhookSubscription(
        org_id=org_id,
        url=data.url,
        secret=secret,
        event_types=list(data.event_types),
        description=data.description,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return WebhookCreateResponse(
        id=sub.id,
        url=sub.url,
        event_types=list(sub.event_types or []),
        secret=secret,
        description=sub.description,
        created_at=sub.created_at,
    )


@router.get("", response_model=WebhookListResponse)
async def list_webhooks(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """List all webhook subscriptions for the caller's org. Secrets are NOT returned."""
    org_id, _ = auth
    result = await session.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.org_id == org_id)
        .order_by(WebhookSubscription.created_at)
    )
    subs = result.scalars().all()
    return WebhookListResponse(webhooks=[_to_response(s) for s in subs])


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Fetch a single webhook subscription. Secret is NOT returned."""
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return _to_response(sub)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    data: WebhookUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Partial update. Cannot change the secret here — use the rotate endpoint."""
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if data.url is not None:
        sub.url = data.url
    if data.event_types is not None:
        sub.event_types = list(data.event_types)
    if data.is_active is not None:
        sub.is_active = data.is_active
        # Re-enabling a sub clears the failure counter so it isn't auto-
        # disabled on the next failure before the customer's fix has time
        # to take effect.
        if data.is_active:
            sub.consecutive_failures = 0
    if data.description is not None:
        sub.description = data.description

    await session.commit()
    await session.refresh(sub)
    return _to_response(sub)


@router.post("/{webhook_id}/rotate", response_model=WebhookRotateResponse)
async def rotate_webhook_secret(
    webhook_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Generate and return a new signing secret. The old secret stops working immediately."""
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")

    new_secret = generate_webhook_secret()
    sub.secret = new_secret
    await session.commit()
    return WebhookRotateResponse(id=sub.id, secret=new_secret)


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Permanently delete a webhook subscription."""
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await session.delete(sub)
    await session.commit()
    return {"detail": "Webhook deleted"}


# ── Wave 2B PR A3 — admin delivery introspection ───────────────────────


def _to_delivery_response(row: WebhookDelivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=row.id,
        subscription_id=row.subscription_id,
        event_type=row.event_type,
        status=row.status,
        attempt_count=row.attempt_count,
        next_retry_at=row.next_retry_at,
        created_at=row.created_at,
        succeeded_at=row.succeeded_at,
        aborted_at=row.aborted_at,
        last_status_code=row.last_status_code,
        idempotency_key=row.idempotency_key,
        attempts=[
            WebhookDeliveryAttemptResponse.model_validate(a)
            for a in (row.attempts or [])
        ],
    )


@router.get(
    "/{webhook_id}/deliveries", response_model=WebhookDeliveryListResponse
)
async def list_deliveries(
    webhook_id: str,
    status: str | None = Query(
        default=None,
        description="Optional filter: pending|in_progress|succeeded|aborted",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """List deliveries for a subscription. Admin-only, org-scoped.

    Plan §1 — the admin introspection endpoint operators use to triage
    "why didn't customer X get the webhook?". Returns newest-first.
    """
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = (
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == webhook_id)
    )
    if status is not None:
        stmt = stmt.where(WebhookDelivery.status == status)
        count_stmt = count_stmt.where(WebhookDelivery.status == status)

    rows = list((await session.execute(stmt)).scalars().all())
    # Force-load attempts (lazy by default on async sessions).
    for row in rows:
        await session.refresh(row, attribute_names=["attempts"])
    total = (await session.execute(count_stmt)).scalar() or 0
    return WebhookDeliveryListResponse(
        deliveries=[_to_delivery_response(r) for r in rows],
        total=int(total),
    )


@router.post(
    "/{webhook_id}/deliveries/{delivery_id}/replay",
    response_model=WebhookDeliveryReplayResponse,
)
async def replay_delivery(
    webhook_id: str,
    delivery_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Re-attempt a terminal (aborted/succeeded) delivery.

    Flips status to ``pending`` with an immediate ``next_retry_at`` so
    the sweeper picks it up on the next tick. A fresh first attempt is
    also scheduled in-process so the operator sees forward progress
    without waiting for the sweeper.

    ``attempt_count`` is NOT reset to zero — that would collide with
    the existing ``WebhookDeliveryAttempt`` rows on the
    ``(delivery_id, attempt_number)`` unique constraint. Instead, the
    counter continues from its prior value so the replay's attempts get
    fresh sequential numbers (e.g. an aborted delivery with 7 attempts
    starts the replay cycle at attempt 8). The audit trail therefore
    captures every replay round in order.
    """
    org_id, _ = auth
    sub = await session.get(WebhookSubscription, webhook_id)
    if sub is None or sub.org_id != org_id:
        raise HTTPException(status_code=404, detail="Webhook not found")

    delivery = await session.get(WebhookDelivery, delivery_id)
    if (
        delivery is None
        or delivery.subscription_id != webhook_id
        or delivery.org_id != org_id
    ):
        raise HTTPException(status_code=404, detail="Delivery not found")

    # Reconcile attempt_count with the max attempt_number persisted —
    # defensive against state drift if attempts were inserted out of
    # band (manual SQL, replay-of-a-replay).
    max_attempt = (
        await session.execute(
            select(func.max(WebhookDeliveryAttempt.attempt_number)).where(
                WebhookDeliveryAttempt.delivery_id == delivery.id
            )
        )
    ).scalar() or 0
    delivery.attempt_count = max(delivery.attempt_count or 0, int(max_attempt))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delivery.status = "pending"
    delivery.next_retry_at = now
    delivery.succeeded_at = None
    delivery.aborted_at = None
    delivery.locked_until = None
    delivery.locked_by = None
    delivery.last_status_code = None
    await session.commit()
    await session.refresh(delivery)

    # Fire an immediate retry so the operator doesn't wait a full tick.
    _track_task(asyncio.create_task(_attempt_delivery(delivery.id)))

    return WebhookDeliveryReplayResponse(
        id=delivery.id,
        status=delivery.status,
        attempt_count=delivery.attempt_count,
        next_retry_at=delivery.next_retry_at,
    )
