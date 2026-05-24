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
        # number-abbreviation-quantity (default tier).
        ('<p>2.8K decisions captured today</p>', "number-abbreviation-quantity"),
        ('<p>5K records</p>', "number-abbreviation-quantity"),
        ('<p>1M actions</p>', "number-abbreviation-quantity"),
        ('<p>3B events processed</p>', "number-abbreviation-quantity"),
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
# number-abbreviation-quantity — negative cases (no false positives)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        # Storage units must not trigger (regex requires a quantity noun after).
        '<p>upload limit 8MB per file</p>',
        '<p>2GB max</p>',
        # Video resolution — no quantity noun follows.
        '<p>4K display supported</p>',
        # Statutory dollar figures (regulations citations) — no operational
        # noun follows ("€35M penalty" is fine; "€35M decisions" would not be).
        '<p>EU AI Act: €35M or 7% of turnover</p>',
        '<p>$5K/day, compounding</p>',
        # Wizard volume bucket boundaries — range label, no noun after.
        '<p>10K – 100K</p>',
        # Random sentence with K in the middle is fine — needs digits-letter form.
        '<p>OK indicator</p>',
    ],
)
def test_abbreviation_rule_no_false_positives(tmp_path: Path, snippet: str) -> None:
    write(tmp_path, "frontend/page.tsx", snippet)
    violations = ccv.scan_paths([tmp_path / "frontend"])
    blocking = [v for v in violations if not v.allowed]
    abbrev_hits = [v for v in blocking if v.rule_id == "number-abbreviation-quantity"]
    assert abbrev_hits == [], (
        f"abbreviation rule should not fire on {snippet!r}, got {abbrev_hits}"
    )


# ---------------------------------------------------------------------------
# Strict-mode rules — gated behind --strict
# ---------------------------------------------------------------------------


def test_strict_rules_inactive_by_default(tmp_path: Path) -> None:
    # date-no-year, recommendation-language, tabular-nums-missing,
    # numbers-no-commas should NOT fire in default mode.
    write(
        tmp_path,
        "frontend/page.tsx",
        'format(d, "MMM d")\n'
        '<p>You should attest before continuing.</p>\n'
        '<p>{count.toLocaleString()}</p>\n'
        '<p>port 8080 timeout 5000ms</p>\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"], strict=False)
    blocking = [v for v in violations if not v.allowed and not v.warning]
    assert blocking == []


@pytest.mark.parametrize(
    "snippet,expected_id",
    [
        # date-no-year — short date format strings.
        ('format(d, "MMM d")', "date-no-year"),
        ("format(d, 'MMM dd')", "date-no-year"),
        # date-no-year — toLocaleDateString with month but no year.
        ('d.toLocaleDateString("en-US", { month: "short", day: "numeric" })', "date-no-year"),
        # recommendation-language — bare imperatives.
        ('<p>You should attest before continuing.</p>', "recommendation-language"),
        ('<p>We recommend that you upload the BAA.</p>', "recommendation-language"),
        ('<p>Make sure to upload the BAA.</p>', "recommendation-language"),
        ('<p>You must attest first.</p>', "recommendation-language"),
        # tabular-nums-missing — bare .toLocaleString() render.
        ('<p>{count.toLocaleString()}</p>', "tabular-nums-missing"),
    ],
)
def test_strict_rules_detect(tmp_path: Path, snippet: str, expected_id: str) -> None:
    write(tmp_path, "frontend/page.tsx", snippet)
    violations = ccv.scan_paths([tmp_path / "frontend"], strict=True)
    blocking = [v for v in violations if not v.allowed and not v.warning]
    assert expected_id in {v.rule_id for v in blocking}, (
        f"strict rule {expected_id!r} should fire on {snippet!r}, "
        f"got blocking={ids_of(blocking)}"
    )


@pytest.mark.parametrize(
    "snippet",
    [
        # date-no-year — full date format with year present is fine.
        'format(d, "MMM d, yyyy")',
        'd.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })',
        # recommendation-language — "Consider X" / "Recommended: X" are the OK forms.
        '<p>Consider uploading the BAA now.</p>',
        '<p>Recommended: upload the BAA.</p>',
        # "You should be" is a state-of-being phrase, not a bare imperative.
        '<p>You should be all set after uploading.</p>',
    ],
)
def test_strict_rules_no_false_positives(tmp_path: Path, snippet: str) -> None:
    write(tmp_path, "frontend/page.tsx", snippet)
    violations = ccv.scan_paths([tmp_path / "frontend"], strict=True)
    blocking = [v for v in violations if not v.allowed and not v.warning]
    assert blocking == [], (
        f"strict rules should not fire on {snippet!r}, got {ids_of(blocking)}"
    )


def test_numbers_no_commas_is_warning_only(tmp_path: Path) -> None:
    """The numbers-no-commas rule is warning-level — it surfaces but
    does not flip the exit code. Verify both: the rule fires on a
    legitimate 4+ digit run AND the violation is marked warning=True."""

    write(tmp_path, "frontend/page.tsx", "<p>12500 decisions</p>")
    violations = ccv.scan_paths([tmp_path / "frontend"], strict=True)
    blocking = [v for v in violations if not v.allowed and not v.warning]
    warns = [v for v in violations if not v.allowed and v.warning]
    assert any(v.rule_id == "numbers-no-commas" for v in warns)
    assert not any(v.rule_id == "numbers-no-commas" for v in blocking)


def test_copy_allow_suppresses_strict_rules_too(tmp_path: Path) -> None:
    """``# copy-allow`` markers must work in strict mode for the same
    rules as in default mode."""

    write(
        tmp_path,
        "frontend/page.tsx",
        '// copy-allow: legacy format string used in a non-display context\n'
        'format(d, "MMM d")\n',
    )
    violations = ccv.scan_paths([tmp_path / "frontend"], strict=True)
    blocking = [v for v in violations if not v.allowed and not v.warning]
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


# ---------------------------------------------------------------------------
# --strict flag — CLI behavior
# ---------------------------------------------------------------------------


def test_cli_strict_flag_enables_strict_rules(tmp_path: Path) -> None:
    # A clean (default-mode) input that contains a strict-only violation.
    write(
        tmp_path,
        "frontend/page.tsx",
        '<p>{count.toLocaleString()}</p>',
    )
    # Default mode → exit 0 (strict rule is not active).
    result = run_cli(["frontend"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    # Strict mode → exit 1 (tabular-nums-missing now blocks).
    strict = run_cli(["--strict", "frontend"], cwd=tmp_path)
    assert strict.returncode == 1
    assert "tabular-nums-missing" in strict.stderr


def test_cli_strict_warnings_do_not_block(tmp_path: Path) -> None:
    """Warning-tagged strict rules (e.g. numbers-no-commas) print but do
    NOT flip the exit code. Otherwise the strict mode would be
    unusable as a local audit tool."""

    write(tmp_path, "frontend/page.tsx", "<p>12500 records here</p>")
    result = run_cli(["--strict", "frontend"], cwd=tmp_path)
    # The numbers-no-commas rule prints a warning but does not block.
    assert result.returncode == 0, result.stderr
    assert "numbers-no-commas" in result.stderr
    assert "[warning]" in result.stderr


def test_cli_strict_json_includes_warnings(tmp_path: Path) -> None:
    write(tmp_path, "frontend/page.tsx", "<p>12500 records here</p>")
    result = run_cli(
        ["--strict", "--report-json", "frontend"],
        cwd=tmp_path,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["warnings"] >= 1
    assert payload["summary"]["blocking"] == 0
