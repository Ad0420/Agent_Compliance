"""Integration tests for the branded :mod:`vera.errors` types.

These cover the contract that ``record_action`` (sync + async) raises a
:class:`vera.errors.VeraError` subclass on terminal failure rather than a
raw ``httpx`` exception, and that the server's ``X-Request-ID`` is
propagated onto the error so customers can correlate with backend logs.
"""

from __future__ import annotations

import httpx
import pytest

import vera.async_client as async_client_mod
import vera.client as client_mod
from vera import (
    AsyncVeraClient,
    VeraAuthError,
    VeraNetworkError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
    VeraClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sync(monkeypatch) -> VeraClient:
    """Sync client with retry budget shrunk so 5xx tests fail fast."""
    monkeypatch.setattr(client_mod, "MAX_RETRIES", 1)
    monkeypatch.setattr(client_mod, "RETRY_BACKOFF_BASE", 0.0)
    return VeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )


def _make_async(monkeypatch) -> AsyncVeraClient:
    monkeypatch.setattr(async_client_mod, "MAX_RETRIES", 1)
    monkeypatch.setattr(async_client_mod, "RETRY_BACKOFF_BASE", 0.0)
    return AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
    )


def _patch_transport(c, handler):
    c._client._transport = httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# 4xx mapping
# ---------------------------------------------------------------------------


def test_record_action_raises_VeraAuthError_on_401(monkeypatch):
    c = _make_sync(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(VeraAuthError) as ei:
        c.record_action(action_name="x")
    assert ei.value.status_code == 401
    c.close()


def test_record_action_raises_VeraAuthError_on_403(monkeypatch):
    c = _make_sync(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(403, json={"detail": "no"}))
    with pytest.raises(VeraAuthError):
        c.record_action(action_name="x")
    c.close()


def test_record_action_raises_VeraValidationError_on_400(monkeypatch):
    c = _make_sync(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(400, json={"detail": "bad"}))
    with pytest.raises(VeraValidationError) as ei:
        c.record_action(action_name="x")
    assert ei.value.status_code == 400
    c.close()


def test_record_action_raises_VeraValidationError_on_413(monkeypatch):
    c = _make_sync(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(413, json={"detail": "too big"}))
    with pytest.raises(VeraValidationError):
        c.record_action(action_name="x")
    c.close()


# ---------------------------------------------------------------------------
# 5xx after retries
# ---------------------------------------------------------------------------


def test_record_action_raises_VeraServerError_on_503(monkeypatch):
    c = _make_sync(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(503, json={"detail": "down"}))
    with pytest.raises(VeraServerError) as ei:
        c.record_action(action_name="x")
    assert ei.value.status_code == 503
    c.close()


# ---------------------------------------------------------------------------
# Timeout / network
# ---------------------------------------------------------------------------


def test_record_action_raises_VeraTimeoutError(monkeypatch):
    c = _make_sync(monkeypatch)

    def handler(req):
        raise httpx.ConnectTimeout("simulated")

    _patch_transport(c, handler)
    with pytest.raises(VeraTimeoutError):
        c.record_action(action_name="x")
    c.close()


def test_record_action_raises_VeraNetworkError(monkeypatch):
    c = _make_sync(monkeypatch)

    def handler(req):
        raise httpx.ConnectError("dns fail")

    _patch_transport(c, handler)
    with pytest.raises(VeraNetworkError):
        c.record_action(action_name="x")
    c.close()


# ---------------------------------------------------------------------------
# X-Request-ID propagation
# ---------------------------------------------------------------------------


def test_request_id_in_error(monkeypatch):
    c = _make_sync(monkeypatch)

    def handler(req):
        return httpx.Response(401, headers={"X-Request-ID": "abc-123"})

    _patch_transport(c, handler)
    with pytest.raises(VeraAuthError) as ei:
        c.record_action(action_name="x")
    assert ei.value.request_id == "abc-123"
    assert "abc-123" in str(ei.value)
    c.close()


# ---------------------------------------------------------------------------
# Async parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_record_action_raises_VeraAuthError_on_401(monkeypatch):
    c = _make_async(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(401))
    with pytest.raises(VeraAuthError):
        await c.record_action(action_name="x")
    await c._client.aclose()


@pytest.mark.asyncio
async def test_async_record_action_raises_VeraServerError_on_503(monkeypatch):
    c = _make_async(monkeypatch)
    _patch_transport(c, lambda req: httpx.Response(503))
    with pytest.raises(VeraServerError):
        await c.record_action(action_name="x")
    await c._client.aclose()


@pytest.mark.asyncio
async def test_async_request_id_in_error(monkeypatch):
    c = _make_async(monkeypatch)
    _patch_transport(
        c,
        lambda req: httpx.Response(401, headers={"X-Request-ID": "xyz-9"}),
    )
    with pytest.raises(VeraAuthError) as ei:
        await c.record_action(action_name="x")
    assert ei.value.request_id == "xyz-9"
    await c._client.aclose()
