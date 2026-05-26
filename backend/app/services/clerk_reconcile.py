"""Source-of-truth reconciliation of Clerk org + membership state.

Backstop for the Clerk webhook pipeline. When a user signs in with a valid
Clerk JWT whose ``org_id`` claim points at an org Vera has no
``OrgMembership`` row for, this module asks Clerk's REST API "is this user
actually a member of that org, and with what role?" and backfills the
``Organization`` + ``ChainState`` + ``OrgMembership`` rows on the spot.

Why this exists (failure modes the webhook alone can't cover):

  1. Org deleted+recreated in Clerk: existing members carry over silently,
     no ``organizationMembership.created`` event is re-fired.
  2. Backend was down for >24 h during a key event (Svix retry budget
     elapses and the event is dropped forever).
  3. Webhook URL was misconfigured at the moment the event fired.
  4. Org created in Clerk before the webhook subscription existed.

Idempotent — safe to call on every miss. The hot path (rows already exist)
short-circuits before any Clerk API call once the local rows are present.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..middleware.clerk_auth import _CLERK_API_BASE, _map_clerk_role, _utcnow_naive
from ..models import ChainState, Organization, OrgMembership

logger = logging.getLogger(__name__)


async def reconcile_membership_from_clerk(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    clerk_org_id: str,
) -> OrgMembership | None:
    """Ensure the (user, org) pair has Org + Membership rows in Vera's DB.

    Returns the ``OrgMembership`` row if Clerk confirms the user is a member
    of the org. Returns ``None`` in two cases — the caller must treat both as
    "no membership":

      * Clerk responded and said the user is not a member of the org.
      * Reconciliation was not possible (e.g. ``CLERK_SECRET_KEY`` unset,
        Clerk API timed out). Fail closed; the caller's existing 401/403
        handling kicks in and the user retries.

    The split is logged but not surfaced to the caller — leaking "Clerk is
    down" vs "user genuinely not a member" to an unauthenticated client
    would be an info-disclosure footgun.
    """
    if not settings.clerk_secret_key:
        logger.warning(
            "Reconcile skipped: CLERK_SECRET_KEY not configured "
            "(user=%s org=%s)",
            clerk_user_id,
            clerk_org_id,
        )
        return None

    try:
        clerk_role = await _fetch_user_role_in_org(
            clerk_user_id=clerk_user_id, clerk_org_id=clerk_org_id
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Reconcile aborted: Clerk membership lookup failed "
            "(user=%s org=%s): %s",
            clerk_user_id,
            clerk_org_id,
            exc,
        )
        return None

    if clerk_role is None:
        logger.info(
            "Reconcile: Clerk confirms not-a-member (user=%s org=%s)",
            clerk_user_id,
            clerk_org_id,
        )
        return None

    org = await _ensure_organization(session, clerk_org_id=clerk_org_id)
    if org is None:
        # Couldn't materialize the Org row (Clerk org-fetch failure). The
        # _ensure_organization call logged the reason; fail closed.
        return None

    backend_role = _map_clerk_role(clerk_role)
    membership = await _upsert_membership(
        session,
        org_id=org.id,
        clerk_user_id=clerk_user_id,
        clerk_org_id=clerk_org_id,
        backend_role=backend_role,
    )
    await session.commit()
    await session.refresh(membership)
    logger.info(
        "Reconcile succeeded: user=%s org=%s role=%s "
        "(org_row=%s, membership_row=%s)",
        clerk_user_id,
        clerk_org_id,
        backend_role,
        org.id,
        membership.id,
    )
    return membership


async def _fetch_user_role_in_org(
    *, clerk_user_id: str, clerk_org_id: str
) -> str | None:
    """Look up a user's current role in an org via Clerk REST.

    Returns the raw Clerk role string (e.g. ``"org:admin"``) or ``None`` if
    not a member / org doesn't exist. Raises ``httpx.HTTPError`` on transport
    or non-404 server errors so the caller can fail closed.
    """
    url = f"{_CLERK_API_BASE}/v1/organizations/{clerk_org_id}/memberships"
    headers = {
        "Authorization": f"Bearer {settings.clerk_secret_key}",
        "Accept": "application/json",
    }
    params = {"user_id": clerk_user_id, "limit": 1}

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body = resp.json()
    data = body if isinstance(body, list) else (body.get("data") or [])
    if not data:
        return None
    first = data[0]
    return first.get("role") if isinstance(first, dict) else None


async def _ensure_organization(
    session: AsyncSession, *, clerk_org_id: str
) -> Organization | None:
    """Return the live ``Organization`` row for ``clerk_org_id``, creating
    one (plus its ``ChainState``) by fetching from Clerk REST if missing.
    """
    result = await session.execute(
        select(Organization).where(
            Organization.clerk_org_id == clerk_org_id,
            Organization.deleted_at.is_(None),
        )
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org

    try:
        name = await _fetch_org_name(clerk_org_id)
    except httpx.HTTPError as exc:
        logger.warning(
            "Reconcile: failed to fetch Clerk org details for %s: %s",
            clerk_org_id,
            exc,
        )
        return None

    org = Organization(
        name=name or f"clerk:{clerk_org_id}",
        clerk_org_id=clerk_org_id,
    )
    session.add(org)
    await session.flush()
    session.add(ChainState(org_id=org.id))
    await session.flush()
    logger.info(
        "Reconcile: created Organization id=%s for clerk_org_id=%s",
        org.id,
        clerk_org_id,
    )
    return org


async def _fetch_org_name(clerk_org_id: str) -> str | None:
    url = f"{_CLERK_API_BASE}/v1/organizations/{clerk_org_id}"
    headers = {
        "Authorization": f"Bearer {settings.clerk_secret_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body = resp.json()
    return body.get("name") if isinstance(body, dict) else None


async def _upsert_membership(
    session: AsyncSession,
    *,
    org_id: str,
    clerk_org_id: str,
    clerk_user_id: str,
    backend_role: str,
) -> OrgMembership:
    """Idempotent membership upsert. Mirrors the webhook handler's behaviour
    so reconciled rows are indistinguishable from webhook-created ones."""
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == clerk_user_id,
            OrgMembership.clerk_org_id == clerk_org_id,
        )
    )
    membership = result.scalar_one_or_none()
    now = _utcnow_naive()
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


__all__ = ["reconcile_membership_from_clerk"]
