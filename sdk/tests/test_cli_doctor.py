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


def test_check_tenant_fail_when_resolver_raises_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A programming error in ``resolve_tenant`` (RuntimeError, ImportError,
    AttributeError, ...) must NOT be silently classified as INFO. The
    outer doctor handler turns it into FAIL — that's the honest answer."""
    from vera import _context

    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated resolver internals bug")

    monkeypatch.setattr(_context, "resolve_tenant", _explode)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])
    parsed = json.loads(result.output.strip())
    tenant_check = next(c for c in parsed["checks"] if c["name"] == "tenant")
    assert tenant_check["status"] == "FAIL"
    assert "raised unexpectedly" in tenant_check["message"]


def test_check_tenant_fail_on_phi_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``resolve_tenant`` raises ``TenantMissingOrInvalid`` with a
    non-missing reason (malformed / phi_shape_detected), classify as
    FAIL rather than INFO."""
    from vera import _context
    from vera.errors import (
        TENANT_REASON_PHI_SHAPE,
        TenantMissingOrInvalid,
    )

    def _phi(*_args, **_kwargs):
        raise TenantMissingOrInvalid(reason=TENANT_REASON_PHI_SHAPE)

    monkeypatch.setattr(_context, "resolve_tenant", _phi)
    result = cli_mod._doctor_check_tenant()
    assert result["status"] == "FAIL"
    assert result["details"]["reason"] == TENANT_REASON_PHI_SHAPE


def test_check_spool_info_when_unset() -> None:
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "INFO"


def test_check_spool_warn_when_path_set_but_no_passphrase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``VERA_SPOOL_PATH`` set but no ``VERA_SPOOL_KEY`` → WARN.

    The spool would fail-closed at SDK boot anyway; doctor flags it now.
    """
    monkeypatch.setenv("VERA_SPOOL_PATH", str(tmp_path / "spool.db"))
    monkeypatch.delenv("VERA_SPOOL_KEY", raising=False)
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "WARN"
    assert "VERA_SPOOL_KEY" in result["message"]


def test_check_spool_pass_writes_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fresh spool path + passphrase → constructor writes the sentinel
    and returns PASS. Sentinel file should exist after the check."""
    pytest.importorskip("cryptography")
    spool_path = tmp_path / "spool.db"
    monkeypatch.setenv("VERA_SPOOL_PATH", str(spool_path))
    monkeypatch.setenv("VERA_SPOOL_KEY", "test-passphrase-1234567890")
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "PASS", result["message"]
    assert "sentinel verified" in result["message"]
    assert spool_path.exists()


def test_check_spool_fails_on_wrong_passphrase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing spool + mismatched passphrase → SpoolPassphraseError → FAIL."""
    pytest.importorskip("cryptography")
    spool_path = tmp_path / "spool.db"

    # Bootstrap the spool with passphrase A.
    from vera.spool import Spool

    s = Spool(str(spool_path), passphrase="passphrase-A-original")
    s.close()
    assert spool_path.exists()

    # Doctor opens it with passphrase B — sentinel decrypt fails.
    monkeypatch.setenv("VERA_SPOOL_PATH", str(spool_path))
    monkeypatch.setenv("VERA_SPOOL_KEY", "passphrase-B-different")
    result = cli_mod._doctor_check_spool()
    assert result["status"] == "FAIL"
    assert "sentinel" in result["message"].lower()


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
    """PR #201 flat envelope: ``{"code": "baa_required", ...}`` at top level.

    The previous implementation read ``body.error.code`` (a nested shape
    that never appears on the wire), so the BAA hint silently never
    fired. Now reads ``body.code`` directly.
    """
    monkeypatch.setenv("VERA_API_KEY", "al_live_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            403,
            json={
                "code": "baa_required",
                "fix_url": "/customers",
                "detail": "Customer has not signed BAA",
            },
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "BAA gate blocked this live key" in result["message"]
    assert result["details"]["error_code"] == "baa_required"


def test_check_auth_baa_expired_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """``baa_expired`` triggers the same friendly hint as ``baa_required``."""
    monkeypatch.setenv("VERA_API_KEY", "al_live_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            403,
            json={
                "code": "baa_expired",
                "fix_url": "/customers",
                "detail": "BAA expired 2025-01-01",
            },
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "BAA gate blocked this live key" in result["message"]


def test_check_auth_unknown_code_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-BAA code is surfaced in a ``(code: ...)`` suffix, no BAA hint."""
    monkeypatch.setenv("VERA_API_KEY", "al_live_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            403, json={"code": "rate_limited", "detail": "slow down"}
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "BAA" not in result["message"]
    assert "rate_limited" in result["message"]


def test_check_auth_non_json_body_doesnt_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401 with a plaintext (non-JSON) body should still FAIL gracefully."""
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setenv("VERA_API_URL", "https://mock.example")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            401, content=b"<html>not json</html>",
            headers={"content-type": "text/html"},
        )
    )
    _patch_httpx(monkeypatch, transport)
    result = cli_mod._doctor_check_auth()
    assert result["status"] == "FAIL"
    assert "401" in result["message"]


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


def test_check_sdk_version_fail_on_runtime_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix #10: if ``vera.__version__`` exists and disagrees with the pip
    metadata, that's a stale-install footgun — FAIL with a clear message."""
    import vera as _vera_mod

    # ``vera`` doesn't expose ``__version__`` today. Set + tear down
    # manually because ``monkeypatch.setattr(..., raising=False)`` then
    # ``delattr`` on teardown raises AttributeError if the attr never
    # existed before.
    had_attr = hasattr(_vera_mod, "__version__")
    prev = getattr(_vera_mod, "__version__", None)
    try:
        _vera_mod.__version__ = "999.0.0-shadow"  # type: ignore[attr-defined]
        result = cli_mod._doctor_check_sdk_version()
    finally:
        if had_attr:
            _vera_mod.__version__ = prev  # type: ignore[attr-defined]
        else:
            try:
                delattr(_vera_mod, "__version__")
            except AttributeError:
                pass
    # Pip metadata says 1.0.0 on this branch; runtime patched to mismatch.
    assert result["status"] == "FAIL"
    assert "version mismatch" in result["message"]
    assert "shadowing" in result["message"]


def test_check_sdk_version_pass_when_runtime_version_absent() -> None:
    """When ``vera.__version__`` is missing (current state of the module),
    the check falls back to the pip-only behavior — PASS on 1.0+."""
    import vera as _vera_mod

    # Defensive: ensure no leftover patch from another test.
    if hasattr(_vera_mod, "__version__"):
        try:
            delattr(_vera_mod, "__version__")
        except AttributeError:
            pass
    result = cli_mod._doctor_check_sdk_version()
    assert result["status"] == "PASS"


def test_doctor_warns_on_unknown_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix #14: a check that emits a status outside PASS/FAIL/WARN/INFO
    must surface a warning to stderr rather than being silently dropped."""

    def _weird() -> dict[str, Any]:
        return {
            "name": "weirdo",
            "status": "MAYBE",
            "message": "unclassified",
            "details": {},
        }

    monkeypatch.setattr(cli_mod, "_DOCTOR_CHECKS", (_weird,))
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    # Doctor itself doesn't fail when there's no FAIL count.
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "unknown doctor status" in combined or "MAYBE" in combined


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
