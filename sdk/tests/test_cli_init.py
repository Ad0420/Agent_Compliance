"""Tests for ``vera init`` (Phase 1 PR 11 / Stream E1).

Covers the happy path with ``--key`` (no browser), the paste-back path
(monkeypatched ``getpass``), the existing-config short-circuit, the
``--force`` overwrite, and shape validation.

Browsers are NEVER opened in CI: ``webbrowser.open`` is monkeypatched
on every test that could trigger it.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from vera import cli as cli_mod
from vera.cli import cli


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip Vera env vars so existing config doesn't leak into init tests."""
    for var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_TENANT_ID",
        "VERA_DASHBOARD_URL",
        "VERA_DEV",
        "VERA_SPOOL_PATH",
        "VERA_SPOOL_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``webbrowser.open`` so the test suite never spawns a browser."""
    monkeypatch.setattr(cli_mod.webbrowser, "open", lambda *a, **kw: True)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_init_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--help"])
    assert result.exit_code == 0
    assert "--key" in result.output
    assert "--env-file" in result.output
    assert "--force" in result.output
    assert "--dashboard-url" in result.output


# ---------------------------------------------------------------------------
# --key flag (no browser)
# ---------------------------------------------------------------------------


def test_init_with_key_dash_reads_stdin(tmp_path: Path) -> None:
    """``--key -`` reads the key from stdin so it doesn't leak into
    ps / shell history / CI logs."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "s" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", "-", "--env-file", str(env_file)],
        input=f"{api_key}\n",
    )
    assert result.exit_code == 0, result.output
    assert env_file.exists()
    assert api_key in env_file.read_text()


def test_init_with_key_dash_strips_whitespace(tmp_path: Path) -> None:
    """Surrounding whitespace on stdin is stripped before shape validation."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "t" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", "-", "--env-file", str(env_file)],
        input=f"   {api_key}   \n",
    )
    assert result.exit_code == 0, result.output
    assert api_key in env_file.read_text()


def test_init_with_key_dash_rejects_bad_shape(tmp_path: Path) -> None:
    """A malformed key piped via stdin is still rejected by the shape check."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    result = runner.invoke(
        cli,
        ["init", "--key", "-", "--env-file", str(env_file)],
        input="not-a-vera-key\n",
    )
    assert result.exit_code != 0
    assert "doesn't look like" in result.output
    assert not env_file.exists()


def test_init_with_key_dash_empty_stdin_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    result = runner.invoke(
        cli,
        ["init", "--key", "-", "--env-file", str(env_file)],
        input="",
    )
    assert result.exit_code != 0
    assert "stdin was empty" in result.output
    assert not env_file.exists()


def test_init_help_warns_about_ps_visibility() -> None:
    """The ``--key`` help text must warn that the value leaks into ps."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--help"])
    assert result.exit_code == 0
    assert "ps" in result.output
    assert "--key -" in result.output


def test_init_with_key_flag_writes_env(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert env_file.exists()
    contents = env_file.read_text()
    assert f"VERA_API_KEY={api_key}" in contents
    assert "VERA_API_URL=https://api.usevera.xyz" in contents
    assert "VERA_TENANT_ID=" in contents


def test_init_with_key_flag_writes_0600_mode(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    if sys.platform == "win32":
        pytest.skip("file mode bits don't carry the same meaning on Windows")
    mode = stat.S_IMODE(env_file.stat().st_mode)
    # Owner-only read/write — group + world bits must be zero.
    assert mode & 0o077 == 0, oct(mode)


def test_init_rejects_invalid_key_shape(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    result = runner.invoke(
        cli,
        ["init", "--key", "not-a-vera-key", "--env-file", str(env_file)],
    )
    assert result.exit_code != 0
    assert "doesn't look like" in result.output
    assert not env_file.exists()


def test_init_accepts_al_live_key(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_live_" + "y" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert "live key" in result.output


def test_init_custom_api_url_written(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--api-url",
            "https://custom.example.com",
        ],
    )
    assert result.exit_code == 0, result.output
    contents = env_file.read_text()
    assert "VERA_API_URL=https://custom.example.com" in contents


# ---------------------------------------------------------------------------
# Existing config short-circuit
# ---------------------------------------------------------------------------


def test_init_skips_if_env_file_exists(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    env_file.write_text("VERA_API_KEY=existing\n")
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0
    assert "already configured" in result.output
    # Existing file must NOT be clobbered.
    assert env_file.read_text() == "VERA_API_KEY=existing\n"


def test_init_proceeds_when_env_file_has_no_key(tmp_path: Path) -> None:
    """Fix #7: an .env that exists but has no VERA_API_KEY should NOT
    short-circuit init — clobbering an empty stub file isn't destructive."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    env_file.write_text("# placeholder, no key yet\n")
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    # Without ``--force`` we'd ordinarily expect a refusal-to-clobber,
    # but the existing-config summary returns None when no real key is
    # present, so init proceeds with default ``force=True`` semantics.
    assert result.exit_code == 0, result.output
    assert api_key in env_file.read_text()


def test_init_proceeds_when_env_file_has_empty_key(tmp_path: Path) -> None:
    """Fix #7: ``VERA_API_KEY=`` (empty value) doesn't count as configured."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    env_file.write_text("VERA_API_KEY=\nVERA_API_URL=https://api.example.com\n")
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert api_key in env_file.read_text()


def test_init_skips_if_env_var_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"  # doesn't exist
    monkeypatch.setenv("VERA_API_KEY", "al_test_" + "z" * 32)
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file)],
    )
    assert result.exit_code == 0
    assert "already configured" in result.output
    assert not env_file.exists()


def test_init_force_overwrites_existing(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    env_file.write_text("VERA_API_KEY=old\n")
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        ["init", "--key", api_key, "--env-file", str(env_file), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert env_file.read_text() != "VERA_API_KEY=old\n"
    assert api_key in env_file.read_text()


# ---------------------------------------------------------------------------
# Paste-back flow (monkeypatched getpass)
# ---------------------------------------------------------------------------


def test_init_paste_back_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "p" * 32
    # Force "headed" so the browser-open branch runs (but webbrowser is stubbed).
    monkeypatch.setattr(cli_mod, "_is_headless", lambda: False)
    monkeypatch.setattr(cli_mod.getpass, "getpass", lambda prompt="": api_key)
    result = runner.invoke(
        cli,
        ["init", "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert env_file.exists()
    assert api_key in env_file.read_text()


def test_init_paste_back_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "q" * 32
    monkeypatch.setattr(cli_mod, "_is_headless", lambda: False)

    attempts = iter(["bad-key-1", "bad-key-2", api_key])
    monkeypatch.setattr(
        cli_mod.getpass, "getpass", lambda prompt="": next(attempts)
    )
    result = runner.invoke(
        cli,
        ["init", "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert "2 attempt(s) left" in result.output or "1 attempt(s) left" in result.output
    assert api_key in env_file.read_text()


def test_init_paste_back_fails_after_3_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    monkeypatch.setattr(cli_mod, "_is_headless", lambda: False)
    monkeypatch.setattr(cli_mod.getpass, "getpass", lambda prompt="": "junk")
    result = runner.invoke(
        cli,
        ["init", "--env-file", str(env_file)],
    )
    assert result.exit_code != 0
    assert "shape invalid" in result.output
    assert not env_file.exists()


def test_init_headless_skips_browser_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In headless mode, `webbrowser.open` must NOT be called."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "h" * 32
    monkeypatch.setattr(cli_mod, "_is_headless", lambda: True)

    called = {"n": 0}

    def _fail(*a, **kw):
        called["n"] += 1
        return True

    monkeypatch.setattr(cli_mod.webbrowser, "open", _fail)
    monkeypatch.setattr(cli_mod.getpass, "getpass", lambda prompt="": api_key)
    result = runner.invoke(
        cli,
        ["init", "--env-file", str(env_file)],
    )
    assert result.exit_code == 0, result.output
    assert called["n"] == 0, "webbrowser.open must not run in headless mode"
    assert "headless" in result.output.lower()


# ---------------------------------------------------------------------------
# Shape validator unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "al_test_" + "x" * 32,
        "al_live_" + "y" * 32,
        "al_test_" + "a" * 16,  # minimum length
        "al_live_AbC-_d1234567890",
    ],
)
def test_validate_api_key_shape_accepts(key: str) -> None:
    assert cli_mod._validate_api_key_shape(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "",
        "al_test_short",
        "wrong_prefix_" + "x" * 32,
        "al_other_" + "x" * 32,
        "AL_TEST_" + "x" * 32,  # uppercase prefix not accepted
        "al_test_" + "x" * 32 + " with space",
    ],
)
def test_validate_api_key_shape_rejects(key: str) -> None:
    assert cli_mod._validate_api_key_shape(key) is False


def test_is_headless_ssh_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 22 5.6.7.8 22")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    assert cli_mod._is_headless() is True


def test_is_headless_ci_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert cli_mod._is_headless() is True


# ---------------------------------------------------------------------------
# URL injection / scheme validation (Phase 1 PR 11 review fix #1 + #3)
# ---------------------------------------------------------------------------


def test_init_rejects_api_url_with_newline_injection(tmp_path: Path) -> None:
    """``--api-url`` with an embedded newline would write a rogue
    ``ADMIN_PASSWORD=hijacked`` line into the generated .env. Must abort."""
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    malicious = "http://api.example.com\nADMIN_PASSWORD=hijacked"
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--api-url",
            malicious,
        ],
    )
    assert result.exit_code != 0
    assert "control characters" in result.output
    assert not env_file.exists()


def test_init_rejects_api_url_with_carriage_return(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--api-url",
            "http://api.example.com\rOTHER=1",
        ],
    )
    assert result.exit_code != 0
    assert "control characters" in result.output
    assert not env_file.exists()


def test_init_rejects_javascript_scheme_api_url(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--api-url",
            "javascript:alert(1)",
        ],
    )
    assert result.exit_code != 0
    assert "must be http(s)" in result.output
    assert not env_file.exists()


def test_init_rejects_file_scheme_dashboard_url(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--dashboard-url",
            "file:///etc/passwd",
        ],
    )
    assert result.exit_code != 0
    assert "must be http(s)" in result.output
    assert not env_file.exists()


def test_init_rejects_dashboard_url_with_newline(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--dashboard-url",
            "https://app.example.com\nEVIL=1",
        ],
    )
    assert result.exit_code != 0
    assert "control characters" in result.output
    assert not env_file.exists()


def test_init_rejects_api_url_without_host(tmp_path: Path) -> None:
    runner = CliRunner()
    env_file = tmp_path / ".env"
    api_key = "al_test_" + "x" * 32
    result = runner.invoke(
        cli,
        [
            "init",
            "--key",
            api_key,
            "--env-file",
            str(env_file),
            "--api-url",
            "https://",  # scheme but no netloc
        ],
    )
    assert result.exit_code != 0
    assert "no host" in result.output
    assert not env_file.exists()


def test_validate_url_helper_accepts_https() -> None:
    assert (
        cli_mod._validate_url("https://api.example.com", kind="api-url")
        == "https://api.example.com"
    )


def test_validate_url_helper_accepts_http() -> None:
    assert (
        cli_mod._validate_url("http://localhost:8000", kind="api-url")
        == "http://localhost:8000"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com\n",
        "http://api.example.com\r",
        "http://api.example.com\x00",
        "http://api.example.com\x1f",
        "http://api.example.com\x7f",
    ],
)
def test_validate_url_helper_rejects_control_chars(url: str) -> None:
    import click as _click

    with pytest.raises(_click.ClickException):
        cli_mod._validate_url(url, kind="api-url")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com",
        "data:text/html,<script>",
        "ssh://example.com",
        "",  # empty
        "not a url",  # no scheme
    ],
)
def test_validate_url_helper_rejects_bad_scheme(url: str) -> None:
    import click as _click

    with pytest.raises(_click.ClickException):
        cli_mod._validate_url(url, kind="api-url")


def test_write_env_file_rejects_control_chars_in_api_key(tmp_path: Path) -> None:
    """Defense-in-depth: even if a future caller bypasses CLI validation,
    the writer itself must refuse to interpolate a key with newlines."""
    env_file = tmp_path / ".env"
    with pytest.raises(Exception) as excinfo:
        cli_mod._write_env_file(
            env_file,
            api_key="al_test_xxx\nEVIL=1",
            api_url="https://api.example.com",
            tenant_id="",
            force=True,
        )
    assert "control characters" in str(excinfo.value)
    assert not env_file.exists()


def test_write_env_file_rejects_control_chars_in_api_url(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    with pytest.raises(Exception) as excinfo:
        cli_mod._write_env_file(
            env_file,
            api_key="al_test_" + "x" * 32,
            api_url="http://api.example.com\nADMIN=1",
            tenant_id="",
            force=True,
        )
    assert "control characters" in str(excinfo.value)
    assert not env_file.exists()


def test_write_env_file_rejects_control_chars_in_tenant_id(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    with pytest.raises(Exception) as excinfo:
        cli_mod._write_env_file(
            env_file,
            api_key="al_test_" + "x" * 32,
            api_url="https://api.example.com",
            tenant_id="tenant\nADMIN=1",
            force=True,
        )
    assert "control characters" in str(excinfo.value)
    assert not env_file.exists()


def test_write_env_file_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VERA_API_KEY=existing\n")
    with pytest.raises(FileExistsError):
        cli_mod._write_env_file(
            env_file,
            api_key="al_test_" + "x" * 32,
            api_url="https://api.example.com",
            tenant_id="",
        )
    # Existing file must be untouched.
    assert env_file.read_text() == "VERA_API_KEY=existing\n"


def test_write_env_file_overwrites_with_force(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VERA_API_KEY=existing\n")
    api_key = "al_test_" + "x" * 32
    cli_mod._write_env_file(
        env_file,
        api_key=api_key,
        api_url="https://api.example.com",
        tenant_id="",
        force=True,
    )
    assert api_key in env_file.read_text()


# ---------------------------------------------------------------------------
# _parse_env_file helper (fix #8)
# ---------------------------------------------------------------------------


def test_parse_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert cli_mod._parse_env_file(tmp_path / "does_not_exist.env") == {}


def test_parse_env_file_basic_keys(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("VERA_API_KEY=al_test_xyz\nVERA_TENANT_ID=acme\n")
    parsed = cli_mod._parse_env_file(p)
    assert parsed["VERA_API_KEY"] == "al_test_xyz"
    assert parsed["VERA_TENANT_ID"] == "acme"


def test_parse_env_file_strips_double_quotes(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text('VERA_API_KEY="al_test_xyz"\n')
    assert cli_mod._parse_env_file(p)["VERA_API_KEY"] == "al_test_xyz"


def test_parse_env_file_strips_single_quotes(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("VERA_API_KEY='al_test_xyz'\n")
    assert cli_mod._parse_env_file(p)["VERA_API_KEY"] == "al_test_xyz"


def test_parse_env_file_inline_comment_stripped(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("VERA_API_KEY=al_test_xyz  # this is a comment\n")
    assert cli_mod._parse_env_file(p)["VERA_API_KEY"] == "al_test_xyz"


def test_parse_env_file_hash_without_space_kept(tmp_path: Path) -> None:
    """A ``#`` not preceded by whitespace is part of the value."""
    p = tmp_path / ".env"
    p.write_text("VERA_API_KEY=al_test_xy#z\n")
    assert cli_mod._parse_env_file(p)["VERA_API_KEY"] == "al_test_xy#z"


def test_parse_env_file_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "\n"
        "# this is a comment\n"
        "\n"
        "VERA_API_KEY=al_test_xyz\n"
        "\n"
    )
    parsed = cli_mod._parse_env_file(p)
    assert parsed == {"VERA_API_KEY": "al_test_xyz"}


def test_parse_env_file_skips_lines_without_equals(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("not a key value line\nVERA_API_KEY=al_test_xyz\n")
    assert cli_mod._parse_env_file(p) == {"VERA_API_KEY": "al_test_xyz"}
