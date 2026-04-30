"""Passkey login + opaque session-token auth.

Single-process in-memory session store — fine for a sales demo. If we
ever horizontally scale, swap in a redis-backed store.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Response, status

from simulator.customers.triageguard.backend.config import Settings, get_settings


# Module-level session store. Keys are random opaque tokens, values are
# the label we display back to the client (`signed_in_as`).
_SESSIONS: dict[str, str] = {}


def reset_sessions_for_tests() -> None:
    """Clear the session store. Tests call this between cases."""
    _SESSIONS.clear()


def verify_passkey(supplied: str, settings: Settings) -> bool:
    """Constant-time passkey check."""
    return hmac.compare_digest(
        supplied.encode("utf-8"), settings.passkey.encode("utf-8")
    )


def issue_session(settings: Settings) -> str:
    """Mint a fresh opaque session token and remember the user label."""
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = settings.signed_in_as
    return token


def revoke_session(token: Optional[str]) -> None:
    if token and token in _SESSIONS:
        del _SESSIONS[token]


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.cookie_max_age_seconds,
        httponly=True,
        # `samesite=lax` lets the frontend on a different localhost port
        # still send the cookie on top-level GETs; the SSE endpoint relies
        # on this.
        samesite="lax",
        # Demo runs over plain http://localhost so secure=False; flip to
        # True behind https in production.
        secure=False,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.cookie_name, path="/")


# ── FastAPI dependency ────────────────────────────────────────────────────


def require_session(
    triageguard_session: Optional[str] = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Dependency that enforces a valid session cookie. Returns the user label."""
    if not triageguard_session or triageguard_session not in _SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in.",
        )
    return _SESSIONS[triageguard_session]
