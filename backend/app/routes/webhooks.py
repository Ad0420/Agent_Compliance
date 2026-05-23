"""Webhook subscription management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey, WebhookSubscription
from ..schemas.webhook import (
    WebhookCreate,
    WebhookCreateResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookRotateResponse,
    WebhookUpdate,
)
from ..services.auth import require_permission
from ..services.webhooks import generate_webhook_secret


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
