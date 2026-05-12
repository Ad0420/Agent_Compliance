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

Concurrency / dedupe ordering (post-PR #164 audit fix):
    Dedupe is written *before* side effects via INSERT ... ON CONFLICT
    DO NOTHING in its own transaction. Two concurrent identical deliveries
    therefore see exactly one insert succeed; the loser short-circuits to
    a replay 200 without re-applying side effects. The dedupe row carries
    a ``success`` flag — handlers mark it ``True`` on completion. A row
    with ``success=False`` is treated as "not yet successfully processed":
    Svix retries are allowed to drive the handler again. This is how the
    handler distinguishes a stuck-mid-processing replay from a deterministic
    failure (e.g. parent-org-not-yet-exists → 503 → retry).

Role mapping (Clerk → backend):
    org:admin               -> admin
    org:compliance_reviewer -> compliance_reviewer  (custom Clerk role)
    org:member              -> developer
    everything else         -> developer (default)
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from ..config import settings
from ..database import get_db
from ..models import (
    BACKEND_ROLES,
    APIKey,
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

    If a previously soft-deleted row exists for the same Clerk org ID it is
    *not* resurrected — soft-deleted rows have ``clerk_org_id=NULL`` and
    their original ID has been moved to ``scrubbed_clerk_org_id`` so the
    unique constraint allows a fresh insert.
    """
    clerk_org_id = data.get("id")
    if not clerk_org_id:
        logger.warning("organization.created with no id: %r", data)
        return

    # Idempotency: only match live (non-soft-deleted) orgs. A soft-deleted
    # org has had ``clerk_org_id`` NULLed, so this filter naturally excludes
    # them — we keep the explicit ``deleted_at IS NULL`` here for clarity.
    existing = await session.execute(
        select(Organization).where(
            Organization.clerk_org_id == clerk_org_id,
            Organization.deleted_at.is_(None),
        )
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
    """Soft-delete the backend org and tombstone its memberships + API keys.

    Why soft-delete (changed from PR #164's hard-delete):
      ``action_records.org_id`` uses ``ondelete=RESTRICT`` — audit records
      must outlive their org, that's the entire point of an audit trail.
      The PR #164 hard-delete raised ``ForeignKeyViolation`` on Postgres
      whenever the org had any action records; the resulting 500 prevented
      the dedupe row from being committed, so Clerk retried forever.

    What soft-delete does:
      1. ``organizations`` row: set ``deleted_at``, move ``clerk_org_id``
         into ``scrubbed_clerk_org_id``, NULL out ``clerk_org_id`` to free
         the unique constraint.
      2. ``org_memberships``: hard-delete (no audit-trail constraint, the
         linkage is reconstructable from Clerk anyway).
      3. ``api_keys``: mark all live keys revoked. The keys' ``org_id``
         still points at the soft-deleted org, but ``revoked_at`` makes
         ``authenticate_request`` reject them. This is what ultimately
         denies API access after a Clerk org deletion. (We can't rely on
         cascade because the org row is staying.)

    What soft-delete preserves:
      action_records, policy rows, checkpoints, policy_violations, and
      approvals all stay intact — they still reference the (now soft-
      deleted) org row by FK, which is fine because the org row still
      exists. Routes that look up an org by Clerk ID MUST filter
      ``deleted_at IS NULL`` to avoid surfacing a deleted org. Routes
      that look up by ``api_key.org_id`` are protected by the revoked-key
      check in ``authenticate_request``.
    """
    clerk_org_id = data.get("id")
    if not clerk_org_id:
        return
    result = await session.execute(
        select(Organization).where(
            Organization.clerk_org_id == clerk_org_id,
            Organization.deleted_at.is_(None),
        )
    )
    org = result.scalar_one_or_none()
    if org is None:
        logger.info(
            "organization.deleted for unknown/already-deleted clerk_org_id=%s — no-op",
            clerk_org_id,
        )
        return

    now = datetime.utcnow()

    # 1. Soft-delete the org row. NULL out clerk_org_id so the unique index
    #    doesn't block a future re-provision of the same Clerk org ID.
    await session.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(
            deleted_at=now,
            scrubbed_clerk_org_id=clerk_org_id,
            clerk_org_id=None,
        )
    )

    # 2. Hard-delete memberships (no audit constraint; reconstructable from
    #    Clerk). Bulk DELETE so we don't pay per-row ORM overhead.
    await session.execute(
        delete(OrgMembership).where(OrgMembership.org_id == org.id)
    )

    # 3. Revoke live API keys for the org. We don't delete them — the
    #    surviving action records may FK back via approvals etc., and an
    #    operator forensic audit may want to see which key minted a record.
    await session.execute(
        update(APIKey)
        .where(APIKey.org_id == org.id, APIKey.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    logger.info(
        "Soft-deleted backend org %s (clerk_org_id=%s); memberships purged, "
        "API keys revoked.",
        org.id,
        clerk_org_id,
    )


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
    now = datetime.utcnow()
    if membership is None:
        membership = OrgMembership(
            org_id=org_id,
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
            role=backend_role,
            updated_at=now,
        )
        session.add(membership)
        await session.flush()
    else:
        membership.role = backend_role
        membership.updated_at = now
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
    """Upsert the (user, org) membership row.

    If the parent ``Organization`` row doesn't exist yet, we raise 503 so
    Svix retries the delivery. PR #164 originally returned 200 here, which
    permanently dropped the event whenever Clerk delivered the membership
    webhook before the parent ``organization.created`` arrived. Returning
    503 leverages Svix's retry budget (~24 h with exponential backoff) to
    converge once the parent org webhook eventually lands.
    """
    clerk_org_id, clerk_user_id, clerk_role = _extract_membership_fields(data)
    if not clerk_org_id or not clerk_user_id:
        logger.warning(
            "membership event missing fields: org=%r user=%r",
            clerk_org_id,
            clerk_user_id,
        )
        return

    # Look up the backend org that mirrors this Clerk org. The
    # organization.created event SHOULD have created it already; if it
    # hasn't, return 503 so Svix retries.
    result = await session.execute(
        select(Organization).where(
            Organization.clerk_org_id == clerk_org_id,
            Organization.deleted_at.is_(None),
        )
    )
    org = result.scalar_one_or_none()
    if org is None:
        logger.warning(
            "membership event for unknown clerk_org_id=%s — "
            "requesting Svix retry (parent organization.created not yet processed?)",
            clerk_org_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Parent organization not yet provisioned; please retry",
        )

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


# ── Dedupe primitives (CRITICAL #2/#3 fix) ────────────────────────────────────


async def _claim_dedupe_row(
    session: AsyncSession,
    *,
    svix_id: str,
    event_type: str,
) -> tuple[bool, bool]:
    """Claim the dedupe slot for ``svix_id`` in its own transaction.

    Returns ``(is_replay_of_success, is_new_attempt)``:

      * ``is_replay_of_success=True``  → row exists with ``success=True``;
        caller should short-circuit with 200 replay.
      * ``is_new_attempt=True``        → either we inserted a fresh row, or
        we found a previous ``success=False`` row that we're allowed to
        retry. Caller proceeds to run handlers, then must call
        ``_mark_dedupe_success(svix_id)`` if the handlers complete.

    On Postgres we INSERT ... ON CONFLICT DO NOTHING. On SQLite (tests) we
    INSERT OR IGNORE. After the insert, we re-read the row to inspect
    ``success`` — if a peer inserted ahead of us and already succeeded, we
    return as a replay; if a peer (or prior failed attempt) left a
    ``success=False`` row, we proceed (allowing retry of failures).

    The dedupe row is committed BEFORE the handler runs so that:
      (a) a concurrent identical delivery sees the row and waits as a replay,
          rather than racing into duplicate side effects;
      (b) if the handler crashes hard, the ``success=False`` tombstone is
          preserved across the rollback for operator visibility.
    """
    dialect = session.bind.dialect.name if session.bind else "sqlite"

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(ProcessedWebhookEvent)
            .values(
                svix_id=svix_id,
                event_type=event_type,
                processed_at=datetime.utcnow(),
                success=False,
            )
            .on_conflict_do_nothing(index_elements=["svix_id"])
        )
        await session.execute(stmt)
    else:
        # SQLite (tests) / other dialects: use INSERT OR IGNORE via the
        # ``prefixes`` API on the core Insert statement.
        from sqlalchemy import insert as core_insert

        stmt = (
            core_insert(ProcessedWebhookEvent)
            .prefix_with("OR IGNORE")
            .values(
                svix_id=svix_id,
                event_type=event_type,
                processed_at=datetime.utcnow(),
                success=False,
            )
        )
        await session.execute(stmt)

    # Commit the dedupe insert before reading + handler runs so a concurrent
    # delivery sees it (the read in the peer's claim happens after its own
    # INSERT, so we don't need a lock here — both inserts race; the loser's
    # INSERT is a no-op and the loser then reads the winner's row).
    await session.commit()

    result = await session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == svix_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        # This shouldn't happen — the INSERT either succeeded or hit a
        # conflict (and the conflicting row exists). Treat as new.
        return False, True

    if row.success:
        return True, False
    return False, True


async def _mark_dedupe_success(session: AsyncSession, *, svix_id: str) -> None:
    """Mark the dedupe row as successfully processed. Idempotent."""
    await session.execute(
        update(ProcessedWebhookEvent)
        .where(ProcessedWebhookEvent.svix_id == svix_id)
        .values(success=True)
    )
    await session.commit()


# ── INFO: opportunistic GC for processed_webhook_events ───────────────────────

# Probability per webhook of running the cleanup sweep. 1% × (Svix delivery
# rate) is a small constant load — for a 10 rps webhook stream this is one
# DELETE per 100s, which is negligible. Tuned to bound the dedupe table at
# roughly (rps × 30d) rows steady-state.
_GC_PROBABILITY = 0.01
_GC_MAX_AGE_DAYS = 30


async def _opportunistic_cleanup(session: AsyncSession) -> None:
    """Probabilistic GC of old dedupe rows. Bounds table growth without
    requiring a separate cron job. Failure here is non-fatal — we log and
    move on so a bad cleanup doesn't tank the webhook.
    """
    if random.random() >= _GC_PROBABILITY:
        return
    cutoff = datetime.utcnow() - timedelta(days=_GC_MAX_AGE_DAYS)
    try:
        result = await session.execute(
            delete(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.processed_at < cutoff
            )
        )
        await session.commit()
        rowcount = getattr(result, "rowcount", None)
        if rowcount:
            logger.info(
                "Opportunistic GC removed %d processed_webhook_events rows older than %d days",
                rowcount,
                _GC_MAX_AGE_DAYS,
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Opportunistic GC failed: %s", exc)
        await session.rollback()


# ── Main route ────────────────────────────────────────────────────────────────


async def _dispatch_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Route a verified event to its handler."""
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


@router.post("/webhooks")
async def handle_clerk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Verify, dedupe, dispatch.

    Returns 200 OK on success or successful replay. Returns 503 only when
    a handler intentionally requests retry (e.g. parent-org-not-yet-exists).
    Always returns 200 OK on unknown event types so Clerk doesn't retry
    events we can't handle.
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

    event_type = event.get("type") or ""
    data = event.get("data") or {}
    if not isinstance(data, dict):
        logger.warning("Clerk webhook 'data' not an object: %r", type(data))
        raise HTTPException(status_code=400, detail="Malformed event data")

    request_id = getattr(request.state, "request_id", None)
    log_extra = {"request_id": request_id} if request_id else {}
    svix_id = headers.get("svix-id")
    logger.info(
        "Clerk webhook received: type=%s svix_id=%s",
        event_type,
        svix_id,
        extra=log_extra,
    )

    # ── Dedupe BEFORE side effects (CRITICAL #2/#3 fix) ───────────────────
    # If svix-id is missing (shouldn't happen — Svix sets it) we still
    # process the event but skip dedupe. Without an ID we have no key to
    # dedupe on; that path is best-effort only.
    if svix_id:
        is_replay, is_new = await _claim_dedupe_row(
            session, svix_id=svix_id, event_type=event_type
        )
        if is_replay:
            logger.info("Replay of svix_id=%s — already processed", svix_id)
            return {"status": "ok", "replay": "true"}
        if not is_new:  # pragma: no cover - defensive
            # Neither replay-of-success nor a fresh attempt — shouldn't
            # happen, but acknowledge so Clerk doesn't infinite-retry.
            return {"status": "ok"}

    # ── Run handler in its own transaction ────────────────────────────────
    try:
        await _dispatch_event(session, event_type, data)
        await session.commit()
    except HTTPException:
        # Handler asked for retry (e.g. 503 parent-org-not-exists). Roll
        # back the side-effect transaction; the dedupe row stays with
        # ``success=False`` so a subsequent retry can run the handler
        # again. Re-raise so Svix sees the status code.
        await session.rollback()
        raise
    except Exception:
        # Handler crashed. Roll back side effects; dedupe row stays as
        # tombstone (success=False) for operator visibility. Re-raise so
        # FastAPI returns 500 and Svix retries.
        await session.rollback()
        logger.exception("Clerk webhook handler crashed for svix_id=%s", svix_id)
        raise

    if svix_id:
        await _mark_dedupe_success(session, svix_id=svix_id)
        # Opportunistic GC runs only on success — never on the error path,
        # so a sad-path bug can't also tank the cleanup.
        await _opportunistic_cleanup(session)

    return {"status": "ok"}


__all__ = ["router"]
