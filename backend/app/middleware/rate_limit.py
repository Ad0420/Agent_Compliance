"""Sliding-window rate limiter middleware.

Limits requests per API key (or per IP for unauthenticated endpoints).
Uses an in-memory store — suitable for single-instance deployments.
For multi-instance, swap the store for Redis.
"""

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter.

    Configurable via environment variables:
        RATE_LIMIT_RPM: requests per minute (default 120)
        RATE_LIMIT_BURST: max burst in a 1-second window (default 20)
    """

    def __init__(self, app, rpm: int = 0, burst: int = 0):
        super().__init__(app)
        self.rpm = rpm or getattr(settings, "rate_limit_rpm", 120)
        self.burst = burst or getattr(settings, "rate_limit_burst", 20)
        self.window = 60.0  # 1 minute sliding window
        # key -> deque of timestamps
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def _get_key(self, request: Request) -> str:
        """Extract rate limit key: API key if present, otherwise client IP."""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 10:
            # Use first 16 chars of the key as the bucket (don't store full key)
            return f"key:{auth[7:23]}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def _is_allowed(self, key: str) -> tuple[bool, dict]:
        """Check if request is allowed. Returns (allowed, headers)."""
        now = time.monotonic()
        window = self._requests[key]

        # Purge entries older than the window
        cutoff = now - self.window
        while window and window[0] < cutoff:
            window.popleft()

        remaining = self.rpm - len(window)

        # Also check burst (requests in last 1 second)
        one_sec_ago = now - 1.0
        recent = sum(1 for t in window if t >= one_sec_ago)
        burst_remaining = self.burst - recent

        headers = {
            "X-RateLimit-Limit": str(self.rpm),
            "X-RateLimit-Remaining": str(max(0, remaining)),
            "X-RateLimit-Burst-Limit": str(self.burst),
            "X-RateLimit-Burst-Remaining": str(max(0, burst_remaining)),
        }

        if remaining <= 0 or burst_remaining <= 0:
            # Calculate retry-after
            if remaining <= 0:
                retry_after = self.window - (now - window[0])
            else:
                retry_after = 1.0 - (now - one_sec_ago)
            headers["Retry-After"] = str(int(retry_after) + 1)
            return False, headers

        window.append(now)
        headers["X-RateLimit-Remaining"] = str(max(0, remaining - 1))
        return True, headers

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        key = self._get_key(request)
        allowed, headers = self._is_allowed(key)

        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Slow down."},
            )
            for k, v in headers.items():
                response.headers[k] = v
            return response

        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response
