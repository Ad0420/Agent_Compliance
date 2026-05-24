"""Tests for ``vera review-status`` (Phase 1 PR 11 / Stream E4 stub).

The body of the command is filled in alongside the Phase 2 backend.
For Phase 1 it just exists in the CLI surface and prints a clear
"this is coming" message so callers can wire it into scripts now and
get a real result later without changing the CLI shape.
"""

from __future__ import annotations

from click.testing import CliRunner

from vera.cli import cli


def test_review_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "--help"])
    assert result.exit_code == 0
    assert "review_id" in result.output.lower() or "REVIEW_ID" in result.output


def test_review_status_prints_stub_message() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "rev_abc123"])
    assert result.exit_code == 0
    assert "rev_abc123" in result.output
    assert "Phase 2" in result.output


def test_review_status_requires_argument() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status"])
    # Click exits 2 on missing required argument.
    assert result.exit_code != 0
    assert "REVIEW_ID" in result.output or "review_id" in result.output.lower()


def test_review_status_shape_in_cli_list() -> None:
    """The stub must appear in `vera --help` so callers can discover it."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "review-status" in result.output
