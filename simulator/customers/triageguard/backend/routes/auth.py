"""Auth routes — passkey login, logout, session-status check."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from simulator.customers.triageguard.backend import auth
from simulator.customers.triageguard.backend.config import Settings, get_settings
from simulator.customers.triageguard.backend.schemas import LoginRequest, MeResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> Response:
    if not auth.verify_passkey(body.passkey, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid passkey.",
        )
    token = auth.issue_session(settings)
    auth.set_session_cookie(response, token, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    triageguard_session: Optional[str] = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth.revoke_session(triageguard_session)
    auth.clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
async def me(label: str = Depends(auth.require_session)) -> MeResponse:
    return MeResponse(signed_in_as=label)
