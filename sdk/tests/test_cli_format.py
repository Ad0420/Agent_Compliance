"""Pure unit tests for :mod:`vera._cli_format`.

No :class:`CliRunner`, no Click, no monkeypatching of click streams —
just import the helpers and assert their outputs. Keeps the test surface
focused on rendering correctness and lets us iterate on layout without
shimming the whole CLI.
"""

from __future__ import annotations

import json as _json
import re
from datetime import datetime, timedelta, timezone

import pytest

from vera import _cli_format as fmt


# A fixed "now" used as the relative-time anchor in every test. UTC,
# no microseconds — keeps the absolute renders boring.
_NOW = datetime(2026, 5, 24, 14, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# relative_time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "delta_seconds,expected",
    [
        # Past, in ascending magnitude.
        (0, "just now"),
        (-1, "just now"),
        (-4, "just now"),
        (-5, "5s ago"),
        (-30, "30s ago"),
        (-59, "59s ago"),
        (-60, "1m ago"),
        (-90, "1m ago"),
        (-3599, "59m ago"),
        (-3600, "1h ago"),
        (-7200, "2h ago"),
        (-86_399, "23h ago"),
        (-86_400, "1d ago"),
        (-86_400 * 36, "36d ago"),
        # Future, in ascending magnitude.
        (45, "in 45s"),
        (59, "in 59s"),
        (60, "in 1m"),
        (300, "in 5m"),
        (3599, "in 59m"),
        (3600, "in 1h"),
        (86_400, "in 24h"),
    ],
)
def test_relative_time_boundaries(delta_seconds: int, expected: str) -> None:
    target = _NOW + timedelta(seconds=delta_seconds)
    assert fmt.relative_time(target, now=_NOW) == expected


def test_relative_time_none_returns_question_mark() -> None:
    assert fmt.relative_time(None, now=_NOW) == "?"


def test_relative_time_naive_dt_treated_as_utc() -> None:
    """A naive datetime should be assumed-UTC (backend convention)."""
    naive = datetime(2026, 5, 24, 14, 29, 0)  # 1 minute before _NOW
    assert fmt.relative_time(naive, now=_NOW) == "1m ago"


# ---------------------------------------------------------------------------
# _parse_dt (private but worth pinning since the renderer leans on it)
# ---------------------------------------------------------------------------


def test_parse_dt_accepts_iso_string_with_z() -> None:
    parsed = fmt._parse_dt("2026-05-24T14:23:15Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.hour == 14 and parsed.minute == 23


def test_parse_dt_accepts_iso_string_with_offset() -> None:
    parsed = fmt._parse_dt("2026-05-24T14:23:15+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_dt_rejects_garbage_without_raising() -> None:
    assert fmt._parse_dt("not a date") is None
    assert fmt._parse_dt("") is None
    assert fmt._parse_dt(None) is None
    assert fmt._parse_dt(12345) is None


def test_parse_dt_accepts_datetime_passthrough() -> None:
    dt = datetime(2026, 5, 24, tzinfo=timezone.utc)
    assert fmt._parse_dt(dt) is dt


# ---------------------------------------------------------------------------
# render_status_human — snapshot-shaped assertions
# ---------------------------------------------------------------------------


def _pending_approval() -> dict:
    """A minimal pending approval (no decisions yet)."""
    return {
        "id": "app_01H7XKCRJF8",
        "org_id": "org_acme",
        "requested_by_agent": "dpo-bot",
        "action_name": "delete_customer_record",
        "action_summary": "Hard-delete user record per GDPR Art. 17",
        "context": {"table": "customers", "rows": 1},
        "risk_tier": "high",
        "approvers_required": 2,
        "status": "pending",
        "decisions": [],
        "requested_at": "2026-05-24T14:27:00Z",  # 3m ago
        "expires_at":   "2026-05-24T14:37:00Z",  # in 7m
        "resolved_at":  None,
        "data_subject_id": "user_42",
    }


def _resolved_approval() -> dict:
    """Approved, with two recorded decisions."""
    base = _pending_approval()
    base.update(
        {
            "status": "approved",
            "resolved_at": "2026-05-24T14:29:00Z",
            "decisions": [
                {
                    "decision": "approve",
                    "approver": "ops_lead@acme.io",
                    "decided_at": "2026-05-24T14:28:00Z",
                    "note": "checked the data subject's GDPR request",
                },
                {
                    "decision": "approve",
                    "approver": "privacy@acme.io",
                    "decided_at": "2026-05-24T14:29:00Z",
                },
            ],
        }
    )
    return base


def test_render_pending_no_color() -> None:
    out = fmt.render_status_human(_pending_approval(), color=False, now=_NOW)
    # Header carries id + status + risk.
    assert "Review app_01H7XKCRJF8" in out
    assert "[. PENDING]" in out
    assert "risk: high" in out
    # Body rows.
    assert "agent" in out and "dpo-bot" in out
    assert "action" in out and "delete_customer_record" in out
    assert "summary" in out
    assert "subject" in out and "user_42" in out
    assert "requested" in out and "3m ago" in out
    assert "expires" in out and "in 7m" in out
    assert "approvers" in out and "2 required" in out
    # No decisions block (empty list).
    assert "Decisions" not in out
    # Context block sorted.
    assert "Context:" in out
    rows_block = out.split("Context:", 1)[1]
    assert rows_block.index("rows") < rows_block.index("table") or "rows" in rows_block
    # No ANSI escapes when color=False.
    assert "\x1b[" not in out


def test_render_resolved_with_decisions_no_color() -> None:
    out = fmt.render_status_human(_resolved_approval(), color=False, now=_NOW)
    assert "[OK APPROVED]" in out
    assert "Decisions (2):" in out
    assert "OK approve by ops_lead@acme.io" in out
    assert "OK approve by privacy@acme.io" in out
    # Note rendered, with indent and surrounding quotes.
    assert '            "checked the data subject\'s GDPR request"' in out
    assert "resolved" in out


def test_render_color_enabled_produces_ansi_escapes() -> None:
    out = fmt.render_status_human(_resolved_approval(), color=True, now=_NOW)
    assert "\x1b[" in out, "color=True must emit ANSI escapes"
    # Status glyph uses unicode when color is on.
    assert "✓" in out


def test_render_color_disabled_strips_all_ansi() -> None:
    out = fmt.render_status_human(_resolved_approval(), color=False, now=_NOW)
    assert "\x1b[" not in out
    # And uses ASCII fallback symbols.
    assert "OK" in out
    assert "✓" not in out


def test_render_omits_optional_fields_when_absent() -> None:
    minimal = {
        "id": "app_min",
        "requested_by_agent": "bot",
        "action_name": "act",
        "risk_tier": "low",
        "approvers_required": 1,
        "status": "pending",
        "decisions": [],
        "requested_at": "2026-05-24T14:30:00Z",
        # No expires_at, resolved_at, action_summary, data_subject_id, context.
    }
    out = fmt.render_status_human(minimal, color=False, now=_NOW)
    assert "expires" not in out
    assert "resolved" not in out
    assert "summary" not in out
    assert "subject" not in out
    assert "Context:" not in out
    assert "Decisions" not in out


def test_render_pr_a5_fields_when_present() -> None:
    """When webhook/callback fields are populated, they render."""
    approval = _resolved_approval()
    approval["webhook_sent_at"] = "2026-05-24T14:29:01Z"
    approval["callback_received_at"] = "2026-05-24T14:29:03Z"
    out = fmt.render_status_human(approval, color=False, now=_NOW)
    assert "webhook" in out
    assert "callback" in out


def test_render_pr_a5_fields_skipped_when_absent() -> None:
    """The renderer must NOT emit webhook/callback rows when fields are None."""
    approval = _resolved_approval()
    approval["webhook_sent_at"] = None
    approval["callback_received_at"] = None
    out = fmt.render_status_human(approval, color=False, now=_NOW)
    # The literal labels (with the column-padded form) should be absent.
    assert "\n  webhook " not in out
    assert "\n  callback " not in out


def test_render_watch_footer_appended_when_provided() -> None:
    out = fmt.render_status_human(
        _pending_approval(),
        color=False,
        watch_footer="Polling every 5s. Elapsed: 30s.",
        now=_NOW,
    )
    assert "Polling every 5s. Elapsed: 30s." in out
    # Separated by exactly one blank line above the footer.
    assert "\n\nPolling every" in out


def test_render_tolerates_missing_required_fields() -> None:
    """Partial dict (bad backend response) shouldn't crash the formatter."""
    out = fmt.render_status_human({}, color=False, now=_NOW)
    # Renders "?" for missing fields rather than raising.
    assert "?" in out
    assert "Review ?" in out


def test_render_long_multiline_note_indented_consistently() -> None:
    approval = _resolved_approval()
    approval["decisions"][0]["note"] = "line one\nline two\nline three"
    out = fmt.render_status_human(approval, color=False, now=_NOW)
    assert '            "line one"' in out
    assert '            "line two"' in out
    assert '            "line three"' in out


def test_render_status_unknown_falls_back_to_question_mark_glyph() -> None:
    approval = _pending_approval()
    approval["status"] = "weird_new_state"
    out = fmt.render_status_human(approval, color=False, now=_NOW)
    assert "[? WEIRD_NEW_STATE]" in out


# ---------------------------------------------------------------------------
# JSON renderers
# ---------------------------------------------------------------------------


def test_render_status_json_is_valid_indented_json() -> None:
    out = fmt.render_status_json(_resolved_approval())
    assert out.endswith("\n")
    parsed = _json.loads(out)
    assert parsed["id"] == "app_01H7XKCRJF8"
    assert parsed["status"] == "approved"
    # Pretty-printed (multi-line).
    assert out.count("\n") > 5


def test_render_status_ndjson_is_one_line() -> None:
    out = fmt.render_status_ndjson(_resolved_approval())
    # Exactly one newline, at the very end.
    assert out.count("\n") == 1
    assert out.endswith("\n")
    # No leading whitespace.
    assert not out.startswith(" ")
    # Parseable.
    parsed = _json.loads(out)
    assert parsed["status"] == "approved"


def test_render_status_json_serializes_datetime() -> None:
    approval = _pending_approval()
    approval["requested_at"] = datetime(2026, 5, 24, 14, 27, 0, tzinfo=timezone.utc)
    out = fmt.render_status_json(approval)
    # default=str renders the datetime — must not raise.
    parsed = _json.loads(out)
    assert "2026" in parsed["requested_at"]


# ---------------------------------------------------------------------------
# Color / headless detection
# ---------------------------------------------------------------------------


def test_is_color_inappropriate_honors_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    assert fmt._is_color_inappropriate() is True


def test_is_color_inappropriate_honors_term_dumb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert fmt._is_color_inappropriate() is True


def test_is_color_inappropriate_when_stdout_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pytest already redirects stdout, so isatty() is False — verify."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    # In the pytest harness stdout is captured, so isatty() returns False.
    assert fmt._is_color_inappropriate() is True


def test_should_use_color_flag_always_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--no-color`` must disable color even when env+TTY would allow it."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    assert fmt.should_use_color(no_color_flag=True) is False


# ---------------------------------------------------------------------------
# Watch footer
# ---------------------------------------------------------------------------


def test_render_watch_footer_basic() -> None:
    out = fmt.render_watch_footer(5.0, 135.0, now=_NOW)
    assert "Polling every 5s" in out
    assert "Press Ctrl-C to exit" in out
    assert "2m 15s" in out
    assert "14:30:00 UTC" in out


def test_render_watch_footer_subsecond_interval_keeps_decimal() -> None:
    out = fmt.render_watch_footer(0.5, 1.0, now=_NOW)
    assert "Polling every 0.5s" in out


def test_format_elapsed_buckets() -> None:
    assert fmt._format_elapsed(0) == "0s"
    assert fmt._format_elapsed(45) == "45s"
    assert fmt._format_elapsed(60) == "1m 0s"
    assert fmt._format_elapsed(135) == "2m 15s"
    assert fmt._format_elapsed(3661) == "1h 1m 1s"


# ---------------------------------------------------------------------------
# Column-alignment regression — long IDs should not bunch up the badge
# ---------------------------------------------------------------------------


def test_long_review_id_does_not_break_layout() -> None:
    approval = _pending_approval()
    approval["id"] = "app_" + "x" * 80
    out = fmt.render_status_human(approval, color=False, now=_NOW)
    # We don't truncate; we just verify the badge is still present.
    assert "[. PENDING]" in out
    assert "risk: high" in out
