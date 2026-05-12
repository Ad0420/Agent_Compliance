"""Tests for the env-var loader in :class:`VeraClient` and
:class:`AsyncVeraClient` constructors (DX-E).

These exercise the constructor pathway directly — independent of
:func:`vera.init` — so other entry points (direct construction in legacy
code, framework integrations) also benefit from env-var fallbacks.
"""

from __future__ import annotations

import os

import pytest

from vera import AsyncVeraClient, VeraClient


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clear vera env vars before each test."""
    for var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_AGENT_NAME",
        "VERA_AGENT_VERSION",
        "VERA_MODEL_ID",
        "VERA_FRAMEWORK",
        "VERA_SPOOL_PATH",
        "VERA_SPOOL_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def test_constructor_reads_VERA_API_URL(monkeypatch):
    monkeypatch.setenv("VERA_API_URL", "http://env-url.example")
    c = VeraClient(api_key="k")
    assert c.api_url == "http://env-url.example"


def test_constructor_reads_VERA_API_KEY(monkeypatch):
    monkeypatch.setenv("VERA_API_KEY", "env-key-value")
    c = VeraClient(api_url="http://x")
    assert c._httpx_client_kwargs["headers"]["Authorization"] == "Bearer env-key-value"


def test_constructor_reads_VERA_AGENT_NAME(monkeypatch):
    monkeypatch.setenv("VERA_AGENT_NAME", "env-named-agent")
    c = VeraClient(api_key="k", api_url="http://x")
    assert c.agent_name == "env-named-agent"


def test_constructor_reads_optional_identity_env(monkeypatch):
    monkeypatch.setenv("VERA_AGENT_VERSION", "v1.2")
    monkeypatch.setenv("VERA_MODEL_ID", "gpt-4o")
    monkeypatch.setenv("VERA_FRAMEWORK", "langchain")
    c = VeraClient(api_key="k", api_url="http://x")
    assert c.agent_version == "v1.2"
    assert c.model_id == "gpt-4o"
    assert c.framework == "langchain"


def test_constructor_reads_VERA_SPOOL_PATH(monkeypatch, tmp_path):
    spool_path = str(tmp_path / "spool.db")
    monkeypatch.setenv("VERA_SPOOL_PATH", spool_path)
    monkeypatch.setenv("VERA_SPOOL_KEY", "test-passphrase-32chars-or-more!")

    c = VeraClient(api_key="k", api_url="http://x")
    try:
        assert c._persistent_buffer_path == spool_path
        # File should have been created by the Spool constructor.
        assert os.path.exists(spool_path)
    finally:
        c.close()


def test_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("VERA_API_URL", "http://env.example")
    monkeypatch.setenv("VERA_API_KEY", "env-key")
    monkeypatch.setenv("VERA_AGENT_NAME", "env-agent")

    c = VeraClient(
        api_url="http://explicit.example",
        api_key="explicit-key",
        agent_name="explicit-agent",
    )
    assert c.api_url == "http://explicit.example"
    assert c.agent_name == "explicit-agent"
    assert c._httpx_client_kwargs["headers"]["Authorization"] == "Bearer explicit-key"


def test_empty_string_env_var_uses_default(monkeypatch):
    """``VERA_API_URL=""`` must fall through to the documented default.

    Empty-string env vars still fall through to the default — only
    explicit non-None kwargs are treated as the caller's intentional
    choice (see :func:`test_explicit_empty_string_kwarg_sticks`).
    """
    monkeypatch.setenv("VERA_API_URL", "")
    c = VeraClient(api_key="k")
    assert c.api_url == "https://api.usevera.xyz"


def test_explicit_empty_string_kwarg_sticks(monkeypatch):
    """Explicit ``api_key=""`` kwarg sticks; the env var is NOT consulted.

    This is the consistent ``None means unset, anything else means
    explicit`` semantic introduced on PR #170. Previously ``api_url`` and
    ``api_key`` disagreed on this point.
    """
    monkeypatch.setenv("VERA_API_KEY", "env-key-value")
    # Explicit empty-string overrides env — the caller chose "" deliberately.
    c = VeraClient(api_url="http://x", api_key="")
    assert c._httpx_client_kwargs["headers"]["Authorization"] == "Bearer "

    monkeypatch.setenv("VERA_AGENT_NAME", "env-named-agent")
    # Same for agent_name: explicit "" wins over env.
    c2 = VeraClient(api_url="http://x", api_key="k", agent_name="")
    assert c2.agent_name == ""


def test_default_api_url_is_saas(monkeypatch):
    c = VeraClient(api_key="k")
    assert c.api_url == "https://api.usevera.xyz"


def test_async_constructor_reads_env_vars(monkeypatch):
    monkeypatch.setenv("VERA_API_KEY", "async-env-key")
    monkeypatch.setenv("VERA_API_URL", "http://async-env.example")
    monkeypatch.setenv("VERA_AGENT_NAME", "async-env-agent")
    monkeypatch.setenv("VERA_AGENT_VERSION", "async-v1")
    monkeypatch.setenv("VERA_MODEL_ID", "async-model")
    monkeypatch.setenv("VERA_FRAMEWORK", "crewai")

    c = AsyncVeraClient()

    assert c.api_url == "http://async-env.example"
    assert c.agent_name == "async-env-agent"
    assert c.agent_version == "async-v1"
    assert c.model_id == "async-model"
    assert c.framework == "crewai"
    assert c._httpx_client_kwargs["headers"]["Authorization"] == "Bearer async-env-key"


def test_async_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("VERA_AGENT_NAME", "env-agent")
    c = AsyncVeraClient(agent_name="explicit", api_key="k")
    assert c.agent_name == "explicit"


def test_constructor_without_api_key_warns(caplog):
    with caplog.at_level("WARNING", logger="vera.client"):
        VeraClient(api_url="http://x")
    assert any("No API key configured" in r.message for r in caplog.records)


def test_constructor_with_explicit_api_key_does_not_warn(caplog):
    with caplog.at_level("WARNING", logger="vera.client"):
        VeraClient(api_url="http://x", api_key="kk")
    assert not any("No API key configured" in r.message for r in caplog.records)
