"""Tests for the ``vera`` CLI (Phase 4a DX-F).

Uses Click's ``CliRunner`` so nothing actually hits the network. Each
test that exercises a subcommand monkeypatches :class:`VeraClient` to a
small stub so we don't depend on real env-var state or the real API.
"""

from __future__ import annotations

import json as _json

import pytest
from click.testing import CliRunner

from vera import cli as cli_mod
from vera.cli import cli
from vera.errors import VeraAuthError, VeraNetworkError, VeraTimeoutError


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


def test_help_works() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output
    assert "ping" in result.output
    assert "tail" in result.output


def test_config_show_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show", "--help"])
    assert result.exit_code == 0
    assert "--reveal-secrets" in result.output


def test_ping_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ping", "--help"])
    assert result.exit_code == 0
    assert "--timeout" in result.output


def test_tail_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["tail", "--help"])
    assert result.exit_code == 0
    assert "--limit" in result.output
    assert "--follow" in result.output
    assert "--json" in result.output


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show_masks_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_live_super_secret_xyz")
    monkeypatch.delenv("VERA_DEV", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0, result.output
    # Full secret must NOT appear anywhere in the output.
    assert "al_live_super_secret_xyz" not in result.output
    assert "..." in result.output  # mask marker
    assert "_xyz" in result.output  # last 4 chars in the mask


def test_config_show_reveal_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_live_super_secret_xyz")
    monkeypatch.delenv("VERA_DEV", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show", "--reveal-secrets"])
    assert result.exit_code == 0, result.output
    assert "al_live_super_secret_xyz" in result.output


def test_config_show_unset_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No API key set → shows ``(unset)`` instead of masking nothing."""
    monkeypatch.delenv("VERA_API_KEY", raising=False)
    monkeypatch.delenv("VERA_DEV", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "(unset)" in result.output


def test_config_show_dev_mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_DEV", "1")
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "dev_mode" in result.output
    assert "on" in result.output


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


class _MockClient:
    """Stub VeraClient used by the ping success path."""

    def __init__(self, **kw):
        self.api_url = "https://test.example"

    def verify_chain(self) -> dict:
        return {"status": "ok", "chain_length": 42}

    def close(self) -> None:
        pass


def test_ping_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "VeraClient", _MockClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["ping"])
    assert result.exit_code == 0, result.output
    assert "Authenticated" in result.output
    assert "chain_length: 42" in result.output


def test_ping_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def verify_chain(self):
            raise VeraAuthError("invalid api_key")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _BadClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["ping"])
    assert result.exit_code == 1
    assert "Authentication failed" in result.output


def test_ping_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SlowClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def verify_chain(self):
            raise VeraTimeoutError("timed out")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _SlowClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["ping", "--timeout", "1"])
    assert result.exit_code == 1
    assert "Timeout" in result.output


def test_ping_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NetClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def verify_chain(self):
            raise VeraNetworkError("dns failed")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _NetClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["ping"])
    assert result.exit_code == 1
    assert "Network error" in result.output


# ---------------------------------------------------------------------------
# tail
# ---------------------------------------------------------------------------


class _TailClient:
    """Stub VeraClient that returns a fixed two-record response."""

    def __init__(self, **kw):
        self.api_url = "https://test.example"

    def query_actions(self, **filters) -> dict:
        return {
            "records": [
                {
                    "id": "r1",
                    "sequence_number": 1,
                    "recorded_at": "2026-05-12T00:00:00Z",
                    "agent_name": "test",
                    "action_name": "approve",
                    "result": "success",
                },
                {
                    "id": "r2",
                    "sequence_number": 2,
                    "recorded_at": "2026-05-12T00:00:01Z",
                    "agent_name": "test",
                    "action_name": "deny",
                    "result": "blocked",
                },
            ]
        }

    def close(self) -> None:
        pass


def test_tail_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "VeraClient", _TailClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["tail", "--limit", "10"])
    assert result.exit_code == 0, result.output
    assert "approve" in result.output
    assert "deny" in result.output


def test_tail_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class _JsonClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def query_actions(self, **filters):
            return {
                "records": [
                    {"id": "r1", "agent_name": "a", "action_name": "act"}
                ]
            }

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _JsonClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["tail", "--json"])
    assert result.exit_code == 0, result.output
    line = result.output.strip().splitlines()[0]
    parsed = _json.loads(line)
    assert parsed["id"] == "r1"


def test_tail_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--agent`` and ``--result`` must be forwarded to query_actions."""
    captured: dict = {}

    class _FilterClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def query_actions(self, **filters):
            captured.update(filters)
            return {"records": []}

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _FilterClient)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["tail", "--agent", "loan-bot", "--result", "blocked", "--limit", "7"],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("agent_name") == "loan-bot"
    assert captured.get("result") == "blocked"
    assert captured.get("limit") == 7


def test_tail_limit_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``--limit`` over 500 is clamped to 500."""
    captured: dict = {}

    class _ClampClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def query_actions(self, **filters):
            captured.update(filters)
            return {"records": []}

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _ClampClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["tail", "--limit", "9999"])
    assert result.exit_code == 0, result.output
    assert captured.get("limit") == 500


def test_tail_one_shot_error_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrClient:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def query_actions(self, **filters):
            raise VeraAuthError("nope")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _ErrClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["tail"])
    assert result.exit_code == 1


def test_print_record_smoke() -> None:
    """``_print_record`` should not raise on a minimally-shaped record."""
    cli_mod._print_record({"sequence_number": 1, "agent_name": "a"})


def test_env_truthy() -> None:
    assert cli_mod._env_truthy.__name__ == "_env_truthy"
    import os as _os

    _os.environ["__VERA_TEST_TRUE__"] = "1"
    try:
        assert cli_mod._env_truthy("__VERA_TEST_TRUE__") is True
    finally:
        _os.environ.pop("__VERA_TEST_TRUE__", None)
