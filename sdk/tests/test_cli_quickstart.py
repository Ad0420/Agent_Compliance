"""Tests for ``vera quickstart`` (Phase 1 PR 11 / Stream E2).

The CLI subprocess that actually runs the generated demo is mocked
out so the test suite doesn't hit the network or require a real
backend.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
        "VERA_DASHBOARD_URL",
        "VERA_DEV",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod.webbrowser, "open", lambda *a, **kw: True)


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock subprocess.run so the generated demo is never executed."""

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else [],
            returncode=0,
            stdout="[demo] OK\n",
            stderr="",
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress the post-demo sleep so tests don't pay for it."""
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_quickstart_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["quickstart", "--help"])
    assert result.exit_code == 0
    assert "--demo-file" in result.output
    assert "--tenant" in result.output
    assert "--no-open" in result.output
    assert "--non-interactive" in result.output


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_quickstart_with_env_key_generates_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--tenant",
            "test_tenant_123",
            "--no-open",
        ],
    )
    assert result.exit_code == 0, result.output
    assert demo_file.exists()
    body = demo_file.read_text()
    assert "vera.init(" in body
    assert "@vera.gate(" in body
    assert "Demo complete" in body
    assert "Quickstart complete" in result.output
    assert "/customers/test_tenant_123" in result.output


def test_quickstart_default_tenant_uses_random_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        ["quickstart", "--demo-file", str(demo_file), "--no-open"],
    )
    assert result.exit_code == 0, result.output
    assert "quickstart_" in result.output  # tenant URL includes the prefix


def test_quickstart_no_open_suppresses_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    monkeypatch.setattr(cli_mod, "_is_headless", lambda: False)

    called = {"n": 0}

    def _track(*a, **kw):
        called["n"] += 1
        return True

    monkeypatch.setattr(cli_mod.webbrowser, "open", _track)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--no-open",
            "--tenant",
            "t1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert called["n"] == 0


def test_quickstart_subprocess_invoked_with_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated demo subprocess receives VERA_TENANT_ID + VERA_API_KEY."""
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    captured: dict = {}

    def _capture(cmd, *, env, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", _capture)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--tenant",
            "abc123",
            "--no-open",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["env"]["VERA_TENANT_ID"] == "abc123"
    assert captured["env"]["VERA_API_KEY"] == "al_test_" + "x" * 32


def test_quickstart_subprocess_failure_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)

    def _fail(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="boom\n"
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", _fail)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--tenant",
            "abc",
            "--no-open",
        ],
    )
    assert result.exit_code != 0
    assert "exited with code 1" in result.output


def test_quickstart_skip_run_does_not_invoke_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    called = {"n": 0}

    def _track(*a, **kw):
        called["n"] += 1
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(cli_mod.subprocess, "run", _track)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--tenant",
            "t1",
            "--no-open",
            "--skip-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Config check
# ---------------------------------------------------------------------------


def test_quickstart_non_interactive_no_key_fails(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "quickstart",
                "--demo-file",
                str(demo_file),
                "--non-interactive",
                "--no-open",
                "--tenant",
                "t1",
            ],
        )
    assert result.exit_code != 0
    assert "VERA_API_KEY" in result.output


def test_quickstart_reads_dotenv_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If VERA_API_KEY is unset but a local .env exists, parse it."""
    runner = CliRunner()
    api_key = "al_test_" + "d" * 32
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".env").write_text(
            "# comment line\n"
            f"VERA_API_KEY={api_key}\n"
            "VERA_API_URL=https://example.com\n"
        )
        result = runner.invoke(
            cli,
            [
                "quickstart",
                "--tenant",
                "t1",
                "--no-open",
            ],
        )
    assert result.exit_code == 0, result.output


def test_quickstart_rejects_invalid_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--tenant",
            "bad tenant!",  # space + ! fail the regex
            "--no-open",
        ],
    )
    assert result.exit_code != 0
    assert "invalid --tenant" in result.output


def test_quickstart_dashboard_url_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "x" * 32)
    runner = CliRunner()
    demo_file = tmp_path / "qs_demo.py"
    result = runner.invoke(
        cli,
        [
            "quickstart",
            "--demo-file",
            str(demo_file),
            "--dashboard-url",
            "https://staging.example.com",
            "--tenant",
            "abc",
            "--no-open",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "https://staging.example.com/customers/abc" in result.output
