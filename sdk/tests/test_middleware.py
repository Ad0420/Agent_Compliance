"""Tests for :class:`vera.middleware.VeraMiddleware` (Phase 1 PR 7 / D4).

Covers:

* Tenant header → ContextVar binding visible to the handler.
* Missing header in non-strict mode → handler sees ``None``.
* Malformed header in non-strict mode → handler sees ``None``.
* Missing / malformed header in strict mode → 400 response.
* Per-request reset: tenant does NOT leak across requests.

This entire module skips when starlette is not installed — the SDK
core depends only on httpx, and ``vera.middleware`` raises at import
time without starlette. We use module-level ``pytest.importorskip``
BEFORE importing ``vera.middleware`` so collection succeeds on
starlette-less environments.
"""

from __future__ import annotations

import pytest

# Skip the whole module if starlette / httpx-test client are not installed.
# These MUST run before the ``vera.middleware`` import below; that module
# raises ImportError at module-load time when starlette is missing.
pytest.importorskip("starlette")
pytest.importorskip("starlette.testclient")

from vera._context import (  # noqa: E402
    _current_tenant,
    get_tenant,
    set_default_tenant,
)
from vera.middleware import VeraMiddleware  # noqa: E402

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_tenant_state():
    """Clear tenant state between tests so middleware tests are independent."""
    set_default_tenant(None)
    token = _current_tenant.set(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_tenant(None)


def _build_app(**middleware_kwargs):
    """Build a tiny Starlette app whose handler echoes ``get_tenant()``."""

    async def echo_tenant(request):
        return JSONResponse({"tenant": get_tenant()})

    app = Starlette(routes=[Route("/echo", echo_tenant)])
    app.add_middleware(VeraMiddleware, **middleware_kwargs)
    return app


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def test_middleware_binds_tenant_header():
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/echo", headers={"X-Tenant-ID": "cleveland_clinic"})
    assert resp.status_code == 200
    body = resp.json()
    # JSON serializes tuples to lists.
    assert body == {"tenant": ["cleveland_clinic", "middleware"]}


def test_middleware_custom_header():
    app = _build_app(header="X-Customer")
    client = TestClient(app)
    resp = client.get("/echo", headers={"X-Customer": "acme_co"})
    assert resp.status_code == 200
    assert resp.json() == {"tenant": ["acme_co", "middleware"]}


def test_handler_sees_none_when_header_absent_non_strict():
    app = _build_app()  # strict=False
    client = TestClient(app)
    resp = client.get("/echo")
    assert resp.status_code == 200
    assert resp.json() == {"tenant": None}


def test_handler_sees_none_when_header_malformed_non_strict():
    app = _build_app()  # strict=False
    client = TestClient(app)
    # Whitespace fails the ^[a-zA-Z0-9_-]+$ regex.
    resp = client.get("/echo", headers={"X-Tenant-ID": "has spaces"})
    assert resp.status_code == 200
    assert resp.json() == {"tenant": None}


# ---------------------------------------------------------------------------
# Strict mode.
# ---------------------------------------------------------------------------


def test_strict_mode_rejects_missing_header():
    app = _build_app(strict=True)
    client = TestClient(app)
    resp = client.get("/echo")
    assert resp.status_code == 400
    assert "missing" in resp.text.lower()


def test_strict_mode_rejects_malformed_header():
    app = _build_app(strict=True)
    client = TestClient(app)
    resp = client.get("/echo", headers={"X-Tenant-ID": "has spaces"})
    assert resp.status_code == 400
    assert "invalid" in resp.text.lower()


def test_strict_mode_accepts_valid_header():
    app = _build_app(strict=True)
    client = TestClient(app)
    resp = client.get("/echo", headers={"X-Tenant-ID": "tenant_a"})
    assert resp.status_code == 200
    assert resp.json() == {"tenant": ["tenant_a", "middleware"]}


# ---------------------------------------------------------------------------
# Reset — no leak across requests.
# ---------------------------------------------------------------------------


def test_tenant_resets_between_requests():
    """First request binds tenant; second request (no header) sees None."""
    app = _build_app()
    client = TestClient(app)

    r1 = client.get("/echo", headers={"X-Tenant-ID": "first"})
    assert r1.json() == {"tenant": ["first", "middleware"]}

    r2 = client.get("/echo")
    # If the previous binding leaked, this would return ["first", ...].
    assert r2.json() == {"tenant": None}


def test_tenant_resets_even_on_handler_exception():
    """A handler that raises must still trigger the middleware's reset."""

    async def boom(request):
        raise RuntimeError("kaboom")

    app = Starlette(routes=[Route("/boom", boom)])
    app.add_middleware(VeraMiddleware)
    client = TestClient(app, raise_server_exceptions=False)

    r1 = client.get("/boom", headers={"X-Tenant-ID": "leaky"})
    assert r1.status_code == 500

    # Now check the tenant is not bound for a follow-up request.
    async def echo(request):
        return JSONResponse({"tenant": get_tenant()})

    app2 = Starlette(routes=[Route("/echo", echo)])
    app2.add_middleware(VeraMiddleware)
    client2 = TestClient(app2)
    r2 = client2.get("/echo")
    assert r2.json() == {"tenant": None}
