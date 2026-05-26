#!/usr/bin/env bash
# scripts/check_iam_tier_usage.sh — CI lint rule banning direct
# ``ctx.tier == IamTier.X`` comparisons in backend route handlers.
#
# Why this rule exists
# --------------------
# Wave 3B.3 (PR #236) established the IAM tier model. ``IamTier.STAFF_FULL``
# is reserved for a v2 break-glass tier and MUST behave identically to
# ``STAFF_READ_ONLY`` in v1 (same redaction, same audit, same read-only
# surface). Code that branches on ``== IamTier.STAFF_READ_ONLY`` would
# silently treat a future STAFF_FULL caller as a customer — wrong tier,
# wrong audit, wrong PHI redaction. Likewise ``== IamTier.CUSTOMER`` is
# brittle: every new tier name forces a per-route fix.
#
# The fix is to branch on the ``ctx.is_staff`` / ``ctx.is_customer``
# boolean properties defined on ``AuthContext`` in
# ``backend/app/services/auth.py``. Those properties encode the policy
# in one place; route handlers never have to know the enum shape.
#
# The same antipattern was caught by ``/review`` twice in Phase 3:
#   * PR #236 (Wave 3B.3): ``backend/app/routes/staff.py:99`` —
#     CRITICAL finding.
#   * PR #240 (Wave 3D.1): ``backend/app/routes/dashboard_chain_integrity.py:48`` —
#     INFORMATIONAL finding.
# A third pass on develop today (the PR that ships this script) caught
# five more instances in ``approvals.py``, ``records.py``, and
# ``checkpoints_by_date.py`` — all fixed in the same commit that lands
# this lint rule.
#
# What this script does
# ---------------------
# Greps ``backend/app/routes/`` for lines matching
# ``ctx\.tier\s*==\s*IamTier\.`` (any tier, not just STAFF_READ_ONLY —
# CUSTOMER is equally brittle). Exits non-zero on any unmarked hit.
#
# Suppression
# -----------
# To document a deliberate exact-tier introspection (rare — most code
# wants ``is_staff`` / ``is_customer``), append an inline marker on the
# same line OR the line immediately preceding:
#
#     # iam-tier-direct-comparison-ok: <reason ≥8 chars>
#
# Examples of legitimate uses:
#   * A test asserting a specific tier was returned.
#   * Code inside ``services/iam.py`` itself that defines what each tier
#     means (the redactor, the tier resolver). The default scan excludes
#     ``services/`` so those don't need markers — but adding them in any
#     future cross-cutting helper inside ``routes/`` is the escape hatch.
#
# The reason is mandatory (≥8 chars) and is surfaced when the script
# runs with ``--report-json`` for auditability.
#
# Exit codes
# ----------
#   0 — no unmarked violations.
#   1 — one or more unmarked violations (each printed to stderr).
#   2 — usage / IO error.
#
# Why a shell script and not a ruff rule
# --------------------------------------
# The repo has no ruff configuration (no ``pyproject.toml`` at the repo
# root, no ``ruff.toml``). Adding ruff just for this one rule would add
# significant new infrastructure for a one-line regex check. A 100-line
# shell script with a Python self-test mirrors the ``check_copy_violations``
# pattern already in this directory, runs in <1s in CI, has zero
# dependencies, and is easy to extend with more single-regex IAM
# guardrails if they're needed later.

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
# Repo root: this script lives in ``<repo>/scripts/``.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# The pattern. We match ``ctx.tier == IamTier.<NAME>`` with optional
# whitespace. The leading ``ctx\.`` anchor catches the common form;
# tests asserting tier values use different names (``result.tier``,
# ``auth.tier``, etc.) and are intentionally NOT linted by this rule —
# tests SHOULD assert on the enum directly.
#
# We also match the inverted ``IamTier.X == ctx.tier`` form (Yoda
# comparison) because the same antipattern applies regardless of operand
# order.
PATTERN='(ctx\.tier[[:space:]]*==[[:space:]]*IamTier\.|IamTier\.[A-Z_]+[[:space:]]*==[[:space:]]*ctx\.tier)'

ALLOW_MARKER="iam-tier-direct-comparison-ok:"
ALLOW_REASON_MIN_LENGTH=8

# ── Help / arg parsing ────────────────────────────────────────────────
# Accept any order: ``check_iam_tier_usage.sh [--report-json] [PATH]`` or
# ``check_iam_tier_usage.sh [PATH] [--report-json]``. The first
# non-flag positional is the scan root; flags can appear anywhere.
REPORT_JSON=0
SCAN_ROOT=""
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            cat <<EOF
Usage: $(basename "$0") [SCAN_ROOT] [--report-json]

Scans SCAN_ROOT (default: backend/app/routes) for direct
``ctx.tier == IamTier.X`` comparisons. Exits 1 on any unmarked hit.

Suppress a legitimate occurrence with an inline comment:
    # iam-tier-direct-comparison-ok: <reason ≥${ALLOW_REASON_MIN_LENGTH} chars>

Place the marker on the same line as the violation OR on the line
immediately preceding.

See ``backend/app/services/auth.py`` AuthContext.is_staff /
AuthContext.is_customer for the canonical fix.
EOF
            exit 0
            ;;
        --report-json)
            REPORT_JSON=1
            ;;
        --*)
            echo "error: unknown flag: $arg" >&2
            exit 2
            ;;
        *)
            if [[ -z "$SCAN_ROOT" ]]; then
                SCAN_ROOT="$arg"
            else
                echo "error: multiple scan roots given: $SCAN_ROOT and $arg" >&2
                exit 2
            fi
            ;;
    esac
done

# Default scan root if none given.
if [[ -z "$SCAN_ROOT" ]]; then
    SCAN_ROOT="${REPO_ROOT}/backend/app/routes"
fi

if [[ ! -d "$SCAN_ROOT" && ! -f "$SCAN_ROOT" ]]; then
    echo "error: scan root not found: $SCAN_ROOT" >&2
    exit 2
fi

# ── Scan ──────────────────────────────────────────────────────────────
# grep prints ``<path>:<lineno>:<matched line>``. We use ``-E`` (ERE),
# ``-n`` (line number), ``-H`` (always print filename even on a single
# file), ``--include='*.py'`` (Python only), and ``-r`` (recursive — a
# no-op on single files).
#
# ``|| true`` so an empty grep doesn't trip ``set -e``.

raw_hits="$(grep -rEnH --include='*.py' "$PATTERN" "$SCAN_ROOT" 2>/dev/null || true)"

if [[ -z "$raw_hits" ]]; then
    if [[ "$REPORT_JSON" == "1" ]]; then
        printf '{"summary":{"total":0,"blocking":0,"allowed":0},"violations":[]}\n'
    fi
    exit 0
fi

# ── Per-hit allow-marker check ────────────────────────────────────────
# For each hit, we need to read the violation line + the line immediately
# above and look for the suppression marker. We do this in Python (via
# stdlib only) because line-above lookups are messy in pure bash and we
# need json output for auditability.
#
# We pass the raw hits to Python via the ``RAW_HITS`` env var (bash
# can't redirect stdin twice — once for the heredoc that holds the
# Python source, once for the data).

RAW_HITS="$raw_hits" python3 - "$ALLOW_MARKER" "$ALLOW_REASON_MIN_LENGTH" "$REPORT_JSON" <<'PY'
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ALLOW_MARKER = sys.argv[1]
MIN_REASON_LEN = int(sys.argv[2])
REPORT_JSON = sys.argv[3] == "1"

raw = os.environ.get("RAW_HITS", "").strip()
if not raw:
    if REPORT_JSON:
        print(json.dumps({"summary": {"total": 0, "blocking": 0, "allowed": 0}, "violations": []}))
    sys.exit(0)

# grep output: <path>:<lineno>:<line>
ENTRY_RE = re.compile(r"^(?P<path>[^:]+):(?P<lineno>\d+):(?P<line>.*)$")

# Suppression-marker regex. The marker MUST appear inside a comment
# (``#`` introducer in Python). We accept the marker on the same line
# OR the immediately preceding line. The reason is the text AFTER the
# marker, trimmed, and must be at least MIN_REASON_LEN chars.
MARKER_RE = re.compile(
    r"#[^\n]*?" + re.escape(ALLOW_MARKER) + r"\s*(?P<reason>[^\n]*)"
)

# Group hits by file so we open each file once.
by_file: dict[str, list[tuple[int, str]]] = defaultdict(list)
for raw_line in raw.splitlines():
    m = ENTRY_RE.match(raw_line)
    if not m:
        continue
    by_file[m.group("path")].append((int(m.group("lineno")), m.group("line")))

violations = []  # list of {path, line, matched_text, allowed, allow_reason}
for path, hits in by_file.items():
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        # Couldn't re-read — treat all hits as unsuppressed.
        for lineno, matched in hits:
            violations.append({
                "path": path,
                "line": lineno,
                "matched_text": matched.strip(),
                "allowed": False,
                "allow_reason": None,
            })
        continue
    for lineno, matched in hits:
        # 1-indexed line; ``lines[lineno-1]`` is the violation,
        # ``lines[lineno-2]`` is the line above (if any).
        same = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        above = lines[lineno - 2] if lineno >= 2 else ""
        reason = None
        for src in (same, above):
            mm = MARKER_RE.search(src)
            if mm:
                candidate = mm.group("reason").strip()
                if len(candidate) >= MIN_REASON_LEN:
                    reason = candidate
                    break
        violations.append({
            "path": path,
            "line": lineno,
            "matched_text": matched.strip(),
            "allowed": reason is not None,
            "allow_reason": reason,
        })

blocking = [v for v in violations if not v["allowed"]]
allowed = [v for v in violations if v["allowed"]]

if REPORT_JSON:
    print(json.dumps({
        "summary": {
            "total": len(violations),
            "blocking": len(blocking),
            "allowed": len(allowed),
        },
        "violations": violations,
    }, indent=2))

# Pretty-print to stderr so CI logs show the issues.
for v in blocking:
    print(
        f"{v['path']}:{v['line']}: iam-tier-direct-comparison "
        f"({v['matched_text']!r}): use ctx.is_staff / ctx.is_customer "
        f"instead of ctx.tier == IamTier.X. See "
        f"backend/app/services/auth.py AuthContext.is_staff for the "
        f"canonical fix. Suppress with "
        f"`# {ALLOW_MARKER} <reason ≥{MIN_REASON_LEN} chars>` if this "
        f"is a deliberate exact-tier introspection.",
        file=sys.stderr,
    )

if blocking:
    print(
        f"\n{len(blocking)} unmarked direct ctx.tier comparison(s) found "
        f"({len(allowed)} suppressed by # {ALLOW_MARKER}).",
        file=sys.stderr,
    )
    sys.exit(1)
sys.exit(0)
PY
