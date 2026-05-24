#!/usr/bin/env python3
"""
Vera copy-violation checker.

Scans user-facing surfaces (default: ``frontend/``) for banned vocabulary
and voice-style violations from ``CLAUDE.md``, ``dashboard-design-system.md``
§Voice & copy, ``landing-design.md``, and ``v1-implementation-plan.md``.

Rule classes
============

The checker ships two tiers of rules:

1. **Default rules** (always on, gate CI). Hand-picked for near-zero
   false-positive rate. CI runs ``python scripts/check_copy_violations.py``
   without arguments — any default-rule hit fails the build. Examples:
   ``court-admissible``, ``cryptographic proof``, ``Welcome back``,
   ``Hospital`` / ``Tenant`` labels, ``posture score``,
   ``5K`` / ``2M`` / ``3B`` number abbreviations under 10K.

2. **Strict rules** (opt-in via ``--strict``). Heuristic-grade rules
   with non-trivial false-positive rates. Run locally before opening a
   PR; they intentionally do NOT gate CI in v1 because the noise would
   block work. Examples: date-format-without-year, recommendation-
   language without "Consider X" / "Recommended:", bare-number
   rendering without ``tabular-nums``, ≥4-digit numbers without comma
   separators.

Why this split?  The design system §Voice & copy rules are easy to
*state* but hard to *machine-check* without context. The default tier
catches the violations PRs reliably introduce; the strict tier catches
patterns where a human still has to decide whether each hit is real or
a legitimate exception (date-fns format string used internally,
non-quantity number rendering, etc.). Promoting strict→default is
encouraged once a rule proves itself in real reviews; demoting back is
also fine and documented.

Manual-only rules
=================

Some §Voice & copy rules cannot be reliably scripted and must be audited
by hand during PR review (no script catches them at all):

- **Severity language matches the badge.** "HIGH" should pair with
  "Critical" or a specific consequence; "MEDIUM" with "Recommended" /
  "Warning"; "LOW" with "Optional" / "Consider". The script has no
  visibility into which JSX node renders a badge alongside which text.
- **Empty-state shape.** §Voice & copy says "State the fact, offer the
  action." A regex can't tell whether an EmptyState's subtitle proposes
  an action or just describes the void.
- **Error message structure.** "State what went wrong, what to do about
  it." Same problem — structural, not lexical.
- **Marketing chrome on dashboard pages.** "Welcome back" is scripted;
  hero-style "Your AI Trust Layer" copy in unexpected places is too
  open-ended to encode.
- **Decimal-place consistency.** `99.7%` next to `99.95%` next to
  `100%` is a stylistic inconsistency the linter can't reason about
  across components.

Bring these up in PR review. The CONTRIBUTING / CLAUDE.md voice section
points to the canonical full rule list (`dashboard-design-system.md`
§Voice & copy).

Suppression
===========

A ``copy-allow: <reason>`` marker that appears inside a comment
(``#``, ``//``, ``/* ... */`` or ``<!-- ... -->``) on the same line or
the immediately preceding line suppresses the violation. The reason is
required and surfaces in ``--report-json`` output for auditability. The
marker MUST be preceded by a real comment introducer — string literals
that contain the text ``copy-allow:`` do NOT suppress (see
``_intro_is_inside_string``).

Output: each violation as ``path:line:column: <rule>: <message>`` to
stderr. Exit 0 on clean input, 1 on any blocking violations. Stdlib-only
(Python 3.10+); no external deps.
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
#
# ``strict_only=True`` rules only fire when ``--strict`` is passed.
# ``warning=True`` rules surface to stderr (with a ``[warning]`` prefix)
# but do not flip the exit code.


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    message: str
    strict_only: bool = False
    warning: bool = False
    # Optional second pass: callback that takes the regex match and the
    # raw line and returns True iff the match is actually a violation.
    # Used to filter false positives (e.g. ``8MB`` size unit on
    # ``number-abbreviation-under-10k``) that are awkward to encode in
    # the regex itself.
    second_pass: "object | None" = None


def _rx(pattern: str, *, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


# ── Rule set ───────────────────────────────────────────────────────────────


RULES: tuple[Rule, ...] = (
    # ─── Default tier (CI-gated) ──────────────────────────────────────────
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
    Rule(
        id="number-abbreviation-quantity",
        # ``2.8K decisions``, ``5K records``, ``1M actions`` etc. —
        # an abbreviated number adjacent to an operational-quantity noun.
        # §Voice & copy: "'12,500 decisions' not '12.5K decisions' —
        # accuracy beats brevity. No abbreviation under 10K." We use a
        # narrow noun-adjacency rule (decisions/records/actions/customers/
        # users/events/agents/reviews/checks) because broad ``\d+[KMB]\b``
        # firing flagged legitimate statutory dollar figures
        # ("€35M" from the EU AI Act, "$5K/day" from CA SB 942) and
        # wizard volume-bucket boundary labels ("10K – 100K"). The
        # noun-adjacency form catches the actual violation pattern
        # (a Vera counter rendered abbreviated) without false-positiving
        # legal quotes or threshold labels.
        # Allows ``5K`` itself as part of an inline numeric range
        # ("up to 5K") via ``# copy-allow``. Storage units (``8MB``,
        # ``5GB``) and video-resolution (``4K``, ``8K``) usages don't
        # match because they don't precede a quantity noun.
        pattern=re.compile(
            r"\b\d+(?:\.\d+)?[KMB]\s+"
            r"(?:decisions?|records?|actions?|customers?|users?|events?|agents?|reviews?|checks?|requests?)\b",
            flags=re.IGNORECASE,
        ),
        message=(
            'banned: spell out abbreviated quantities adjacent to '
            'operational nouns ("12,500 decisions" not "12.5K decisions"). '
            '§Voice & copy: "accuracy beats brevity. No abbreviation under 10K."'
        ),
    ),
    # ─── Strict tier (--strict opt-in) ────────────────────────────────────
    #
    # These rules are heuristics with non-trivial false-positive rates.
    # They are NOT enabled by default and do NOT gate CI. Run with
    # ``--strict`` locally before opening a PR.
    Rule(
        id="date-no-year",
        # date-fns or Intl format strings that omit the year. Matches
        # ``format(x, "MMM d")`` / ``format(x, 'MMM dd')`` and the
        # corresponding ``toLocaleDateString`` shapes where ``year``
        # isn't requested. We flag the format-string literal itself;
        # for ``toLocaleDateString({...})`` we look for an options
        # object that names ``month`` but not ``year``.
        pattern=_rx(
            r"""(
                ["']                                 # opening quote
                (?:MMM|MMMM|MMMMM)\s+d{1,2}          # MMM d / MMMM dd
                (?!.*y)                              # no 'y' anywhere after
                ["']                                 # closing quote
                |
                # toLocaleDateString( ... ) call whose argument list
                # mentions "month" but never "year". Lookahead asserts
                # the entire call body (up to the next `)`) is
                # year-free; the main pattern then captures up to month
                # so the violation has a sensible matched_text.
                toLocaleDateString\(
                (?=[^)]*month)                       # must mention month
                (?![^)]*year)                        # but must NOT mention year
                [^)]*month
            )""",
            flags=re.IGNORECASE | re.VERBOSE,
        ),
        message=(
            'date format omits the year. §Voice & copy: full-date format '
            'with year ("Mar 15, 2026" not "Mar 15"). Add { year: "numeric" } '
            'or include "yyyy" in the format string.'
        ),
        strict_only=True,
    ),
    Rule(
        id="numbers-no-commas",
        # Bare 4+ digit runs that are NOT preceded by a comma and NOT
        # inside obvious code-ish contexts (versions like 1.2.3, hex
        # strings, years 1900-2099, port numbers, ms latencies). Default
        # warning level — script emits to stderr but does not fail CI
        # so noisy false positives don't block PRs. Promote to blocking
        # later if signal-to-noise improves.
        pattern=_rx(
            r"""(?<![,.\d])                       # not preceded by , . or another digit
                \b
                \d{4,}                            # 4+ digit run
                (?!\s*(?:px|ms|s\b|MB|GB|KB|TB|/|\.)) # not followed by unit-ish text
                \b""",
            flags=re.IGNORECASE | re.VERBOSE,
        ),
        message=(
            'number with 4+ digits should use comma separators ("12,500" '
            'not "12500"). §Voice & copy: comma separators on user-facing '
            'quantities. (warning — heuristic, suppress with # copy-allow '
            'if non-quantity context)'
        ),
        strict_only=True,
        warning=True,
    ),
    Rule(
        id="recommendation-language",
        # Bare imperative recommendations like "You should X", "We
        # recommend that you", "Make sure to" — flag at strict level
        # because the dashboard recommendation language must be
        # "Consider X" or "Recommended: X" only. Heuristic — false
        # positives expected in onboarding copy that legitimately
        # tells users what to do (these are imperatives directed at
        # the operator, not recommendations from a model). Suppress
        # with # copy-allow: <reason> where appropriate.
        pattern=_rx(
            r"""\b(
                you\s+should\s+(?!be\s)            # "you should X" but not "you should be"
                |
                we\s+recommend\s+that\s+you
                |
                make\s+sure\s+to\s+(?!be\s)
                |
                you\s+must\s+(?!be\s|have\s)
            )"""
,
            flags=re.IGNORECASE | re.VERBOSE,
        ),
        message=(
            'recommendation language: use "Consider X" or "Recommended: X" '
            'instead of bare imperatives. §Voice & copy: never "You should X".'
        ),
        strict_only=True,
    ),
    Rule(
        id="tabular-nums-missing",
        # Heuristic — flag JSX expressions that render an unmistakable
        # number (.toLocaleString() call) on a line that lacks a
        # tabular-nums anchor anywhere nearby. We can't reasonably do
        # multi-line lookbacks in a regex, so this only catches the
        # narrow case where the rendering and the className are on the
        # same line. False-positive prone — suppress with # copy-allow.
        pattern=_rx(
            r"\{[^{}]*\.toLocaleString\(\)[^{}]*\}"
        ),
        message=(
            'rendered number should be wrapped in a tabular-nums style. '
            '§Voice & copy: tabular-nums on every rendered number. (strict-mode '
            'heuristic — many true positives need surrounding-line review)'
        ),
        strict_only=True,
    ),
)


def rules_for_mode(*, strict: bool) -> tuple[Rule, ...]:
    """Return the rule subset that should fire in the requested mode."""

    if strict:
        return RULES
    return tuple(r for r in RULES if not r.strict_only)


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
    warning: bool = False

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


def scan_file(path: Path, *, rules: tuple[Rule, ...]) -> list[Violation]:
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

        for rule in rules:
            for m in rule.pattern.finditer(raw_line):
                # Second-pass filter (e.g. ``8MB`` storage-unit on
                # ``number-abbreviation-under-10k``). If it returns
                # False, skip the match entirely — it's not a real
                # violation, not just a suppressed one.
                if rule.second_pass is not None:
                    fn = rule.second_pass  # type: ignore[assignment]
                    if not fn(m, raw_line):  # type: ignore[misc]
                        continue
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
                        warning=rule.warning,
                    )
                )

    return violations


def scan_paths(
    roots: list[Path],
    *,
    paths_glob: str | None = None,
    strict: bool = False,
) -> list[Violation]:
    rules = rules_for_mode(strict=strict)
    out: list[Violation] = []
    for f in iter_target_files(roots, paths_glob=paths_glob):
        out.extend(scan_file(f, rules=rules))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_violation(v: Violation) -> str:
    prefix = "[warning] " if v.warning else ""
    return (
        f"{prefix}{v.path}:{v.line}:{v.column}: {v.rule_id} "
        f"({v.matched_text!r}): {v.message}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_copy_violations",
        description=(
            "Scan user-facing surfaces for banned vocabulary. "
            "Exit 0 if clean, 1 if any blocking violations found. "
            "Pass --strict to enable heuristic rules (date-no-year, "
            "numbers-no-commas, recommendation-language, tabular-nums-missing) "
            "for the PR-author local audit pass."
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
        "--strict",
        action="store_true",
        help=(
            "Enable the heuristic rule tier (date-no-year, numbers-no-commas, "
            "recommendation-language, tabular-nums-missing). Not gated in CI "
            "by default — meant for PR-author local audit. Warning-tagged "
            "rules still print but don't flip the exit code."
        ),
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

    violations = scan_paths(roots, paths_glob=args.paths_glob, strict=args.strict)
    # A violation is "blocking" when it is not allowlisted AND is not a
    # warning-level rule. Warnings still print to stderr (with a [warning]
    # prefix in _format_violation) so the operator sees them, but they
    # don't flip the exit code.
    blocking = [v for v in violations if not v.allowed and not v.warning]
    warnings_active = [v for v in violations if not v.allowed and v.warning]

    if args.report_json:
        report = {
            "summary": {
                "total": len(violations),
                "blocking": len(blocking),
                "warnings": len(warnings_active),
                "allowed": sum(1 for v in violations if v.allowed),
            },
            "violations": [v.to_dict() for v in violations],
        }
        print(json.dumps(report, indent=2))

    # Print warnings first so blocking violations are the last lines —
    # easier to spot in CI log output.
    for v in warnings_active:
        print(_format_violation(v), file=sys.stderr)
    for v in blocking:
        print(_format_violation(v), file=sys.stderr)

    if blocking:
        print(
            f"\n{len(blocking)} blocking copy violation(s) found "
            f"({len(warnings_active)} warning, "
            f"{sum(1 for v in violations if v.allowed)} suppressed by # copy-allow).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
