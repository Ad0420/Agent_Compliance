"""Tests for ``scripts/check_iam_tier_usage.sh``.

Mirrors the test layout used by ``test_check_copy_violations.py``:
spawn the script via subprocess with a tmp_path scan root, assert the
exit code + stderr message shape. The script is shell + an embedded
Python heredoc — these tests treat it as an opaque CLI.

Coverage:

* A fixture file containing a ``ctx.tier == IamTier.STAFF_READ_ONLY``
  line exits non-zero with a useful error message.
* The CUSTOMER variant (``ctx.tier == IamTier.CUSTOMER``) is ALSO
  flagged — the rule is about direct-equality on ANY tier, not just
  staff.
* The Yoda variant (``IamTier.STAFF_READ_ONLY == ctx.tier``) is also
  flagged.
* A line carrying ``# iam-tier-direct-comparison-ok: <reason>`` on the
  same line passes.
* A line carrying the marker on the IMMEDIATELY preceding line passes.
* A marker with a too-short reason (``# iam-tier-direct-comparison-ok: x``)
  does NOT suppress — the violation still fires.
* A bare marker without any reason does NOT suppress.
* A clean file (uses ``ctx.is_staff``) exits 0.
* ``--report-json`` emits a JSON document with the right summary
  totals and includes the ``allow_reason`` field for auditability.
* Non-Python files in the scan root are ignored (``.txt`` next to a
  fixture).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_iam_tier_usage.sh"


def write(tmp_path: Path, name: str, contents: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def run(scan_root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(scan_root), *extra],
        capture_output=True,
        text=True,
    )


# ── Detection ────────────────────────────────────────────────────────


def test_flags_staff_read_only_comparison(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "from app.services.iam import IamTier\n"
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "iam-tier-direct-comparison" in result.stderr
    assert "ctx.is_staff" in result.stderr, (
        "error message must point at the canonical fix"
    )
    assert "auth.py" in result.stderr, "error must link to AuthContext"


def test_flags_customer_comparison(tmp_path: Path) -> None:
    """The rule fires on ANY tier — CUSTOMER is equally brittle."""
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.CUSTOMER:\n"
        "        return 'customer'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "IamTier.CUSTOMER" in result.stderr


def test_flags_yoda_comparison(tmp_path: Path) -> None:
    """``IamTier.X == ctx.tier`` is the same antipattern."""
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if IamTier.STAFF_READ_ONLY == ctx.tier:\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 1, result.stdout + result.stderr


def test_clean_file_passes(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.is_staff:\n"
        "        return 'staff'\n"
        "    if ctx.is_customer:\n"
        "        return 'customer'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 0, result.stdout + result.stderr


# ── Suppression marker ───────────────────────────────────────────────


def test_same_line_marker_suppresses(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:  "
        "# iam-tier-direct-comparison-ok: testing exact-tier introspection\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 0, (
        f"same-line allow-marker should suppress; stderr={result.stderr}"
    )


def test_preceding_line_marker_suppresses(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    # iam-tier-direct-comparison-ok: deliberate exact-tier probe in test helper\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 0, (
        f"preceding-line allow-marker should suppress; stderr={result.stderr}"
    )


def test_short_reason_does_not_suppress(tmp_path: Path) -> None:
    """A reason under the 8-char minimum is treated as no reason."""
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:  "
        "# iam-tier-direct-comparison-ok: x\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 1, (
        "marker with sub-minimum reason should NOT suppress"
    )


def test_empty_reason_does_not_suppress(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:  "
        "# iam-tier-direct-comparison-ok:\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 1


# ── JSON report ──────────────────────────────────────────────────────


def test_report_json_shape(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.tier == IamTier.STAFF_READ_ONLY:  "
        "# iam-tier-direct-comparison-ok: deliberate exact-tier introspection here\n"
        "        return 'staff'\n"
        "    if ctx.tier == IamTier.CUSTOMER:\n"
        "        return 'customer'\n",
    )
    result = run(tmp_path / "routes", "--report-json")
    # Exit code is 1 (one unsuppressed violation). JSON report still
    # prints to stdout.
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["summary"]["total"] == 2
    assert report["summary"]["blocking"] == 1
    assert report["summary"]["allowed"] == 1
    allowed_entry = next(v for v in report["violations"] if v["allowed"])
    assert allowed_entry["allow_reason"] == (
        "deliberate exact-tier introspection here"
    )


def test_report_json_clean(tmp_path: Path) -> None:
    write(
        tmp_path,
        "routes/example.py",
        "def handler(ctx):\n"
        "    if ctx.is_staff:\n"
        "        return 'staff'\n",
    )
    result = run(tmp_path / "routes", "--report-json")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["summary"]["total"] == 0
    assert report["violations"] == []


# ── File filtering ───────────────────────────────────────────────────


def test_non_python_files_ignored(tmp_path: Path) -> None:
    """Markdown / text files mentioning the pattern in docs prose
    should not be linted. The rule applies to ``.py`` route handlers
    only."""

    write(
        tmp_path,
        "routes/README.md",
        "Do not write `ctx.tier == IamTier.STAFF_READ_ONLY` — use "
        "`ctx.is_staff` instead.\n",
    )
    result = run(tmp_path / "routes")
    assert result.returncode == 0, (
        f"docs file should not be linted; stderr={result.stderr}"
    )


# ── Develop-tree regression: the actual routes folder must stay clean ─


def test_actual_routes_folder_is_clean() -> None:
    """End-to-end regression: running the script against the real
    ``backend/app/routes`` tree on develop must exit 0.

    This is the contract: the lint rule lands GREEN. If this test
    fails, either:

    * a new unflagged violation was introduced in develop (fix it
      with ``ctx.is_staff`` / ``ctx.is_customer``), OR
    * the regex was widened and is now hitting a legitimate pattern
      (narrow the regex or suppress with the inline marker).
    """

    routes = REPO_ROOT / "backend" / "app" / "routes"
    if not routes.is_dir():
        pytest.skip("backend/app/routes/ not present in this checkout")
    result = subprocess.run(
        ["bash", str(SCRIPT), str(routes)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "scripts/check_iam_tier_usage.sh found unmarked violations on "
        "develop — review backend/app/routes/ for ``ctx.tier == "
        "IamTier.X`` comparisons.\n\n"
        f"stderr:\n{result.stderr}"
    )
