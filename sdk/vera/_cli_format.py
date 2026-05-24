"""Pure rendering helpers for the ``vera review-status`` CLI command.

Split out of :mod:`vera.cli` so the formatters can be tested without
spinning up a Click ``CliRunner``. Every function here is deterministic
and side-effect-free apart from :func:`_is_color_inappropriate`, which
reads the process environment.

The shape we render is the JSON body returned by
``GET /v1/approvals/{id}`` (see ``backend/app/schemas/approval.py``
``ApprovalResponse``). Optional fields (``webhook_sent_at`` /
``callback_received_at`` from Wave 2B PR A5; ``decided_at`` from later
PRs) render only when populated, so this module is forward-compatible
with downstream backend additions without needing a coordinated bump.
"""

from __future__ import annotations

import json as _json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import click


# ---------------------------------------------------------------------------
# Status / risk style tables
# ---------------------------------------------------------------------------

#: Approval lifecycle states the backend can return. ``cancelled`` is
#: reserved for future backend support; we include it here so the CLI
#: doesn't crash if the backend later emits it.
TERMINAL_STATES: frozenset[str] = frozenset(
    {"approved", "rejected", "expired", "cancelled"}
)

#: Unicode glyph per status — paired 1:1 with ``ASCII_FALLBACK``. We
#: pre-pad each glyph with a width-1 character; the printable width in
#: a terminal is 1 cell each (the box-drawing characters used here have
#: standardized East-Asian Width = "Narrow"), so column alignment in the
#: rendered header stays stable.
STATUS_GLYPHS: dict[str, str] = {
    "pending":   "…",
    "approved":  "✓",
    "rejected":  "✗",
    "expired":   "⊘",
    "cancelled": "⊝",
    "unknown":   "?",
}

#: ASCII fallback used when stdout is not a TTY, ``NO_COLOR`` is set, or
#: ``TERM=dumb``. Length-2 strings so the badge column stays readable.
ASCII_FALLBACK: dict[str, str] = {
    "pending":   ".",
    "approved":  "OK",
    "rejected":  "X",
    "expired":   "EXP",
    "cancelled": "CAN",
    "unknown":   "?",
}

#: Click foreground color name per status. ``None`` means "leave the
#: glyph uncolored". Risk-tier colors are separate (see ``TIER_COLORS``)
#: because the badge in the header is colored by *status* but the
#: ``risk:`` value to the right is colored by *risk tier*.
STATUS_COLORS: dict[str, str | None] = {
    "pending":   "cyan",
    "approved":  "green",
    "rejected":  "red",
    "expired":   "yellow",
    "cancelled": "bright_black",
    "unknown":   None,
}

#: Click foreground color per risk tier. ``critical`` gets bold-bright
#: to read visually distinct from plain red ``high`` — matches the
#: dashboard convention of escalating saturation as risk climbs.
TIER_COLORS: dict[str, dict[str, Any]] = {
    "low":      {"fg": "green"},
    "medium":   {"fg": "yellow"},
    "high":     {"fg": "red"},
    "critical": {"fg": "bright_red", "bold": True},
}


# ---------------------------------------------------------------------------
# Headless / color detection
# ---------------------------------------------------------------------------


def _is_color_inappropriate() -> bool:
    """Return True when ANSI output should be suppressed.

    Three signals, any of which disables color:

    * ``NO_COLOR`` environment variable set to anything non-empty
      (https://no-color.org — the de-facto standard).
    * ``TERM=dumb`` (emacs shell-mode, some CI shells).
    * Stdout is not a TTY (the typical "piped to a file or to ``jq``"
      case — color codes would pollute the downstream consumer).

    Named ``_is_color_inappropriate`` to avoid collision with
    :func:`vera.cli._is_headless`, which has a different responsibility
    (DISPLAY-style browser-launch detection for ``vera init`` /
    ``vera quickstart``). Both are "headless"-shaped, but they detect
    different conditions and have different return values for the same
    environment.
    """
    if os.environ.get("NO_COLOR", "").strip():
        return True
    if os.environ.get("TERM", "").strip() == "dumb":
        return True
    try:
        return not sys.stdout.isatty()
    except (AttributeError, ValueError):
        # Redirected stdout occasionally lacks ``isatty`` (closed file,
        # custom IO wrapper). Treat as headless rather than crashing.
        return True


def should_use_color(no_color_flag: bool) -> bool:
    """Resolve the effective color setting for this invocation.

    Color is enabled only when *both* the ``--no-color`` flag is unset
    AND :func:`_is_color_inappropriate` returns False. This keeps the
    flag's behavior monotonic: ``--no-color`` always wins.
    """
    if no_color_flag:
        return False
    return not _is_color_inappropriate()


def _style(text: str, *, fg: str | None = None, bold: bool = False, enabled: bool) -> str:
    """One-line wrapper around :func:`click.style` honoring the disable knob.

    Returns plain text when ``enabled`` is False so the same formatter
    code path handles colored TTY and headless output without ``if``
    sprinkled at every call site.
    """
    if not enabled or (fg is None and not bold):
        return text
    return click.style(text, fg=fg, bold=bold)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """Best-effort parse of a datetime field from an ApprovalResponse.

    Accepts ``datetime``, ISO-8601 strings (with optional trailing
    ``Z``), and returns ``None`` for empty / unparseable values. We
    intentionally don't raise on bad input — partial responses from a
    misbehaving backend shouldn't crash the formatter. Bad fields just
    render as "?" in the human view (caller's responsibility).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Pydantic-serialized datetimes may be timezone-naive. Treat
        # naive values as UTC since that's the backend's convention.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    # ``datetime.fromisoformat`` in 3.11+ accepts trailing Z; play it
    # safe by normalizing first so 3.10 also works.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def relative_time(dt: datetime | None, *, now: datetime | None = None) -> str:
    """Return a short relative-time description for ``dt``.

    Always renders deterministically given ``(dt, now)``. The ``now``
    parameter exists so tests don't need to monkeypatch :mod:`datetime`.
    Buckets:

    ============  ===========
    Delta         Output
    ============  ===========
    < 5s past     ``just now``
    < 60s past    ``{n}s ago``
    < 60m past    ``{n}m ago``
    < 24h past    ``{n}h ago``
    >= 24h past   ``{n}d ago``
    < 60s future  ``in {n}s``
    < 60m future  ``in {n}m``
    >= 60m future ``in {n}h``
    ============  ===========

    The 60m+ future bucket is a deliberate approximation — approval
    expirations are capped at 86_400s (24h) by the backend validator
    (``ApprovalCreate.expires_in_seconds: le=86_400``), so "in 23h" is
    the longest future delta we'll ever render in practice.
    """
    if dt is None:
        return "?"
    if now is None:
        now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta_s = (dt - now).total_seconds()

    if delta_s <= 0:
        ago = -delta_s
        if ago < 5:
            return "just now"
        if ago < 60:
            return f"{int(ago)}s ago"
        if ago < 3600:
            return f"{int(ago // 60)}m ago"
        if ago < 86_400:
            return f"{int(ago // 3600)}h ago"
        return f"{int(ago // 86_400)}d ago"
    else:
        ahead = delta_s
        if ahead < 60:
            return f"in {int(ahead)}s"
        if ahead < 3600:
            return f"in {int(ahead // 60)}m"
        return f"in {int(ahead // 3600)}h"


def _time_pair(value: Any, *, now: datetime | None = None) -> str:
    """Render an absolute UTC timestamp plus a relative phrase.

    Example: ``2026-05-24 14:23:15 UTC  (3m ago)``.

    Always renders UTC + relative — never local time. Documented in
    the ``vera review-status --help`` text; avoids the confusing case
    where two engineers in different time zones see different absolutes
    for the same approval.
    """
    dt = _parse_dt(value)
    if dt is None:
        return "?"
    absolute = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{absolute}  ({relative_time(dt, now=now)})"


# ---------------------------------------------------------------------------
# Human renderer
# ---------------------------------------------------------------------------


def _row(label: str, value: str) -> str:
    """Render one body row: ``  label          value``."""
    return f"  {label.ljust(14)}  {value}"


def _glyph_for_status(status: str, *, color: bool) -> str:
    """Return the printable glyph for a status, falling back to ASCII."""
    if color:
        return STATUS_GLYPHS.get(status, STATUS_GLYPHS["unknown"])
    return ASCII_FALLBACK.get(status, ASCII_FALLBACK["unknown"])


def render_status_human(
    approval: dict,
    *,
    color: bool,
    watch_footer: str | None = None,
    now: datetime | None = None,
) -> str:
    """Render an ApprovalResponse dict as a multi-line human summary.

    ``color`` toggles ANSI escapes; pass False (or call via
    :func:`should_use_color`) when stdout isn't a TTY. ``watch_footer``,
    if provided, is appended after a blank line — used by ``--watch``
    to show poll cadence + elapsed time below the body.

    Layout (see plan §3.1 for visual mock):

    * Header line: ``Review {id}    [{glyph} {STATUS}]    risk: {tier}``
    * Body: agent / action / requested / expires / resolved / approvers
      and (when populated) webhook + callback rows from PR A5.
    * Decisions block: one line per vote, with optional indented note.
    * Context block: optional, only when ``approval['context']`` is non-empty.
    * Watch footer: optional, controlled by ``watch_footer``.

    Unknown fields are tolerated; missing required fields render as ``?``
    rather than crashing. We never raise — formatters should degrade
    gracefully on partial data.
    """
    status = str(approval.get("status", "unknown"))
    risk = str(approval.get("risk_tier", "unknown"))
    glyph = _glyph_for_status(status, color=color)

    # ── HEADER ────────────────────────────────────────────────────────
    review_id = str(approval.get("id", "?"))
    header_left = f"Review {review_id}"
    badge_inner = f"{glyph} {status.upper()}"
    status_color = STATUS_COLORS.get(status)
    if status_color is not None:
        badge_inner = _style(badge_inner, fg=status_color, enabled=color)
    # Brackets stay uncolored so the visual grouping reads even when the
    # inner text is dimmed (e.g. ``bright_black`` for cancelled).
    badge = f"[{badge_inner}]"

    tier_style = TIER_COLORS.get(risk, {})
    risk_label = _style(
        risk,
        fg=tier_style.get("fg"),
        bold=tier_style.get("bold", False),
        enabled=color,
    )

    # Left-pad so the columns line up across approvals of different ID
    # length. ``ljust`` on the uncolored prefix keeps width math honest
    # (ANSI escapes have zero printable width).
    lines = [
        f"{header_left.ljust(46)}  {badge}     risk: {risk_label}",
        "",
    ]

    # ── BODY ──────────────────────────────────────────────────────────
    body_candidates: list[str | None] = [
        _row("agent", str(approval.get("requested_by_agent", "?"))),
        _row("action", str(approval.get("action_name", "?"))),
        _row("summary", str(approval["action_summary"]))
            if approval.get("action_summary")
            else None,
        _row("subject", str(approval["data_subject_id"]))
            if approval.get("data_subject_id")
            else None,
        _row("requested", _time_pair(approval.get("requested_at"), now=now)),
        _row("expires", _time_pair(approval["expires_at"], now=now))
            if approval.get("expires_at")
            else None,
        _row("resolved", _time_pair(approval["resolved_at"], now=now))
            if approval.get("resolved_at")
            else None,
        # PR A5 forward-compat: render only when populated. The
        # ``ApprovalResponse`` schema already declares these as
        # ``Optional[datetime]``; until upstream PRs (A3/A4/C2)
        # populate them, ``.get()`` returns ``None`` and we skip.
        _row("webhook", _time_pair(approval["webhook_sent_at"], now=now))
            if approval.get("webhook_sent_at")
            else None,
        _row("callback", _time_pair(approval["callback_received_at"], now=now))
            if approval.get("callback_received_at")
            else None,
        _row("approvers", f"{approval.get('approvers_required', 1)} required"),
    ]
    lines.extend(line for line in body_candidates if line is not None)

    # ── DECISIONS ─────────────────────────────────────────────────────
    decisions = approval.get("decisions") or []
    if decisions:
        lines += ["", f"Decisions ({len(decisions)}):"]
        for d in decisions:
            decision = str(d.get("decision", "?"))
            approver = str(d.get("approver", "?"))
            decided_at = d.get("decided_at")
            note = d.get("note")
            if color:
                sym = "✓" if decision == "approve" else "✗"
            else:
                sym = "OK" if decision == "approve" else "NO"
            sym_color = "green" if decision == "approve" else "red"
            sym_styled = _style(sym, fg=sym_color, enabled=color)
            lines.append(
                f"  {sym_styled} {decision:<7} by {approver:<24} "
                f"{_time_pair(decided_at, now=now)}"
            )
            if note:
                # Indent each line of a multi-line note uniformly so a
                # paragraph note doesn't break the column.
                for note_line in str(note).splitlines():
                    lines.append(f"            \"{note_line}\"")

    # ── CONTEXT (optional) ────────────────────────────────────────────
    ctx = approval.get("context") or {}
    if isinstance(ctx, dict) and ctx:
        lines += ["", "Context:"]
        # Sort keys for deterministic output — vital for snapshot tests
        # and for diff-friendly NDJSON-vs-human cross-checks.
        for k in sorted(ctx.keys()):
            v = ctx[k]
            lines.append(f"  {str(k):<10}  {v}")

    # ── WATCH FOOTER ──────────────────────────────────────────────────
    if watch_footer:
        lines += ["", watch_footer]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# JSON renderers
# ---------------------------------------------------------------------------


def render_status_json(approval: dict) -> str:
    """Single-shot JSON output (pretty-printed, two-space indent).

    Uses ``default=str`` so :class:`datetime` values (which pydantic may
    have already serialized to ISO strings — but which the SDK round-trips
    as-is) format cleanly without an explicit encoder.
    """
    return _json.dumps(approval, indent=2, default=str, sort_keys=True) + "\n"


def render_status_ndjson(approval: dict) -> str:
    """NDJSON: one compact JSON object, terminated by ``\\n``.

    Used by ``--watch --json`` to emit one line per poll. No leading
    whitespace, no trailing whitespace before the newline — strict
    NDJSON discipline so downstream ``jq -c`` / ``stdbuf -oL`` pipelines
    work without surprises.
    """
    return _json.dumps(approval, default=str, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Watch footer
# ---------------------------------------------------------------------------


def _format_elapsed(elapsed_s: float) -> str:
    """Render ``elapsed_s`` as ``1h 23m 4s`` / ``45s`` etc."""
    s = max(0, int(elapsed_s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m {s % 60}s"


def render_watch_footer(
    interval: float,
    elapsed_s: float,
    *,
    now: datetime | None = None,
) -> str:
    """Footer line shown below the body in ``--watch`` mode.

    Format: ``Polling every 5s. Press Ctrl-C to exit. Elapsed: 2m 15s. Last poll: 14:28:30 UTC.``
    """
    if now is None:
        now = datetime.now(timezone.utc)
    poll_clock = now.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
    # Trim trailing zero on integer intervals so "5s" beats "5.0s".
    if float(interval).is_integer():
        interval_str = f"{int(interval)}s"
    else:
        interval_str = f"{interval}s"
    return (
        f"Polling every {interval_str}. Press Ctrl-C to exit. "
        f"Elapsed: {_format_elapsed(elapsed_s)}. Last poll: {poll_clock}."
    )


# ---------------------------------------------------------------------------
# Terminal clear sequence
# ---------------------------------------------------------------------------


#: ANSI: clear screen + clear scrollback + cursor home. Works on Windows
#: Terminal, modern conhost (post-2019 ANSI VT update), and every
#: mainstream Unix terminal. Sent only when color is enabled — in
#: headless mode we print stacked frames separated by a divider instead.
TERMINAL_CLEAR = "\033[2J\033[3J\033[H"

#: Frame divider used in headless ``--watch`` mode in place of a screen
#: clear. Stacked frames produce a readable log when piped to ``tee``.
HEADLESS_FRAME_DIVIDER = "----- new poll -----\n"
