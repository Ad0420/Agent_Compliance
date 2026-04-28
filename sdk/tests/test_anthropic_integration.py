"""Unit tests for the Anthropic integration (streaming + redaction).

These tests fake the Anthropic SDK shapes via ``MagicMock`` and
``types.SimpleNamespace`` so they don't require the real ``anthropic``
package at test time.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from vera.integrations.anthropic import (
    AuditedAnthropic,
    _AuditedMessageStream,
    _StreamRecorder,
)
from vera.redaction import Redactor


# ---------------------------------------------------------------------------
# Helpers — build fake Anthropic SDK shapes
# ---------------------------------------------------------------------------


def _make_text_block(text: str):
    return types.SimpleNamespace(type="text", text=text)


def _make_message(text: str, *, stop_reason="end_turn", input_tokens=10, output_tokens=20):
    return types.SimpleNamespace(
        content=[_make_text_block(text)],
        stop_reason=stop_reason,
        usage=types.SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


def _content_block_delta(text: str):
    return types.SimpleNamespace(
        type="content_block_delta",
        delta=types.SimpleNamespace(text=text),
    )


def _message_start(input_tokens=10, output_tokens=0):
    return types.SimpleNamespace(
        type="message_start",
        message=types.SimpleNamespace(
            usage=types.SimpleNamespace(
                input_tokens=input_tokens, output_tokens=output_tokens
            )
        ),
    )


def _message_delta(stop_reason="end_turn", input_tokens=10, output_tokens=42):
    return types.SimpleNamespace(
        type="message_delta",
        delta=types.SimpleNamespace(stop_reason=stop_reason),
        usage=types.SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


def _message_stop():
    return types.SimpleNamespace(type="message_stop")


class _FakeAnthropicClient:
    """Stand-in for ``anthropic.Anthropic()``. ``messages`` is a MagicMock."""

    def __init__(self):
        self.messages = MagicMock()


class _FakeMessageStream:
    """Stand-in for the high-level ``MessageStream`` context manager.

    Mirrors the surface our wrapper relies on:
        - context manager (__enter__/__exit__)
        - ``text_stream`` iterable
        - ``get_final_message()``
    """

    def __init__(self, tokens, final_message, raise_on_exit: bool = False):
        self._tokens = list(tokens)
        self._final = final_message
        self._raise_on_exit = raise_on_exit
        self.entered = False
        self.exited_args = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited_args = (exc_type, exc, tb)
        if self._raise_on_exit:
            raise RuntimeError("forced exit failure")
        return False

    @property
    def text_stream(self):
        for tok in self._tokens:
            yield tok

    def get_final_message(self):
        return self._final

    def __iter__(self):
        # Raw event iteration (not used in most tests — included for parity).
        for tok in self._tokens:
            yield _content_block_delta(tok)


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


class TestNonStreamingCreate:
    def test_records_successful_call(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.return_value = _make_message("Hello there.")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert response.content[0].text == "Hello there."
        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "success"
        assert kwargs["target_system"] == "anthropic"
        assert kwargs["target_resource"] == "claude-sonnet-4-6"
        assert kwargs["action_type"] == "llm_call"
        assert kwargs["outcome"]["response"] == "Hello there."
        assert kwargs["outcome"]["stop_reason"] == "end_turn"
        assert kwargs["outcome"]["token_usage"]["input_tokens"] == 10
        assert kwargs["outcome"]["token_usage"]["output_tokens"] == 20
        assert kwargs["outcome"]["token_usage"]["total_tokens"] == 30

    def test_records_failure_and_reraises(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.side_effect = RuntimeError("boom")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        with pytest.raises(RuntimeError, match="boom"):
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=128,
                messages=[{"role": "user", "content": "Hi"}],
            )

        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "failure"
        assert kwargs["error_message"] == "boom"

    def test_redaction_applied_to_response(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        # Response embeds an SSN — should be redacted before audit.
        anthropic_client.messages.create.return_value = _make_message(
            "Customer SSN is 123-45-6789, please verify."
        )

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Look up the customer"}],
        )

        kwargs = ledger.record_action.call_args[1]
        assert "[REDACTED:ssn]" in kwargs["outcome"]["response"]
        assert "123-45-6789" not in kwargs["outcome"]["response"]

    def test_redaction_applied_to_last_message(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.return_value = _make_message("ok")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[
                {"role": "user", "content": "My SSN is 111-22-3333"},
            ],
        )

        kwargs = ledger.record_action.call_args[1]
        assert "[REDACTED:ssn]" in kwargs["input_data"]["last_message"]
        assert "111-22-3333" not in kwargs["input_data"]["last_message"]

    def test_last_message_with_content_blocks(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.return_value = _make_message("ok")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "First chunk."},
                        {"type": "text", "text": "Second chunk with email a@b.co"},
                    ],
                }
            ],
        )

        kwargs = ledger.record_action.call_args[1]
        last = kwargs["input_data"]["last_message"]
        assert "First chunk." in last
        # Email replaced
        assert "[REDACTED:email]" in last
        assert "a@b.co" not in last

    def test_custom_redactor_overrides_default(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.return_value = _make_message(
            "secret payload here"
        )
        # Redactor with a custom serializer that always returns a marker
        custom = Redactor(custom_serializer=lambda v: "<<scrubbed>>")

        client = AuditedAnthropic(
            anthropic_client, ledger_client=ledger, redactor=custom
        )
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
        )

        kwargs = ledger.record_action.call_args[1]
        # Custom serializer takes precedence over the default redactor.
        assert kwargs["outcome"]["response"] == "<<scrubbed>>"

    def test_back_compat_constructor_signature(self):
        """``AuditedAnthropic(client, ledger_client=...)`` without redactor still works."""
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.return_value = _make_message("ok")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
        )
        ledger.record_action.assert_called_once()


# ---------------------------------------------------------------------------
# Streaming via messages.create(stream=True) — iterator-style
# ---------------------------------------------------------------------------


class TestStreamingViaCreate:
    def test_stream_records_on_completion(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        events = [
            _message_start(input_tokens=12),
            _content_block_delta("Hello "),
            _content_block_delta("world"),
            _content_block_delta("!"),
            _message_delta(stop_reason="end_turn", input_tokens=12, output_tokens=3),
            _message_stop(),
        ]
        anthropic_client.messages.create.return_value = iter(events)

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        stream = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
        )

        out = list(stream)
        # The wrapper passed the raw events through.
        assert len(out) == len(events)

        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "success"
        assert kwargs["outcome"]["response"] == "Hello world!"
        assert kwargs["outcome"]["stop_reason"] == "end_turn"
        assert kwargs["outcome"]["token_usage"]["output_tokens"] == 3
        assert kwargs["outcome"]["token_usage"]["total_tokens"] == 15

    def test_stream_iteration_error_records_failure(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()

        def _gen():
            yield _content_block_delta("hi ")
            yield _content_block_delta("there")
            raise RuntimeError("upstream blew up")

        anthropic_client.messages.create.return_value = _gen()

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        stream = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
        )

        with pytest.raises(RuntimeError, match="upstream blew up"):
            list(stream)

        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "failure"
        assert kwargs["error_message"] == "upstream blew up"
        # Partial response captured
        assert kwargs["outcome"]["partial_response"] == "hi there"

    def test_stream_init_failure_records(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        anthropic_client.messages.create.side_effect = RuntimeError("init failed")

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        with pytest.raises(RuntimeError, match="init failed"):
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=128,
                messages=[{"role": "user", "content": "Hi"}],
                stream=True,
            )

        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "failure"

    def test_streaming_redaction_email(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        events = [
            _content_block_delta("Reach me at "),
            _content_block_delta("alice@example.com"),
            _content_block_delta(" anytime."),
            _message_delta(stop_reason="end_turn", output_tokens=5),
            _message_stop(),
        ]
        anthropic_client.messages.create.return_value = iter(events)

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        list(
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=128,
                messages=[{"role": "user", "content": "Hi"}],
                stream=True,
            )
        )

        kwargs = ledger.record_action.call_args[1]
        assert "[REDACTED:email]" in kwargs["outcome"]["response"]
        assert "alice@example.com" not in kwargs["outcome"]["response"]

    def test_streaming_truncates_at_1mb(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        # Build events totalling > 1MB
        chunk = "a" * 100_000  # 100KB per delta
        events = [_content_block_delta(chunk) for _ in range(12)]  # 1.2MB total
        events.append(_message_delta(stop_reason="end_turn", output_tokens=1))
        events.append(_message_stop())
        anthropic_client.messages.create.return_value = iter(events)

        # Use an empty-pattern redactor so we exercise the *streaming* cap
        # (1MB), not the redactor's own ``max_length``. With no patterns,
        # ``serialize`` is effectively pass-through, but still truncates at
        # ``max_length``; we set both well above 1MB so the stream cap fires.
        big_redactor = Redactor(patterns=[], max_length=10_000_000)
        client = AuditedAnthropic(
            anthropic_client, ledger_client=ledger, redactor=big_redactor
        )
        list(
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=128,
                messages=[{"role": "user", "content": "Hi"}],
                stream=True,
            )
        )

        kwargs = ledger.record_action.call_args[1]
        resp = kwargs["outcome"]["response"]
        # The buffer cap is 1MB, plus the truncation suffix.
        assert resp.endswith("...[stream truncated by vera at 1MB]")
        # First 1MB of "a"s, then suffix.
        assert len(resp) == 1_048_576 + len("...[stream truncated by vera at 1MB]")


# ---------------------------------------------------------------------------
# Streaming via messages.stream(...) — high-level CM
# ---------------------------------------------------------------------------


class TestStreamingViaStream:
    def test_stream_cm_records_on_clean_exit(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        final = _make_message(
            "ignored", stop_reason="end_turn", input_tokens=4, output_tokens=6
        )
        fake_stream = _FakeMessageStream(["Hello ", "world", "!"], final)
        anthropic_client.messages.stream.return_value = fake_stream

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        collected = []
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
        ) as stream:
            for token in stream.text_stream:
                collected.append(token)

        assert collected == ["Hello ", "world", "!"]
        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "success"
        assert kwargs["outcome"]["response"] == "Hello world!"
        assert kwargs["outcome"]["stop_reason"] == "end_turn"
        assert kwargs["outcome"]["token_usage"]["total_tokens"] == 10

    def test_stream_cm_records_failure_on_user_exception(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        final = _make_message("ignored")
        fake_stream = _FakeMessageStream(["a", "b", "c"], final)
        anthropic_client.messages.stream.return_value = fake_stream

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        with pytest.raises(ValueError, match="user code blew up"):
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=128,
                messages=[{"role": "user", "content": "Hi"}],
            ) as stream:
                for token in stream.text_stream:
                    if token == "b":
                        raise ValueError("user code blew up")

        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "failure"
        assert kwargs["error_message"] == "user code blew up"
        assert kwargs["outcome"]["partial_response"] == "ab"

    def test_stream_cm_get_final_message_directly(self):
        """Calling get_final_message() on the proxy still yields the final message
        and records the audit on context exit (idempotent)."""
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        final = _make_message(
            "ignored", stop_reason="max_tokens", input_tokens=2, output_tokens=4
        )
        fake_stream = _FakeMessageStream(["xyz"], final)
        anthropic_client.messages.stream.return_value = fake_stream

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
        ) as stream:
            got = list(stream.text_stream)
            assert got == ["xyz"]
            # User calls get_final_message() themselves; should still work.
            f = stream.get_final_message()
            assert f is final

        # Single audit record, idempotent recorder.
        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["outcome"]["stop_reason"] == "max_tokens"

    def test_stream_cm_redacts_response(self):
        ledger = MagicMock()
        anthropic_client = _FakeAnthropicClient()
        final = _make_message("ignored")
        fake_stream = _FakeMessageStream(
            ["My email is ", "bob@corp.io", " ok?"], final
        )
        anthropic_client.messages.stream.return_value = fake_stream

        client = AuditedAnthropic(anthropic_client, ledger_client=ledger)
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{"role": "user", "content": "Hi"}],
        ) as stream:
            list(stream.text_stream)

        kwargs = ledger.record_action.call_args[1]
        assert "[REDACTED:email]" in kwargs["outcome"]["response"]
        assert "bob@corp.io" not in kwargs["outcome"]["response"]


# ---------------------------------------------------------------------------
# _StreamRecorder unit tests (idempotency, cap edge case)
# ---------------------------------------------------------------------------


class TestStreamRecorderDirect:
    def test_record_success_is_idempotent(self):
        ledger = MagicMock()
        rec = _StreamRecorder(
            ledger=ledger,
            redactor=Redactor(),
            input_data={"model": "x"},
            model="x",
            started_at=0.0,
        )
        rec.feed_text("hi")
        rec.record_success()
        rec.record_success()
        ledger.record_action.assert_called_once()

    def test_record_failure_after_success_is_noop(self):
        ledger = MagicMock()
        rec = _StreamRecorder(
            ledger=ledger,
            redactor=Redactor(),
            input_data={"model": "x"},
            model="x",
            started_at=0.0,
        )
        rec.record_success()
        rec.record_failure(RuntimeError("late"))
        ledger.record_action.assert_called_once()
        kwargs = ledger.record_action.call_args[1]
        assert kwargs["result"] == "success"

    def test_feed_text_respects_cap_exactly(self):
        ledger = MagicMock()
        rec = _StreamRecorder(
            ledger=ledger,
            redactor=Redactor(patterns=[], max_length=10_000_000),
            input_data={"model": "x"},
            model="x",
            started_at=0.0,
        )
        # Fill the buffer to the cap exactly.
        rec.feed_text("x" * _StreamRecorder.BUFFER_CAP)
        # Subsequent feed should be discarded with the truncation flag.
        rec.feed_text("more text after cap")
        rec.record_success()

        kwargs = ledger.record_action.call_args[1]
        resp = kwargs["outcome"]["response"]
        # Cap hit on the 2nd feed → truncation suffix appended.
        assert resp.endswith("...[stream truncated by vera at 1MB]")
        # Buffer body is exactly the cap-many "x"s.
        body = resp[: -len("...[stream truncated by vera at 1MB]")]
        assert len(body) == _StreamRecorder.BUFFER_CAP
        assert set(body) == {"x"}
