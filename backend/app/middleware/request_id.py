"""Request ID middleware.

Attaches a stable ``X-Request-ID`` to every response so SDK callers can
correlate failures with server logs. If the client supplies a value via the
``X-Request-ID`` request header, we echo it back; otherwise we mint a UUID4.

The id is also stored on ``request.state.request_id`` so route handlers and
loggers can pick it up.
"""

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Echo or generate ``X-Request-ID`` on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
