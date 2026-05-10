"""Branded exception hierarchy for the Vera SDK.

These wrap underlying httpx errors so callers can catch Vera-specific failures
without depending on httpx internals. Each error carries an optional
``request_id`` (from the server's ``X-Request-ID`` response header) and a docs
URL for the corresponding error code.

Note: as of v0.3.x, the client does NOT yet raise these — they are public API
ahead of the v0.4 client refactor. They are defined now so customer code can
write ``except VeraAuthError:`` from day one and get the right behavior once
the client integration ships (workstream A1 / Phase 2).
"""

from __future__ import annotations

DOC_BASE = "https://docs.usevera.xyz/errors"


class VeraError(Exception):
    """Base class for all Vera SDK errors.

    Attributes:
        request_id: Server-emitted ``X-Request-ID`` echo, if available.
        status_code: HTTP status code that triggered the error, if applicable.
        code: Stable short identifier used in the docs URL (subclass overrides).
    """

    code: str = "vera_error"

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        status_code: int | None = None,
    ):
        self.request_id = request_id
        self.status_code = status_code
        suffix = ""
        if request_id:
            suffix += f" [request_id={request_id}]"
        suffix += f" — see {DOC_BASE}/{self.code}"
        super().__init__(f"{message}{suffix}")


class VeraAuthError(VeraError):
    """401/403: API key missing, invalid, or revoked."""

    code = "auth"


class VeraRateLimitError(VeraError):
    """429: too many requests."""

    code = "rate_limit"


class VeraServerError(VeraError):
    """5xx: Vera service is unavailable."""

    code = "server"


class VeraTimeoutError(VeraError):
    """Request timed out."""

    code = "timeout"


class VeraNetworkError(VeraError):
    """Network failure (DNS, TLS, connection refused, etc.)."""

    code = "network"


class VeraValidationError(VeraError):
    """4xx other than 401/403/429: malformed request."""

    code = "validation"


__all__ = [
    "DOC_BASE",
    "VeraError",
    "VeraAuthError",
    "VeraRateLimitError",
    "VeraServerError",
    "VeraTimeoutError",
    "VeraNetworkError",
    "VeraValidationError",
]
