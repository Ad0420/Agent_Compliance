#!/usr/bin/env python3
"""
Vera copy-violation checker.

Scans user-facing surfaces (default: ``frontend/``) for banned vocabulary
that violates the brand voice rules captured in ``CLAUDE.md`` and the
dashboard-design-system / landing-design / v1-implementation-plan
specs. Examples of banned tokens: ``court-admissible``, ``court-ready``,
``cryptographic proof``, ``proof-of-existence``, ``fully compliant``,
``Welcome back``, plus context-sensitive ``Hospital`` / ``Tenant`` /
``score`` matches.

Output: each violation as ``path:line:column: <token>: <message>`` to
stderr. Exit 0 on clean input, 1 on any violations. A ``copy-allow:
<reason>`` marker that appears inside a comment (``#``, ``//``,
``/* ... */`` or ``<!-- ... -->``) on the same line (or the immediately
preceding line) suppresses the violation; the reason is required and is
surfaced in ``--report-json`` output for auditability. The marker MUST
be preceded by a comment introducer on the same line — string literals
that contain the text ``copy-allow:`` do NOT suppress.

Stdlib-only (Python 3.10+). No external deps.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------
#
# Each rule is a regex compiled with re.IGNORECASE unless ``case_sensitive``
# is True. ``message`` is what we print to stderr. ``id`` is what we use in
# JSON output and in ``# copy-allow`` suppression scoping (currently global —
# any ``# copy-allow`` suppresses all rules on its line, mirroring how
# ``# noqa`` works without a code).


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    message: str


def _rx(pattern: str, *, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


RULES: tuple[Rule, ...] = (
    Rule(
        id="court-admissible",
        # Matches "court-admissible", "court admissible", "court-ready",
        # "court ready" — the four variants called out in CLAUDE.md.
        pattern=_rx(r"court[\s-]?(?:admissible|ready)"),
        message='banned: use "regulator-ready" or "evidence trail" instead',
    ),
    Rule(
        id="cryptographic-proof",
        pattern=_rx(r"cryptographic\s+proof"),
        message='banned in user-facing copy: use "verification evidence" or "hash-chain verification"',
    ),
    Rule(
        id="proof-of-existence",
        pattern=_rx(r"proof[\s-]of[\s-]existence"),
        message='banned: use "verification evidence" or "audit evidence packet"',
    ),
    Rule(
        id="fully-compliant",
        pattern=_rx(r"fully\s+compliant"),
        message='banned per Delve guardrail: use "All checks passing" or "No current blockers"',
    ),
    Rule(
        id="compliant-indicator",
        pattern=_rx(r"compliant\s+indicator"),
        message='banned per Delve guardrail: use "OK indicator" instead',
    ),
    Rule(
        id="welcome-back",
        pattern=_rx(r"welcome\s+back"),
        message='banned marketing chrome: no "Welcome back" copy in the dashboard',
    ),
    Rule(
        id="hospital-label",
        # Only flags Hospital when used as a UI label or as a "tenant: hospital"
        # type construct. Plain mentions of hospitals in onboarding copy that
        # legitimately describe hospitals must add # copy-allow with a reason.
        pattern=_rx(
            r"""(
                label\s*=\s*["']\s*Hospital\s*["']        # JSX label="Hospital"
                |
                aria-label\s*=\s*["']\s*Hospital\s*["']   # aria-label="Hospital"
                |
                placeholder\s*=\s*["']\s*Hospital\s*["']  # placeholder="Hospital"
                |
                title\s*=\s*["']\s*Hospital\s*["']        # title="Hospital"
                |
                tenant\s*:\s*hospital                     # "tenant: hospital"
            )""",
            flags=re.IGNORECASE | re.VERBOSE,
        ),
        message='use "Customer" not "Hospital" as a UI label',
    ),
    Rule(
        id="tenant-label",
        # Same caveat as hospital — flag only when used as a user-facing label
        # in JSX. Backend / SDK code paths refer to "tenant" legitimately and
        # are not scanned by default.
        pattern=_rx(
            r"""(
                label\s*=\s*["']\s*Tenant\s*["']
                |
                aria-label\s*=\s*["']\s*Tenant\s*["']
                |
                placeholder\s*=\s*["']\s*Tenant\s*["']
                |
                title\s*=\s*["']\s*Tenant\s*["']
                |
                >\s*Tenant\s*<                            # JSX child >Tenant<
            )""",
            flags=re.IGNORECASE | re.VERBOSE,
        ),
        message='use "Customer" not "Tenant" as a UI label',
    ),
    Rule(
        id="posture-score",
        # "posture score" and "compliance score" in either order — flag both.
        # Tightened to the two-word adjacent form; bare "score" is too noisy.
        pattern=_rx(r"\b(?:posture|compliance)\s+score\b"),
        message='use "posture" not "score" in posture/compliance contexts',
    ),
)


# ---------------------------------------------------------------------------
# File walking
# ---------------------------------------------------------------------------

DEFAULT_ROOT = Path("frontend")

EXCLUDED_DIRS = {
    "node_modules",
    ".next",
    "dist",
    "coverage",
    ".turbo",
    ".cache",
    "build",
    "out",
}

SCANNED_EXTENSIONS = {
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    ".md",
    ".mdx",
    ".html",
    # ``.json`` is intentionally excluded: JSON has no comment syntax, so a
    # legitimate i18n string table containing words like "Hospital" or
    # "score" would have no escape hatch (the ``copy-allow:`` marker
    # requires a comment introducer). User-facing copy lives in the .tsx /
    # .ts / .md surfaces above.
}

ALLOW_TOKEN = "copy-allow:"

# The suppression marker MUST be introduced by a comment character on the
# same line. This prevents string literals such as
# ``const sneaky = "court-admissible // copy-allow: x"`` from silently
# disabling rules. Comment styles covered: ``#`` (Python/shell/yaml),
# ``//`` (JS/TS), ``/*`` (block comment start), and ``<!--`` (HTML/MDX).
#
# We additionally verify (in ``_allow_reason_from_line``) that the comment
# introducer is not itself sitting inside an open string literal — the
# regex alone can't tell ``"// copy-allow:"`` (inside a quoted string)
# from a real trailing comment.
ALLOW_RE = re.compile(
    r"(?P<intro>#|//|/\*|<!--)\s*copy-allow:\s*(?P<reason>.*)"
)


def _intro_is_inside_string(line: str, intro_pos: int) -> bool:
    """True if the character at ``intro_pos`` sits inside an open string
    literal. We scan left-to-right and toggle quote state on unescaped
    ``"``, ``'``, or backtick. Naive but sufficient for catching the
    common bypass: ``const sneaky = "court-admissible // copy-allow: x"``.
    """

    in_quote: str | None = None
    i = 0
    while i < intro_pos:
        ch = line[i]
        if in_quote is None:
            if ch in ('"', "'", "`"):
                in_quote = ch
        else:
            if ch == "\\":
                # Skip the escaped character.
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        i += 1
    return in_quote is not None


@dataclass
class Violation:
    path: str
    line: int
    column: int
    rule_id: str
    matched_text: str
    message: str
    allowed: bool = False
    allow_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def iter_target_files(
    roots: Iterable[Path],
    *,
    paths_glob: str | None = None,
) -> Iterator[Path]:
    """Yield candidate files under any of ``roots``.

    ``paths_glob`` further restricts results by matching the candidate's
    path-string against the glob (``fnmatch`` semantics).
    """

    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in SCANNED_EXTENSIONS and root not in seen:
                if paths_glob is None or fnmatch.fnmatch(str(root), paths_glob):
                    seen.add(root)
                    yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in place so os.walk skips them.
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix not in SCANNED_EXTENSIONS:
                    continue
                if paths_glob is not None and not fnmatch.fnmatch(str(p), paths_glob):
                    continue
                if p in seen:
                    continue
                seen.add(p)
                yield p


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------


def _allow_reason_from_line(line: str) -> str | None:
    """Return the reason string from a ``copy-allow: <reason>`` suppression
    marker, or None if the line carries no such marker. The marker MUST be
    preceded by a comment introducer (``#``, ``//``, ``/*``, ``<!--``) on
    the same line — bare string literals containing ``copy-allow:`` do
    not count, because that bypass would silence every rule on a line
    that just happens to mention the token (e.g. test fixtures, docs).
    The comment introducer must also live outside any open string literal
    on the line, defeating the ``"// copy-allow:"``-inside-a-string bypass.
    """

    for m in ALLOW_RE.finditer(line):
        if _intro_is_inside_string(line, m.start("intro")):
            continue
        reason = m.group("reason").strip()
        # Trim common trailing comment-end tokens.
        for trailing in ("*/", "-->", "//"):
            if reason.endswith(trailing):
                reason = reason[: -len(trailing)].strip()
        return reason or ""  # empty string means "marker present but no reason"
    return None


def scan_file(path: Path) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Binary or unreadable — skip silently.
        return []

    lines = text.splitlines()
    violations: list[Violation] = []

    for line_no, raw_line in enumerate(lines, start=1):
        # Suppression marker scoping: same line OR previous line.
        same_line_reason = _allow_reason_from_line(raw_line)
        prev_line_reason = (
            _allow_reason_from_line(lines[line_no - 2])
            if line_no >= 2 else None
        )

        for rule in RULES:
            for m in rule.pattern.finditer(raw_line):
                # If this line *is* a suppression marker carrying the
                # matched text (e.g. a comment explaining the rule), the
                # same-line allow applies. Likewise prev-line allow.
                allow_reason = same_line_reason if same_line_reason is not None else prev_line_reason
                allowed = allow_reason is not None and allow_reason != ""
                violations.append(
                    Violation(
                        path=str(path),
                        line=line_no,
                        column=m.start() + 1,
                        rule_id=rule.id,
                        matched_text=m.group(0),
                        message=rule.message,
                        allowed=allowed,
                        allow_reason=allow_reason if allowed else None,
                    )
                )

    return violations


def scan_paths(
    roots: list[Path],
    *,
    paths_glob: str | None = None,
) -> list[Violation]:
    out: list[Violation] = []
    for f in iter_target_files(roots, paths_glob=paths_glob):
        out.extend(scan_file(f))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_violation(v: Violation) -> str:
    return (
        f"{v.path}:{v.line}:{v.column}: {v.rule_id} "
        f"({v.matched_text!r}): {v.message}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_copy_violations",
        description=(
            "Scan user-facing surfaces for banned vocabulary. "
            "Exit 0 if clean, 1 if any violations found."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="Optional explicit roots to scan. Defaults to ./frontend.",
    )
    parser.add_argument(
        "--paths",
        dest="paths_glob",
        default=None,
        help="Restrict scan to paths matching this glob (fnmatch).",
    )
    parser.add_argument(
        "--report-json",
        dest="report_json",
        action="store_true",
        help="Emit violations as JSON to stdout (allowlisted entries included).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="No-op placeholder; autofix not implemented in v1.",
    )
    args = parser.parse_args(argv)

    if args.fix:
        print("fix mode not implemented", file=sys.stderr)

    roots = args.roots if args.roots else [DEFAULT_ROOT]

    violations = scan_paths(roots, paths_glob=args.paths_glob)
    blocking = [v for v in violations if not v.allowed]

    if args.report_json:
        report = {
            "summary": {
                "total": len(violations),
                "blocking": len(blocking),
                "allowed": len(violations) - len(blocking),
            },
            "violations": [v.to_dict() for v in violations],
        }
        print(json.dumps(report, indent=2))

    for v in blocking:
        print(_format_violation(v), file=sys.stderr)

    if blocking:
        print(
            f"\n{len(blocking)} copy violation(s) found "
            f"({len(violations) - len(blocking)} suppressed by # copy-allow).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
