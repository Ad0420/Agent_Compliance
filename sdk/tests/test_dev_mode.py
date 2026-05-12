"""Tests for dev mode (DX-B): stderr sink, DevClient, and the
:meth:`vera.client.VeraClient.dev` classmethod factory.
"""

from __future__ import annotations

import json

import pytest

from vera import VeraClient
from vera.dev import DevClient, _StderrSink, build_dev_client
from vera.redaction import Redactor


def test_dev_client_record_action_writes_to_sink():
    client = build_dev_client(echo=False)
    result = client.record_action(
        action_name="op",
        input_data={"x": 1},
        outcome={"y": 2},
    )

    assert len(client.sink.records) == 1
    record = client.sink.records[0]
    assert record["action_name"] == "op"
    assert record["input_data"] == {"x": 1}
    assert record["outcome"] == {"y": 2}
    # record_action stub returns a synthetic ack matching the production
    # return shape (so customer code using ``sequence_number`` /
    # ``recorded_at`` doesn't KeyError only in dev). ``mode`` is the one
    # dev-only marker.
    assert result["status"] == "success"
    assert result["mode"] == "dev"
    assert result["record_id"] == "dev-1"
    assert result["sequence_number"] == 1
    assert "recorded_at" in result


def test_dev_client_enqueue_action_writes_to_sink():
    client = build_dev_client(echo=False)
    client.enqueue_action(action_name="op1", input_data={"a": 1})
    client.enqueue_action(action_name="op2", input_data={"b": 2})

    names = [r["action_name"] for r in client.sink.records]
    assert names == ["op1", "op2"]


def test_dev_client_stderr_echo_enabled_by_default(capsys):
    client = build_dev_client()  # echo defaults to True
    capsys.readouterr()  # drop the one-time construction banner

    client.enqueue_action(action_name="echoed", input_data={"k": "v"})

    captured = capsys.readouterr()
    assert "[vera-dev]" in captured.err
    # Parse the JSON portion to verify shape.
    line = captured.err.strip().splitlines()[-1]
    payload = json.loads(line.removeprefix("[vera-dev] "))
    assert payload["action_name"] == "echoed"


def test_dev_client_echo_disabled(capsys):
    # Construct, then drain the one-time startup banner (CRITICAL #7) so
    # we only assert on per-record echo behaviour below.
    client = build_dev_client(echo=False)
    capsys.readouterr()  # drop the construction banner

    client.enqueue_action(action_name="silent", input_data={"k": "v"})

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    # But the record is still captured for assertions.
    assert client.sink.records[0]["action_name"] == "silent"


def test_dev_client_redactor_applied_before_sink():
    redactor = Redactor()  # default patterns redact SSN/CC/etc.
    client = build_dev_client(echo=False, redactor=redactor)
    client.enqueue_action(
        action_name="phi",
        input_data={"note": "patient SSN is 123-45-6789"},
    )

    record = client.sink.records[0]
    # input_data is serialized through Redactor.serialize → returns a JSON
    # string with the SSN scrubbed. We assert the raw digits aren't present.
    assert "123-45-6789" not in json.dumps(record, default=str)


def test_dev_client_classmethod_factory():
    client = VeraClient.dev(agent_name="cls-method")
    assert isinstance(client, DevClient)
    assert client.agent_name == "cls-method"


def test_dev_client_close_is_noop():
    client = build_dev_client(echo=False)
    # Should not raise even though there's no background worker / http client.
    client.close()
    # And we can still use it afterward.
    client.enqueue_action(action_name="post-close")
    assert client.sink.records[-1]["action_name"] == "post-close"


def test_dev_client_inherits_build_payload_identity():
    """DevClient must stamp the same identity fields as VeraClient."""
    client = build_dev_client(
        echo=False,
        agent_name="alpha",
        agent_version="v9",
        model_id="m",
        framework="openai",
    )
    client.enqueue_action(action_name="op")
    record = client.sink.records[0]
    assert record["agent_name"] == "alpha"
    assert record["agent_version"] == "v9"
    assert record["model_id"] == "m"
    assert record["framework"] == "openai"


def test_stderr_sink_reset_clears_records():
    sink = _StderrSink(echo=False)
    sink.record({"k": "v"})
    sink.record({"k": "v2"})
    assert len(sink.records) == 2
    sink.reset()
    assert sink.records == []


def test_dev_client_non_json_serializable_payload_does_not_raise(capsys):
    """Echo path must not crash on objects without a default JSON encoder."""
    import datetime

    client = build_dev_client(echo=True)
    capsys.readouterr()  # drop construction banner

    client.enqueue_action(
        action_name="datetime-op",
        input_data={"ts": datetime.datetime(2026, 1, 1, 12, 0, 0)},
    )
    captured = capsys.readouterr()
    assert "[vera-dev]" in captured.err


# ---------------------------------------------------------------------------
# CRITICAL fixes on PR #170 — safety rails around dev mode.
# ---------------------------------------------------------------------------


def test_dev_client_ignores_VERA_SPOOL_PATH(monkeypatch, tmp_path):
    """Dev mode MUST force-disable the durable spool even when env says otherwise.

    HIPAA leak path: if a prior production process wrote PHI to a spool at
    ``VERA_SPOOL_PATH``, and a dev re-runs the same command with
    ``VERA_DEV=1``, the rehydrated records would print to stderr through
    the DevClient sink. The fix: DevClient passes a ``_NO_SPOOL_SENTINEL``
    that bypasses the env-var fallback in ``VeraClient.__init__``.
    """
    spool_path = tmp_path / "should-not-be-created.db"
    monkeypatch.setenv("VERA_SPOOL_PATH", str(spool_path))
    monkeypatch.setenv("VERA_SPOOL_KEY", "test-passphrase-32chars-or-more!")

    client = build_dev_client(echo=False)

    # No spool instance attached to the client.
    assert client._spool is None
    # And no .db file was created on disk — the parent constructor did
    # NOT consult VERA_SPOOL_PATH because of the sentinel.
    assert not spool_path.exists()


def test_dev_client_return_shape_matches_production():
    """DevClient.record_action returns the same keys as production.

    Customer code that pulls ``sequence_number`` or ``recorded_at`` from
    the return dict must work identically in dev and prod. The only extra
    key in dev mode is ``mode="dev"``.
    """
    client = build_dev_client(echo=False)
    result = client.record_action(action_name="op")
    # Production keys.
    for key in ("status", "record_id", "sequence_number", "recorded_at"):
        assert key in result, f"missing production key: {key}"
    # status must be the production value, not a dev-specific marker.
    assert result["status"] == "success"
    # Dev-only marker.
    assert result["mode"] == "dev"


def test_dev_with_production_api_key_refuses(monkeypatch):
    """DEV mode must refuse a production-looking API key (``al_live_*``).

    Otherwise a customer who flips ``VERA_DEV=1`` in a prod env silently
    disables real audit logging — the worst failure mode for a compliance
    product.
    """
    from vera import VeraError

    monkeypatch.delenv("VERA_DEV_CONFIRM", raising=False)
    with pytest.raises(VeraError) as excinfo:
        build_dev_client(echo=False, api_key="al_live_prodlooking")
    assert "production-looking" in str(excinfo.value)
    assert "VERA_DEV_CONFIRM" in str(excinfo.value)


def test_dev_with_production_api_key_allowed_with_confirm(monkeypatch):
    """Setting ``VERA_DEV_CONFIRM=1`` bypasses the prod-key guard."""
    monkeypatch.setenv("VERA_DEV_CONFIRM", "1")
    client = build_dev_client(echo=False, api_key="al_live_prodlooking")
    assert isinstance(client, DevClient)


def test_dev_with_test_api_key_does_not_trip_prod_guard():
    """Non-``al_live_`` keys (e.g. ``al_test_``, ``dev_``) must not trip the guard."""
    # Default dev key is "dev" — no prefix match, no error.
    client = build_dev_client(echo=False)
    assert isinstance(client, DevClient)

    # Test-key prefix is fine.
    client2 = build_dev_client(echo=False, api_key="al_test_something")
    assert isinstance(client2, DevClient)


def test_dev_mode_emits_loud_startup_banner(caplog, capsys):
    """DEV mode must emit a WARN log line AND a stderr banner on construction.

    Customers who accidentally ship ``VERA_DEV=1`` to prod need to see the
    signal in their logs immediately. INFO-level isn't enough — most prod
    log configs filter INFO out.
    """
    with caplog.at_level("WARNING", logger="vera.dev"):
        build_dev_client(echo=False)

    # WARN log line with the documented code.
    assert any(
        "vera-dev-001" in r.message and "DEV MODE ACTIVE" in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]

    # Stderr banner.
    captured = capsys.readouterr()
    assert "[Vera DEV mode]" in captured.err
