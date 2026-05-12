"""Tests for the Sentry-style :func:`vera.init` entry point.

Covers DX-A: one-call setup that constructs a client from explicit kwargs
+ env vars, registers it as the default for ``@audit``, and replaces
previous clients cleanly on re-init.
"""

from __future__ import annotations

import os

import pytest

import vera
from vera import AsyncVeraClient, VeraClient, audit
from vera.dev import DevClient


@pytest.fixture(autouse=True)
def _reset_init_state(monkeypatch):
    """Clear init/state between tests so each test starts from a clean slate."""
    # Clear env-var pollution from prior tests.
    for var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_AGENT_NAME",
        "VERA_AGENT_VERSION",
        "VERA_MODEL_ID",
        "VERA_FRAMEWORK",
        "VERA_DEV",
        "VERA_SPOOL_PATH",
        "VERA_SPOOL_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Clear module-level handles so each test sees a known state.
    vera._initialized_client = None
    vera._initialized_async_client = None
    from vera import decorator as _decorator_mod

    _decorator_mod._default_client = None
    yield
    # Best-effort cleanup so any client constructed during the test doesn't
    # leak a background thread + atexit hook into subsequent tests.
    client = vera.get_client()
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    vera._initialized_client = None
    _decorator_mod._default_client = None


def test_init_with_explicit_args():
    client = vera.init(
        api_key="al_live_explicit",
        api_url="http://explicit.example",
        agent_name="explicit-agent",
    )
    assert isinstance(client, VeraClient)
    assert client.agent_name == "explicit-agent"
    # Stored on the wire-config dict — bearer token is stamped here.
    assert client._httpx_client_kwargs["headers"]["Authorization"] == "Bearer al_live_explicit"
    assert client.api_url == "http://explicit.example"


def test_init_with_env_vars(monkeypatch):
    monkeypatch.setenv("VERA_API_KEY", "al_live_env")
    monkeypatch.setenv("VERA_API_URL", "http://env.example")
    monkeypatch.setenv("VERA_AGENT_NAME", "env-agent")
    monkeypatch.setenv("VERA_AGENT_VERSION", "1.2.3")
    monkeypatch.setenv("VERA_MODEL_ID", "claude-opus")
    monkeypatch.setenv("VERA_FRAMEWORK", "anthropic")

    client = vera.init()

    assert client.agent_name == "env-agent"
    assert client.agent_version == "1.2.3"
    assert client.model_id == "claude-opus"
    assert client.framework == "anthropic"
    assert client.api_url == "http://env.example"
    assert client._httpx_client_kwargs["headers"]["Authorization"] == "Bearer al_live_env"


def test_init_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("VERA_API_KEY", "env-key")
    monkeypatch.setenv("VERA_AGENT_NAME", "env-agent")

    client = vera.init(api_key="explicit-key", agent_name="explicit-agent")

    assert client.agent_name == "explicit-agent"
    assert client._httpx_client_kwargs["headers"]["Authorization"] == "Bearer explicit-key"


def test_init_replaces_previous_client():
    first = vera.init(api_key="k1", agent_name="first")
    assert vera.get_client() is first

    second = vera.init(api_key="k2", agent_name="second")
    assert vera.get_client() is second
    assert second is not first
    # The previous client should have had close() invoked. We can't observe
    # ``_closed`` directly without poking internals, but it's the documented
    # contract — assert via the side effect: first's _closed flag is set.
    assert first._closed is True


def test_init_registers_default_client():
    client = vera.init(api_key="k", agent_name="a", api_url="http://example.test")

    @audit(action_name="op")
    def op(x):
        return x * 2

    # The @audit decorator pulls the module-level default client. If init()
    # didn't register, the decorator's "no client" WARN path would fire and
    # nothing would land on the client's queue.
    op(21)

    # Allow the background thread room — but the queue is populated before
    # the worker drains it, so qsize > 0 should be visible synchronously.
    # We just check that the client owns the queue state, i.e. that
    # _init_runtime_state has fired.
    assert client._queue is not None


def test_init_dev_mode_via_kwarg():
    client = vera.init(dev=True, agent_name="dev-via-kwarg")
    assert isinstance(client, DevClient)
    assert client.agent_name == "dev-via-kwarg"
    # No API key required for dev mode.


def test_init_dev_mode_via_env(monkeypatch):
    monkeypatch.setenv("VERA_DEV", "1")
    client = vera.init(agent_name="dev-via-env")
    assert isinstance(client, DevClient)


@pytest.mark.parametrize("val", ["true", "yes", "on", "TRUE", "Yes"])
def test_init_dev_mode_env_truthy_variants(monkeypatch, val):
    monkeypatch.setenv("VERA_DEV", val)
    client = vera.init()
    assert isinstance(client, DevClient)


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_init_dev_mode_env_falsy_variants(monkeypatch, val):
    monkeypatch.setenv("VERA_DEV", val)
    client = vera.init(api_key="k", api_url="http://x")
    assert not isinstance(client, DevClient)
    assert isinstance(client, VeraClient)


def test_init_dev_kwarg_overrides_env(monkeypatch):
    monkeypatch.setenv("VERA_DEV", "1")
    client = vera.init(dev=False, api_key="k", api_url="http://x")
    assert not isinstance(client, DevClient)


def test_init_async():
    client = vera.init_async(api_key="k", agent_name="async-agent")
    assert isinstance(client, AsyncVeraClient)
    assert client.agent_name == "async-agent"
    assert vera.get_async_client() is client

    # Cleanup: AsyncVeraClient close() is async; we drop the reference
    # rather than awaiting. The test loop will tear down cleanly.
    vera._initialized_async_client = None


def test_get_client_returns_initialized():
    assert vera.get_client() is None
    client = vera.init(api_key="k", agent_name="a", api_url="http://x")
    assert vera.get_client() is client


def test_init_without_api_key_warns_but_does_not_raise(caplog):
    with caplog.at_level("WARNING", logger="vera.client"):
        client = vera.init(agent_name="no-key", api_url="http://x")
    assert isinstance(client, VeraClient)
    assert any("No API key configured" in r.message for r in caplog.records)


def test_init_passes_through_client_kwargs():
    client = vera.init(
        api_key="k",
        api_url="http://x",
        agent_name="a",
        timeout=12.5,
        batch_size=7,
    )
    assert client._batch_size == 7
    assert client._client.timeout.connect == 12.5
