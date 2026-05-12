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
    # record_action stub returns a synthetic ack.
    assert result["status"] == "dev"
    assert result["record_id"] == "dev-1"


def test_dev_client_enqueue_action_writes_to_sink():
    client = build_dev_client(echo=False)
    client.enqueue_action(action_name="op1", input_data={"a": 1})
    client.enqueue_action(action_name="op2", input_data={"b": 2})

    names = [r["action_name"] for r in client.sink.records]
    assert names == ["op1", "op2"]


def test_dev_client_stderr_echo_enabled_by_default(capsys):
    client = build_dev_client()  # echo defaults to True
    client.enqueue_action(action_name="echoed", input_data={"k": "v"})

    captured = capsys.readouterr()
    assert "[vera-dev]" in captured.err
    # Parse the JSON portion to verify shape.
    line = captured.err.strip().splitlines()[-1]
    payload = json.loads(line.removeprefix("[vera-dev] "))
    assert payload["action_name"] == "echoed"


def test_dev_client_echo_disabled(capsys):
    client = build_dev_client(echo=False)
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
    client.enqueue_action(
        action_name="datetime-op",
        input_data={"ts": datetime.datetime(2026, 1, 1, 12, 0, 0)},
    )
    captured = capsys.readouterr()
    assert "[vera-dev]" in captured.err
