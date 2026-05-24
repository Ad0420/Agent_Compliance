"""Tests for ``vera doctor`` (Phase 1 PR 11 / Stream E3).

Each check is independently mockable via httpx's ``MockTransport``
where needed; checks that don't hit the network (config, tenant,
spool, version, codemod) get direct unit tests.

JSON output is round-tripped through ``json.loads`` to confirm the
structure CI consumers expect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from vera import cli as cli_mod
from vera.cli import cli


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_TENANT_ID",
        "VERA_SPOOL_PATH",
        "VERA_SPOOL_KEY",
        "VERA_DASHBOARD_URL",
        "VERA_DEV",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_doctor_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------


def test_check_config_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://example.com")
    monkeypatch.setenv("VERA_TENANT_ID", "tenant_abc")
    result = cli_mod._doctor_check_config()
    assert result["status"] == "PASS"
    assert result["details"]["api_key_kind"] == "test"
    assert result["details"]["tenant_id"] == "tenant_abc"
    # Mask must NOT leak the full key.
    assert "x" * 32 not in result["details"]["api_key"]


def test_check_config_fail_no_key() -> None:
    result = cli_mod._doctor_check_config()
    assert result["status"] == "FAIL"
    assert "not set" in result["message"]


def test_check_config_fail_bad_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "wrong-prefix-xxx")
    result = cli_mod._doctor_check_config()
    assert result["status"] == "FAIL"
    assert "shape" in result["message"]


def test_check_tenant_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_TENANT_ID", "my_tenant_42")
    result = cli_mod._doctor_check_tenant()
    assert result["status"] == "PASS"
    assert result["details"]["tenant_id"] == "my_tenant_42"


def test_check_tenant_info_when_unset() -> None:
    # No env tenant + no process default → INFO, not FAIL.
    from vera import _context

    previous = _context.get_default_tenant()
    _context.set_default_tenant(None)
    try:
        result = cli_mod._doctor_check_tenant()
        assert result["status"] == "INFO"
    finally:
        _context.set_default_tenant(previous)


def test_check_tenant_fail_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_TENANT_ID", "bad tenant!")  # space + !
    result = cli_mod._doctor_check_tenant()
    assert result["status"] == "FAIL"


def test_check_spool_info_when_unset() -> None:
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "INFO"


def test_check_spool_pass_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VERA_SPOOL_PATH", str(tmp_path / "spool.db"))
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "PASS"


def test_check_sdk_version_pass() -> None:
    result = cli_mod._doctor_check_sdk_version()
    # 1.0.0 is on main; this should always PASS in the current branch.
    assert result["status"] == "PASS"


def test_check_codemod_runs() -> None:
    result = cli_mod._doctor_check_codemod()
    assert result["status"] in {"PASS", "INFO"}


# ---------------------------------------------------------------------------
# Connectivity check via httpx MockTransport
# ---------------------------------------------------------------------------


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport):
    """Patch httpx.Client so every Client() in cli.py uses the mock transport."""
    real_init = httpx.Client.__init__

    def _wrap(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", _wrap)


def test_check_connectivity_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "ok"})
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_connectivity()
    assert result["status"] == "PASS"


def test_check_connectivity_fail_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_connectivity()
    assert result["status"] == "FAIL"
    assert "500" in result["message"]


def test_check_auth_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")

    def _handler(req: httpx.Request) -> httpx.Response:
        auth = req.headers.get("Authorization", "")
        assert auth.startswith("Bearer al_test_")
        return httpx.Response(
            200, json={"id": "org_1234567890abcdef", "name": "Test Org"}
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "PASS"
    assert "org_" in result["details"]["org_id"]


def test_check_auth_fail_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            401, json={"error": {"code": "invalid_api_key"}}
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "401" in result["message"]


def test_check_auth_baa_required_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_live_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            403, json={"error": {"code": "baa_required"}}
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "BAA" in result["message"]


def test_check_auth_no_key_fails() -> None:
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Top-level command: text + JSON output, exit codes
# ---------------------------------------------------------------------------


def test_doctor_text_output_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """No config at all → all the network-dependent checks fail → exit 1."""
    runner = CliRunner()
    # Force connectivity/auth checks to fail predictably.
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, json={})
    )
    _patch_httpx(monkeypatch, transport)
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "[FAIL]" in result.output
    assert "summary:" in result.output


def test_doctor_json_output_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"id": "org_abcd1234efgh"})
    )
    _patch_httpx(monkeypatch, transport)
    result = runner.invoke(cli, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output.strip())
    assert "checks" in parsed
    assert "summary" in parsed
    assert all("name" in c and "status" in c for c in parsed["checks"])
    # The full key must NEVER appear in the JSON.
    assert "x" * 32 not in result.output


def test_doctor_exit_zero_when_all_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    monkeypatch.setenv("VERA_TENANT_ID", "tenant_abc")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"id": "org_abcd1234efgh"})
    )
    _patch_httpx(monkeypatch, transport)
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "[FAIL]" not in result.output


def test_doctor_check_isolation_one_check_explodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A check that raises should not abort the whole doctor run."""

    def _explode() -> dict[str, Any]:
        raise RuntimeError("bang")

    monkeypatch.setattr(
        cli_mod, "_DOCTOR_CHECKS", (cli_mod._doctor_check_config, _explode)
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    # Exit code 1 (the explode counts as FAIL) but the run must complete.
    assert result.exit_code == 1
    assert "raised unexpectedly" in result.output
