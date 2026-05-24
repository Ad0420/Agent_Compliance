"""FastAPI / Starlette middleware that binds the tenant per request.

Phase 1 PR 7 / Stream D4. Reads a configurable header off each incoming
HTTP request and calls :func:`vera._context.set_tenant` so downstream
handlers (and any ``@vera.gate`` / ``record_action`` calls they make)
resolve to the correct tenant automatically.

Usage::

    from fastapi import FastAPI
    from vera.middleware import VeraMiddleware

    app = FastAPI()
    app.add_middleware(VeraMiddleware, header="X-Tenant-ID")

Optional ``strict=True`` rejects requests with a missing or malformed
tenant header with a 400 response; the default ``strict=False`` lets
the request through with no tenant bound (so downstream code that
doesn't need a tenant still works, and code that does will raise
:class:`TenantMissingOrInvalid` at resolution time).

starlette is an OPTIONAL dependency of the SDK — the import lives at
module level but module load only fails if starlette is unavailable
AND someone actually imports ``vera.middleware``. The rest of the SDK
does not import this module.

Install with the ``middleware`` extra to get the pinned starlette
floor::

    pip install vera-sdk[middleware]

The pin is ``starlette>=0.21`` because :class:`BaseHTTPMiddleware` had
a contextvar-isolation bug in older releases that caused per-request
tenant bindings to leak across requests. The minimum supported version
fixes that.

Thread-pool gotcha (Codex F4)
-----------------------------
The middleware sets a :class:`contextvars.ContextVar`. That value
propagates automatically into any :func:`asyncio.create_task` the
handler spawns, but it does **NOT** propagate into thread-pool work
(FastAPI ``BackgroundTasks`` running sync functions, ``run_in_executor``,
``asyncio.to_thread``). Use :func:`vera._context.copy_context_to_thread`
to bridge — see that function's docstring for examples.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._context import reset_tenant, set_tenant
from .errors import TenantMissingOrInvalid

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
except ImportError as e:  # pragma: no cover — guarded by optional install
    raise ImportError(
        "vera.middleware requires starlette. Install with `pip install starlette` "
        "or `pip install fastapi` (which depends on starlette)."
    ) from e

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger("vera.middleware")

DEFAULT_HEADER = "X-Tenant-ID"


class VeraMiddleware(BaseHTTPMiddleware):
    """Bind the request's tenant header to the Vera SDK ContextVar.

    Reads ``self.header`` (default ``X-Tenant-ID``) from each incoming
    request. When present and valid, sets it via
    :func:`vera._context.set_tenant` with ``source='middleware'`` and
    resets the ContextVar in a ``finally`` block so the binding never
    leaks between requests.

    Args:
        app: The downstream ASGI app (passed by starlette).
        header: Header name to read the tenant ID from. Case-insensitive
            (starlette normalises). Defaults to ``X-Tenant-ID``.
        strict: When ``True``, requests missing the header OR carrying
            a malformed value short-circuit with a 400 response. When
            ``False`` (default), the request continues with no tenant
            bound — downstream code that needs a tenant will raise
            :class:`TenantMissingOrInvalid` at resolution time.
    """

    def __init__(
        self,
        app: "ASGIApp",
        header: str = DEFAULT_HEADER,
        strict: bool = False,
    ):
        super().__init__(app)
        self.header = header
        self.strict = strict

    async def dispatch(self, request: "Request", call_next):  # type: ignore[override]
        tenant_id = request.headers.get(self.header)
        token = None
        if tenant_id:
            try:
                token = set_tenant(tenant_id, source="middleware")
            except TenantMissingOrInvalid:
                # Malformed header. In strict mode reject the request;
                # otherwise log once-per-request and continue without
                # binding (downstream will raise at resolution time if
                # the handler actually needs the tenant).
                logger.warning(
                    "vera.middleware: rejected malformed %s header",
                    self.header,
                )
                if self.strict:
                    return Response(
                        content=f"invalid {self.header} header",
                        status_code=400,
                    )
        elif self.strict:
            return Response(
                content=f"missing {self.header} header",
                status_code=400,
            )
        try:
            return await call_next(request)
        finally:
            # Always reset, even on handler exception, so the next
            # request handled on this asyncio task starts clean. Reset
            # is a no-op when ``token`` is None (header absent or
            # validation failed in non-strict mode).
            if token is not None:
                reset_tenant(token)


__all__ = ["VeraMiddleware", "DEFAULT_HEADER"]
