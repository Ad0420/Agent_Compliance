"""Clerk webhook handler — Workstream E3 (Clerk → backend org bridge).

Configure in Clerk Dashboard → Webhooks → Add Endpoint:
    URL:    POST https://<your-vera-backend>/v1/clerk/webhooks
    Events: organization.created
            organization.deleted
            organizationMembership.created
            organizationMembership.updated
            organizationMembership.deleted

The signing secret from that endpoint goes into ``CLERK_WEBHOOK_SECRET``.

Security model:
* Every delivery is verified against the Svix signature headers (``svix-id``,
  ``svix-timestamp``, ``svix-signature``). Missing/invalid signature → 401.
* The ``CLERK_WEBHOOK_SECRET`` env var must be set; otherwise the endpoint
  returns 503 to refuse all deliveries. Fail-closed beats failing open.
* Each delivery is deduped on its ``svix-id`` via the
  ``processed_webhook_events`` table — Svix is at-least-once and Clerk
  replays on transient failures.
* Handlers are idempotent: replays return 200 OK without re-applying side
  effects. Unknown event types are logged and acknowledged (200) so Clerk
  doesn't retry events we haven't subscribed to.

Role mapping (Clerk → backend):
    org:admin               -> admin
    org:compliance_reviewer -> compliance_reviewer  (custom Clerk role)
    org:member              -> developer
    everything else         -> developer (default)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from ..config import settings
from ..database import get_db
from ..models import (
    BACKEND_ROLES,
    ChainState,
    Organization,
    OrgMembership,
    ProcessedWebhookEvent,
)

logger = logging.getLogger("vera.clerk_webhooks")

# Router is mounted at /v1 so the public path is /v1/clerk/webhooks.
router = APIRouter(prefix="/clerk", tags=["clerk-webhooks"])


# ── Role mapping ──────────────────────────────────────────────────────────────
# Clerk's role values are "org:admin", "org:member", and custom ones an
# operator may create in the Clerk dashboard. We translate at the trust
# boundary so RBAC checks downstream stay in backend-role vocabulary only.
_CLERK_TO_BACKEND_ROLE = {
    "org:admin": "admin",
    "admin": "admin",
    "org:compliance_reviewer": "compliance_reviewer",
    "compliance_reviewer": "compliance_reviewer",
    "org:member": "developer",
    "member": "developer",
    "org:developer": "developer",
    "developer": "developer",
}


def _map_clerk_role(clerk_role: str | None) -> str:
    """Map a Clerk role string to a backend role. Unknown values default to
    ``developer`` — the safe minimum: a member who can list keys and operate
    but cannot mint or revoke. Admin promotion has to happen explicitly.
    """
    if clerk_role is None:
        return "developer"
    mapped = _CLERK_TO_BACKEND_ROLE.get(clerk_role)
    if mapped is None:
        logger.info("Unknown Clerk role %r; defaulting to 'developer'", clerk_role)
        return "developer"
    assert mapped in BACKEND_ROLES, f"role map inconsistency: {mapped!r}"
    return mapped


# ── Signature verification ────────────────────────────────────────────────────


def _verify_svix(payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify the Svix signature on the request body. Returns the decoded
    event dict on success; raises HTTPException(401) on any failure.

    The caller is responsible for ensuring ``settings.clerk_webhook_secret``
    is set (we raise 503 from the route before reaching here if it isn't).
    """
    try:
        wh = Webhook(settings.clerk_webhook_secret)
        event = wh.verify(payload, headers)
    except WebhookVerificationError as exc:
        logger.info("Clerk webhook rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid signature") from exc
    if not isinstance(event, dict):
        # Svix verify returns the parsed JSON payload — Clerk always sends
        # an object, but be defensive in case a future Clerk change ships a
        # different envelope.
        logger.warning("Clerk webhook payload not an object: %r", type(event))
        raise HTTPException(status_code=400, detail="Malformed event")
    return event


# ── Event handlers ────────────────────────────────────────────────────────────


async def _handle_org_created(session: AsyncSession, data: dict[str, Any]) -> None:
    """Create a backend Organization row keyed by the Clerk org ID, plus
    an admin OrgMembership for ``created_by``. Idempotent.
    """
    clerk_org_id = data.get("id")
    if not clerk_org_id:
        logger.warning("organization.created with no id: %r", data)
        return

    # Idempotency: if we've already mapped this Clerk org, no-op.
    existing = await session.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = existing.scalar_one_or_none()
    if org is None:
        org = Organization(
            name=data.get("name") or f"clerk:{clerk_org_id}",
            clerk_org_id=clerk_org_id,
        )
        session.add(org)
        await session.flush()
        # Every org needs a chain_state row; without it, action ingestion
        # for this org would fail with a foreign-key error.
        session.add(ChainState(org_id=org.id))
        await session.flush()
        logger.info(
            "Created backend org %s for clerk_org_id=%s", org.id, clerk_org_id
        )

    # created_by is the Clerk user who created the org. Promote them to admin.
    creator_user_id = data.get("created_by")
    if creator_user_id:
        await _upsert_membership(
            session,
            org_id=org.id,
            clerk_org_id=clerk_org_id,
            clerk_user_id=creator_user_id,
            backend_role="admin",
        )


async def _handle_org_deleted(session: AsyncSession, data: dict[str, Any]) -> None:
    """Hard-delete the backend org. The DB FK chain cascades to memberships,
    chain_state, api_keys, action_records, policies, etc.

    Decision: we hard-delete rather than soft-delete. Rationale:
      - The Clerk org is gone; there's no human-facing UI that needs the
        row to render a tombstone.
      - Compliance data (action_records, policies, etc.) cascade-delete via
        the existing FK ``ondelete="CASCADE"`` chain. If an operator wants
        to retain audit history after a Clerk org deletion, they should
        export before the webhook fires (Clerk gives a confirmation step).
      - Soft-delete adds a ``deleted_at`` column + every query needs filtering;
        we'd rather not pay that cost until there's a compliance reason.

    Implementation note: we use a Core-level DELETE statement here rather
    than ``session.delete(org)`` because several child tables (chain_state,
    api_keys, action_records, …) use the DB-level FK ``ondelete=CASCADE``
    but lack a matching ORM ``cascade=`` directive on the parent relationship.
    A Core delete bypasses the ORM dependency walker that tries to NULL out
    those child primary keys before issuing the DELETE.
    """
    clerk_org_id = data.get("id")
    if not clerk_org_id:
        return
    result = await session.execute(
        select(Organization.id).where(Organization.clerk_org_id == clerk_org_id)
    )
    org_id = result.scalar_one_or_none()
    if org_id is None:
        logger.info(
            "organization.deleted for unknown clerk_org_id=%s — no-op",
            clerk_org_id,
        )
        return

    # SQLite needs PRAGMA foreign_keys = ON per-connection for ON DELETE
    # CASCADE to actually fire. Production is Postgres where this is the
    # default; we set it here defensively so tests on SQLite mirror prod.
    if session.bind and session.bind.dialect.name == "sqlite":
        await session.execute(text("PRAGMA foreign_keys = ON"))

    await session.execute(
        delete(Organization).where(Organization.id == org_id)
    )
    logger.info("Deleted backend org %s (clerk_org_id=%s)", org_id, clerk_org_id)


async def _upsert_membership(
    session: AsyncSession,
    *,
    org_id: str,
    clerk_org_id: str,
    clerk_user_id: str,
    backend_role: str,
) -> OrgMembership:
    """Idempotent upsert. If a row exists for (clerk_user_id, clerk_org_id),
    update its role; otherwise insert. Used by both `created` and `updated`
    membership events so replays + role changes converge to the same state.
    """
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == clerk_user_id,
            OrgMembership.clerk_org_id == clerk_org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        membership = OrgMembership(
            org_id=org_id,
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
            role=backend_role,
        )
        session.add(membership)
        await session.flush()
    else:
        membership.role = backend_role
    return membership


def _extract_membership_fields(
    data: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Pull (clerk_org_id, clerk_user_id, clerk_role) out of a Clerk
    organizationMembership.* payload. Clerk's shape:

        {
          "organization": { "id": "org_...", ... },
          "public_user_data": { "user_id": "user_...", ... },
          "role": "org:admin",
          ...
        }
    """
    org = data.get("organization") or {}
    user = data.get("public_user_data") or {}
    return (
        org.get("id") if isinstance(org, dict) else None,
        user.get("user_id") if isinstance(user, dict) else None,
        data.get("role"),
    )


async def _handle_membership_created_or_updated(
    session: AsyncSession, data: dict[str, Any]
) -> None:
    clerk_org_id, clerk_user_id, clerk_role = _extract_membership_fields(data)
    if not clerk_org_id or not clerk_user_id:
        logger.warning(
            "membership event missing fields: org=%r user=%r",
            clerk_org_id,
            clerk_user_id,
        )
        return

    # Look up the backend org that mirrors this Clerk org. The
    # organization.created event SHOULD have created it already; if not,
    # log loudly — out-of-order delivery means the upstream Clerk config
    # is missing the organization.created subscription.
    result = await session.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        logger.warning(
            "membership event for unknown clerk_org_id=%s — "
            "is the organization.created subscription enabled?",
            clerk_org_id,
        )
        return

    backend_role = _map_clerk_role(clerk_role)
    await _upsert_membership(
        session,
        org_id=org.id,
        clerk_org_id=clerk_org_id,
        clerk_user_id=clerk_user_id,
        backend_role=backend_role,
    )


async def _handle_membership_deleted(
    session: AsyncSession, data: dict[str, Any]
) -> None:
    clerk_org_id, clerk_user_id, _ = _extract_membership_fields(data)
    if not clerk_org_id or not clerk_user_id:
        return
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == clerk_user_id,
            OrgMembership.clerk_org_id == clerk_org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return
    await session.delete(membership)


# ── Main route ────────────────────────────────────────────────────────────────


@router.post("/webhooks")
async def handle_clerk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Verify, dedupe, dispatch. Always returns 200 OK on a verified event
    (even unknown types) so Clerk doesn't retry events we can't handle.
    """
    if not settings.clerk_webhook_secret:
        logger.warning(
            "CLERK_WEBHOOK_SECRET unset — refusing to process inbound Clerk webhook"
        )
        raise HTTPException(
            status_code=503,
            detail="Clerk webhooks not configured on this server",
        )

    payload = await request.body()
    # Svix wants lowercase header names. FastAPI's request.headers is
    # case-insensitive on read but we materialise a plain dict for svix.
    headers = {k.lower(): v for k, v in request.headers.items()}

    event = _verify_svix(payload, headers)

    # Dedupe on the Svix message ID. INSERT … ON CONFLICT DO NOTHING via a
    # try/select pattern that works on both Postgres and SQLite.
    svix_id = headers.get("svix-id")
    if svix_id:
        existing = await session.execute(
            select(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.svix_id == svix_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.info("Replay of svix_id=%s — already processed", svix_id)
            return {"status": "ok", "replay": "true"}

    event_type = event.get("type") or ""
    data = event.get("data") or {}
    if not isinstance(data, dict):
        logger.warning("Clerk webhook 'data' not an object: %r", type(data))
        raise HTTPException(status_code=400, detail="Malformed event data")

    request_id = getattr(request.state, "request_id", None)
    log_extra = {"request_id": request_id} if request_id else {}
    logger.info(
        "Clerk webhook received: type=%s svix_id=%s",
        event_type,
        svix_id,
        extra=log_extra,
    )

    if event_type == "organization.created":
        await _handle_org_created(session, data)
    elif event_type == "organization.deleted":
        await _handle_org_deleted(session, data)
    elif event_type in (
        "organizationMembership.created",
        "organizationMembership.updated",
    ):
        await _handle_membership_created_or_updated(session, data)
    elif event_type == "organizationMembership.deleted":
        await _handle_membership_deleted(session, data)
    else:
        logger.info("Unhandled Clerk event type %r — acknowledged", event_type)

    # Record the svix_id LAST so a handler exception aborts the whole
    # transaction (no record + no side effects → Clerk retries cleanly).
    if svix_id:
        session.add(
            ProcessedWebhookEvent(svix_id=svix_id, event_type=event_type)
        )

    await session.commit()
    return {"status": "ok"}


__all__ = ["router"]
