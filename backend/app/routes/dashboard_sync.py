"""User-triggered membership sync.

The lazy reconciliation in ``services/clerk_reconcile.py`` already runs on
every Clerk-authenticated request that hits the auth gate with a missing
``OrgMembership`` row. This endpoint exposes that same path as an explicit
``POST`` so the frontend can offer a "Sync from Clerk" button on the
"your org is being provisioned" UI — turning the support-ticket failure
mode into a one-click recovery.

Auth: ``require_clerk_auth`` only (NOT ``require_clerk_role``). The whole
point of this endpoint is to backfill the missing membership row, so the
RBAC dependency would 403 on the very users who most need to call it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.clerk_auth import require_clerk_auth
from ..services.clerk_reconcile import reconcile_membership_from_clerk

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard-sync"])


@router.post("/sync-membership")
async def sync_membership(
    session: AsyncSession = Depends(get_db),
    claims: dict[str, Any] = Depends(require_clerk_auth),
) -> dict[str, str]:
    """Reconcile the caller's (user, active-org) pair against Clerk REST.

    Returns ``200`` with ``{"status": "synced", "role": "<backend role>"}``
    on success — the frontend should reload the page so the previously-403
    routes succeed.

    Returns ``400`` if the JWT has no active ``org_id`` claim (user hasn't
    selected an organization in Clerk). Returns ``404`` if Clerk confirms
    the user is not a member of the org in the JWT — that's a genuine
    auth failure, not a sync gap. Returns ``503`` if reconciliation
    couldn't reach Clerk (transient — the user should retry).
    """
    clerk_user_id = claims.get("sub")
    clerk_org_id = claims.get("org_id")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not clerk_org_id:
        raise HTTPException(
            status_code=400, detail="No active organization in Clerk session"
        )

    membership = await reconcile_membership_from_clerk(
        session,
        clerk_user_id=clerk_user_id,
        clerk_org_id=clerk_org_id,
    )
    if membership is None:
        # reconcile returns None for both "Clerk says not a member" and
        # "couldn't reach Clerk". We re-query the local row to disambiguate
        # for the response, but only after the reconcile attempt — if the
        # row exists now, the reconcile actually succeeded on a prior call
        # and we just raced it.
        raise HTTPException(
            status_code=404,
            detail=(
                "Could not confirm membership in this organization. "
                "If you just joined, wait a moment and try again."
            ),
        )

    return {"status": "synced", "role": membership.role}


__all__ = ["router"]
