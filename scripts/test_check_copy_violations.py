"""Tests for ``scripts/check_copy_violations.py``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_copy_violations.py"

# Reuse the module's scanning primitives for fast unit checks.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_copy_violations as ccv  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write(tmp_path: Path, name: str, contents: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def run_cli(args: Iterable[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def ids_of(violations) -> set[str]:
    return {v.rule_id for v in violations}


# ---------------------------------------------------------------------------
# Per-rule detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet,expected_id",
    [
        ('<p>This is court-admissible evidence.</p>', "court-admissible"),
        ('<p>court ready audit trail</p>', "court-admissible"),
        ('<p>Court-Ready logs</p>', "court-admissible"),
        ('<span>cryptographic proof of integrity</span>', "cryptographic-proof"),
        ('<div>proof-of-existence</div>', "proof-of-existence"),
        ('<div>proof of existence anchor</div>', "proof-of-existence"),
        ('<p>Fully compliant with HIPAA</p>', "fully-compliant"),
        ('<span>compliant indicator</span>', "compliant-indicator"),
        ('<h1>Welcome back, John!</h1>', "welcome-back"),
        ('<label label="Hospital">Foo</label>', "hospital-label"),
        ('<input placeholder="Tenant" />', "tenant-label"),
        ('<p>posture score: 8/10</p>', "posture-score"),
        ('<p>compliance score</p>', "posture-score"),
    ],
)
def test_detects_each_token(tmp_path: Path, snippet: str, expected_id: str) -> None:
    write(tmp_path, "frontend/page.tsx", snippet)
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert expected_id in {v.rule_id for v in blocking}, (
        f"expected rule {expected_id!r} to fire on {snippet!r}, got {ids_of(blocking)}"
    )


def test_clean_input_has_no_violations(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/page.tsx",
        '<p>Vera produces a regulator-ready evidence trail. All checks passing.</p>',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert blocking == []


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------


def test_same_line_allow_with_reason_suppresses(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/onboarding.tsx",
        # The literal "Hospital" here is the customer-type label in onboarding
        # copy where it legitimately names hospitals.
        '<label label="Hospital">Org type</label>  // copy-allow: onboarding lists actual customer industries\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert blocking == []
    # The allowed violation is still captured for JSON output.
    assert any(v.allowed for v in violations)


def test_previous_line_allow_suppresses(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/x.tsx",
        "// copy-allow: legitimate marketing context approved by counsel\n"
        "<p>court-admissible evidence packet</p>\n",
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert blocking == []


def test_allow_without_reason_does_not_suppress(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/x.tsx",
        '<p>court-admissible</p>  // copy-allow:\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    # Empty reason → not a valid suppression.
    assert any(v.rule_id == "court-admissible" for v in blocking)


def test_string_literal_copy_allow_does_not_suppress(tmp_path: Path) -> None:
    """A string literal that contains the substring ``copy-allow:`` must
    NOT silence the rules on its line — only a real comment-prefixed
    marker counts. Regression for the naive ``line.find("copy-allow:")``
    bypass."""

    write(
        tmp_path,
        "frontend/x.tsx",
        'const sneaky = "court-admissible // copy-allow: bypass";\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert any(v.rule_id == "court-admissible" for v in blocking), (
        "string-literal copy-allow: must not silence violations"
    )


def test_real_comment_copy_allow_still_suppresses(tmp_path: Path) -> None:
    """Companion to the string-literal test: an honest ``// copy-allow:``
    comment with a reason continues to suppress as before."""

    write(
        tmp_path,
        "frontend/x.tsx",
        '<p>court-admissible</p>  // copy-allow: legacy term in source quote\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert blocking == []
    assert any(v.allowed and v.allow_reason for v in violations)


def test_hash_comment_copy_allow_suppresses(tmp_path: Path) -> None:
    """``#``-style comments (Python, shell, yaml) must also count as a
    valid suppression introducer."""

    write(
        tmp_path,
        "frontend/notes.md",
        "court-admissible  # copy-allow: legitimate quoting in doc\n",
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    assert blocking == []


# ---------------------------------------------------------------------------
# Excluded directories / extensions
# ---------------------------------------------------------------------------


def test_node_modules_is_skipped(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/node_modules/pkg/page.tsx",
        '<p>court-admissible</p>',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"])
    assert violations == []


def test_unknown_extension_is_skipped(tmp_path: Path) -> None:
    write(tmp_path, "frontend/notes.txt", "court-admissible")
    violations = ccv.scan_paths([tmp_path / "frontend"])
    assert violations == []


# ---------------------------------------------------------------------------
# CLI behavior
# ---------------------------------------------------------------------------


def test_cli_exits_zero_on_clean_input(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/page.tsx",
        "<p>regulator-ready evidence trail</p>",
    )
    result = run_cli(["frontend"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_cli_exits_one_on_violation(tmp_path: Path) -> None:
    write(tmp_path, "frontend/page.tsx", "<p>court-admissible</p>")
    result = run_cli(["frontend"], cwd=tmp_path)
    assert result.returncode == 1
    assert "court-admissible" in result.stderr


def test_cli_report_json_emits_structured_output(tmp_path: Path) -> None:
    write(
        tmp_path,
        "frontend/page.tsx",
        "// copy-allow: allowlisted-for-test reason\n"
        "<p>court-admissible</p>\n",
    )
    result = run_cli(["--report-json", "frontend"], cwd=tmp_path)
    # Allowed entry → exit 0 (no blocking violations).
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["blocking"] == 0
    assert payload["summary"]["allowed"] == 1
    allowed = [v for v in payload["violations"] if v["allowed"]]
    assert allowed and allowed[0]["allow_reason"] == "allowlisted-for-test reason"


def test_cli_fix_is_noop(tmp_path: Path) -> None:
    write(tmp_path, "frontend/page.tsx", "<p>regulator-ready</p>")
    result = run_cli(["--fix", "frontend"], cwd=tmp_path)
    assert result.returncode == 0
    assert "fix mode not implemented" in result.stderr


def test_cli_paths_glob_restricts_scope(tmp_path: Path) -> None:
    write(tmp_path, "frontend/a.tsx", "<p>court-admissible</p>")
    write(tmp_path, "frontend/b.tsx", "<p>court-admissible</p>")
    # Glob that only matches a.tsx — b.tsx is ignored.
    result = run_cli(["--paths", "*a.tsx", "frontend"], cwd=tmp_path)
    assert result.returncode == 1
    assert "a.tsx" in result.stderr
    assert "b.tsx" not in result.stderr
