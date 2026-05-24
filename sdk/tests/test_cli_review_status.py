"""Tests for ``vera review-status`` (Wave 2B PR B3).

Uses Click's :class:`CliRunner` with a monkeypatched :class:`VeraClient`
so nothing hits the network. ``time.sleep`` is also patched in watch-
mode tests so the suite finishes in milliseconds.
"""

from __future__ import annotations

import json as _json

import pytest
from click.testing import CliRunner

from vera import cli as cli_mod
from vera.cli import cli
from vera.errors import (
    VeraAuthError,
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
    WrongKeyTier,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs with a valid-shaped API key so the pre-flight passes.

    Tests that specifically exercise the "no key" branch override this
    explicitly via ``monkeypatch.delenv("VERA_API_KEY")``.
    """
    monkeypatch.setenv("VERA_API_KEY", "al_live_" + "x" * 32)
    # Keep tests deterministic regardless of the host's NO_COLOR setting.
    monkeypatch.delenv("NO_COLOR", raising=False)


def _approval(**overrides) -> dict:
    """Build an ApprovalResponse-shaped dict for use in mock clients."""
    base = {
        "id": "app_01H7XKCRJF8",
        "org_id": "org_acme",
        "requested_by_agent": "dpo-bot",
        "data_subject_id": None,
        "action_name": "delete_record",
        "action_summary": None,
        "context": {},
        "risk_tier": "high",
        "approvers_required": 1,
        "status": "pending",
        "decisions": [],
        "requested_at": "2026-05-24T14:27:00Z",
        "expires_at": "2026-05-24T14:37:00Z",
        "resolved_at": None,
    }
    base.update(overrides)
    return base


def _make_client_class(approval_or_callable):
    """Build a VeraClient stub whose ``get_approval`` returns the given value.

    If ``approval_or_callable`` is callable, it's invoked with
    ``(approval_id)`` per call — useful for transition tests where the
    second poll should return a different state than the first.
    """
    call_log: list[str] = []

    class _Stub:
        def __init__(self, **kw):
            self.api_url = "https://test.example"

        def get_approval(self, approval_id: str) -> dict:
            call_log.append(approval_id)
            if callable(approval_or_callable):
                return approval_or_callable(approval_id, len(call_log))
            return approval_or_callable

        def close(self) -> None:
            pass

    _Stub.call_log = call_log  # type: ignore[attr-defined]
    return _Stub


# ---------------------------------------------------------------------------
# Help / routing
# ---------------------------------------------------------------------------


def test_help_shows_all_options() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "--help"])
    assert result.exit_code == 0
    for flag in ("--watch", "--interval", "--timeout", "--json", "--no-color"):
        assert flag in result.output, f"missing {flag} in --help"
    assert "REVIEW_ID" in result.output
    assert "Exit codes" in result.output


def test_missing_review_id_exits_2_with_usage() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status"])
    # Click's default for a missing required argument.
    assert result.exit_code == 2
    assert "REVIEW_ID" in result.output or "review_id" in result.output.lower()
    assert "Usage" in result.output


def test_review_status_visible_in_top_level_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "review-status" in result.output


def test_interval_below_floor_rejected_by_click() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "x", "--interval", "0.1"])
    assert result.exit_code == 2
    assert "0.5" in result.output


def test_interval_above_ceiling_rejected_by_click() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "x", "--interval", "999"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Pre-flight: no API key
# ---------------------------------------------------------------------------


def test_no_api_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without VERA_API_KEY set, we should exit 2 without touching the network."""
    monkeypatch.delenv("VERA_API_KEY", raising=False)

    # Sentinel: this client should NEVER be constructed.
    constructed = {"n": 0}

    class _Sentinel:
        def __init__(self, **kw):
            constructed["n"] += 1
            self.api_url = "x"

        def get_approval(self, _id):
            raise AssertionError("should not be called")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _Sentinel)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "VERA_API_KEY" in result.output
    # Confirm we never even tried to construct the client.
    assert constructed["n"] == 0


# ---------------------------------------------------------------------------
# Single-shot human output
# ---------------------------------------------------------------------------


def test_single_shot_pending_renders_status_and_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_01H7XKCRJF8"])
    assert result.exit_code == 0, result.output
    assert "Review app_01H7XKCRJF8" in result.output
    assert "PENDING" in result.output
    assert "high" in result.output
    assert "dpo-bot" in result.output
    assert "delete_record" in result.output


def test_single_shot_approved_shows_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _approval(
        status="approved",
        resolved_at="2026-05-24T14:29:00Z",
        decisions=[
            {
                "decision": "approve",
                "approver": "ops@acme.io",
                "decided_at": "2026-05-24T14:28:00Z",
                "note": "looks good",
            },
        ],
    )
    monkeypatch.setattr(cli_mod, "VeraClient", _make_client_class(approval))
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 0, result.output
    assert "APPROVED" in result.output
    assert "Decisions (1):" in result.output
    assert "ops@acme.io" in result.output
    assert '"looks good"' in result.output


def test_single_shot_empty_decisions_omits_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval(decisions=[]))
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 0
    assert "Decisions" not in result.output


def test_single_shot_context_block_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _approval(context={"table": "customers", "rows": 1})
    monkeypatch.setattr(cli_mod, "VeraClient", _make_client_class(approval))
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 0
    assert "Context:" in result.output
    assert "table" in result.output
    assert "customers" in result.output


def test_single_shot_no_color_outputs_no_ansi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CliRunner already gives us a non-TTY, but --no-color is belt+braces."""
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x", "--no-color"])
    assert result.exit_code == 0, result.output
    assert "\x1b[" not in result.output


def test_single_shot_piped_stdout_strips_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --no-color, headless detection should still suppress ANSI."""
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    # CliRunner's stdout is not a TTY, so _is_color_inappropriate() = True.
    assert "\x1b[" not in result.output


def test_single_shot_honors_no_color_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 0
    assert "\x1b[" not in result.output


# ---------------------------------------------------------------------------
# Single-shot JSON
# ---------------------------------------------------------------------------


def test_single_shot_json_is_parseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _approval(status="approved")
    monkeypatch.setattr(cli_mod, "VeraClient", _make_client_class(approval))
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x", "--json"])
    assert result.exit_code == 0, result.output
    parsed = _json.loads(result.output)
    assert parsed["status"] == "approved"
    assert parsed["id"] == approval["id"]


def test_single_shot_json_terminated_with_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x", "--json"])
    assert result.output.endswith("\n")


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace ``time.sleep`` in the cli module with a no-op that records calls."""
    calls: list[float] = []

    def _fast_sleep(s: float) -> None:
        calls.append(s)

    monkeypatch.setattr(cli_mod.time, "sleep", _fast_sleep)
    return calls


def test_watch_exits_on_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pending → approved transition should exit 0 after the second poll."""
    sleep_calls = _patch_sleep(monkeypatch)

    def _transition(_id: str, call_n: int) -> dict:
        if call_n == 1:
            return _approval(status="pending")
        return _approval(status="approved", resolved_at="2026-05-24T14:29:00Z")

    cls = _make_client_class(_transition)
    monkeypatch.setattr(cli_mod, "VeraClient", cls)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["review-status", "app_x", "--watch", "--interval", "1"],
    )
    assert result.exit_code == 0, result.output
    # Sleep called exactly once (between poll 1 and poll 2).
    assert sleep_calls == [1.0]
    # Both polls happened.
    assert len(cls.call_log) == 2  # type: ignore[attr-defined]


def test_watch_json_emits_ndjson_one_object_per_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sleep(monkeypatch)

    def _transition(_id: str, call_n: int) -> dict:
        if call_n == 1:
            return _approval(status="pending")
        return _approval(status="approved")

    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_transition)
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["review-status", "app_x", "--watch", "--json", "--interval", "1"],
    )
    assert result.exit_code == 0, result.output
    lines = [l for l in result.output.splitlines() if l.strip()]
    assert len(lines) == 2, f"expected 2 NDJSON lines, got {lines!r}"
    poll_1 = _json.loads(lines[0])
    poll_2 = _json.loads(lines[1])
    assert poll_1["status"] == "pending"
    assert poll_2["status"] == "approved"


def test_watch_timeout_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    """When timeout elapses before terminal state, exit 3."""
    _patch_sleep(monkeypatch)

    # Stub monotonic so elapsed grows past the timeout on the second
    # iteration without any real wall-clock time passing.
    clock = {"t": 0.0}

    def _fake_monotonic() -> float:
        return clock["t"]

    def _stepping_sleep(s: float) -> None:
        clock["t"] += s + 10.0  # ensure we cross the timeout immediately

    monkeypatch.setattr(cli_mod.time, "monotonic", _fake_monotonic)
    monkeypatch.setattr(cli_mod.time, "sleep", _stepping_sleep)

    monkeypatch.setattr(
        cli_mod,
        "VeraClient",
        _make_client_class(_approval(status="pending")),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "review-status",
            "app_x",
            "--watch",
            "--interval",
            "1",
            "--timeout",
            "5",
        ],
    )
    assert result.exit_code == 3, result.output
    assert "Watch timeout" in result.output
    assert "app_x" in result.output
    assert "last status: pending" in result.output


def test_watch_ctrl_c_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    """A KeyboardInterrupt during the sleep should exit 130 with a clean message."""

    def _interrupt_sleep(_s: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_mod.time, "sleep", _interrupt_sleep)
    monkeypatch.setattr(
        cli_mod,
        "VeraClient",
        _make_client_class(_approval(status="pending")),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["review-status", "app_x", "--watch", "--interval", "1"],
    )
    assert result.exit_code == 130, result.output
    assert "(interrupted)" in result.output


# ---------------------------------------------------------------------------
# Cross-flag warnings
# ---------------------------------------------------------------------------


def test_interval_without_watch_warns_but_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(
        cli, ["review-status", "app_x", "--interval", "10"]
    )
    assert result.exit_code == 0, result.output
    assert "--interval has no effect without --watch" in result.output


def test_timeout_without_watch_warns_but_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_mod, "VeraClient", _make_client_class(_approval())
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x", "--timeout", "30"])
    assert result.exit_code == 0, result.output
    assert "--timeout has no effect without --watch" in result.output


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_404_exits_1_with_not_found_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotFoundClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            err = VeraValidationError("approval not found", status_code=404)
            raise err

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _NotFoundClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_missing"])
    assert result.exit_code == 1, result.output
    assert "not found" in result.output.lower()
    assert "app_missing" in result.output


def test_401_exits_2_with_auth_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AuthFailClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise VeraAuthError("bad credentials")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _AuthFailClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "Authentication failed" in result.output


def test_403_read_perm_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ForbiddenClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise VeraAuthError("forbidden", status_code=403)

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _ForbiddenClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "read" in result.output.lower()


def test_wrong_key_tier_exits_2_with_tier_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WrongTierClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise WrongKeyTier(
                key_kind="test",
                required="live",
                endpoint="GET /v1/approvals/{id}",
            )

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _WrongTierClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "tier mismatch" in result.output
    assert "test" in result.output
    assert "live" in result.output


def test_rate_limit_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ThrottledClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise VeraRateLimitError("too many", request_id="req_abc")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _ThrottledClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "Rate limited" in result.output


def test_server_error_retries_once_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5xx should retry once, then exit 2 on the second failure."""
    calls = {"n": 0}

    class _FlakyClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            calls["n"] += 1
            raise VeraServerError("upstream down")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _FlakyClient)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert calls["n"] == 2, "expected 2 attempts (1 original + 1 retry)"
    assert "Vera service error" in result.output


def test_network_error_retries_once_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    class _NetClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            calls["n"] += 1
            raise VeraNetworkError("dns failed")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _NetClient)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert calls["n"] == 2
    assert "Retried once" in result.output


def test_timeout_error_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _SlowClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            calls["n"] += 1
            raise VeraTimeoutError("slow")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _SlowClient)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert calls["n"] == 2


def test_auth_error_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth errors must not waste a retry round-trip."""
    calls = {"n": 0}

    class _AuthFailClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            calls["n"] += 1
            raise VeraAuthError("bad")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _AuthFailClient)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert calls["n"] == 1, "auth errors must not retry"


def test_validation_error_non_404_exits_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 validation error (e.g. malformed ID) should exit 2, not 1."""

    class _BadReqClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise VeraValidationError("malformed id", status_code=400)

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _BadReqClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2


def test_unexpected_exception_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenClient:
        def __init__(self, **kw):
            self.api_url = "x"

        def get_approval(self, _id):
            raise RuntimeError("kaboom")

        def close(self):
            pass

    monkeypatch.setattr(cli_mod, "VeraClient", _BrokenClient)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-status", "app_x"])
    assert result.exit_code == 2
    assert "Unexpected" in result.output or "kaboom" in result.output
