"""Placeholder dashboard route to exercise Clerk auth end-to-end.

Real dashboard routes (org bridge, user listing, RBAC checks) ship in
Phase 3 / Workstream E3+E4. This module exists only so that we can
verify the ``require_clerk_auth`` dependency wires through the FastAPI app
without depending on any Phase 3 code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..middleware.clerk_auth import require_clerk_auth

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("/me")
async def me(
    request: Request,
    claims: dict = Depends(require_clerk_auth),
) -> dict:
    """Echo the authenticated Clerk user's claims. Sanity check for auth wiring.

    Real dashboard routes will be added in Phase 3 (E3 / E4).
    """
    return {"clerk_user": request.state.clerk_user}
