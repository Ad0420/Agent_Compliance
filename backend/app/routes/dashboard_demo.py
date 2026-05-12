"""Placeholder dashboard route to exercise Clerk auth end-to-end.

Real dashboard routes (org bridge, user listing, RBAC checks) ship in
Phase 3 / Workstream E3+E4. This module exists only so that we can
verify the ``require_clerk_auth`` dependency wires through the FastAPI app
without depending on any Phase 3 code.

Phase 4a F1: gated to all three role tiers (admin / developer /
compliance_reviewer) because ``/me`` is the post-login bootstrap call
the frontend makes to learn the user's role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..middleware.clerk_auth import require_clerk_role

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get(
    "/me",
    dependencies=[
        Depends(require_clerk_role(["admin", "developer", "compliance_reviewer"]))
    ],
)
async def me(request: Request) -> dict:
    """Echo the authenticated Clerk user's claims plus their backend
    membership/role. The frontend hits this immediately after sign-in
    to decide which dashboard pages to surface."""
    membership = getattr(request.state, "clerk_membership", None)
    return {
        "clerk_user": request.state.clerk_user,
        "membership": (
            {
                "org_id": membership.org_id,
                "clerk_org_id": membership.clerk_org_id,
                "role": membership.role,
            }
            if membership
            else None
        ),
    }
