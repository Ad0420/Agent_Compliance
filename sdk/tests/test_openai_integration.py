"""Unit tests for vera.integrations.openai.

Mocks the OpenAI client; no real ``openai`` dependency is required at test
time. Covers:

* Non-streaming success / failure / token-usage capture
* Streaming success / usage on final chunk / 1MB cap / mid-stream failure
* Streaming via context manager
* Redaction wiring for both paths, plus per-instance redactor override
* ``patch_openai`` / ``unpatch_openai`` idempotency
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vera import Redactor
from vera.integrations.openai import (
    AuditedOpenAI,
    _AuditedStreamIterator,
    _resolve_default_redactor,
    patch_openai,
    unpatch_openai,
)


# ---------------------------------------------------------------------------
# Helpers — fake OpenAI shapes
# ---------------------------------------------------------------------------


def _make_response(content: str, usage=None):
    """Build a fake non-streaming ``ChatCompletion``."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage_ns = (
        SimpleNamespace(
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[2],
        )
        if usage is not None
        else None
    )
    return SimpleNamespace(choices=[choice], usage=usage_ns)


def _chunk(content: str | None = None, usage=None):
    """Build a fake ``ChatCompletionChunk``."""
    delta = SimpleNamespace(content=content) if content is not None else SimpleNamespace(content=None)
    choice = SimpleNamespace(delta=delta)
    usage_ns = (
        SimpleNamespace(
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[2],
        )
        if usage is not None
        else None
    )
    return SimpleNamespace(choices=[choice], usage=usage_ns)


def _make_audited(redactor=None):
    """Return ``(audited_client, mock_underlying_client, mock_ledger)``."""
    underlying = MagicMock()
    # ``AuditedOpenAI`` reaches into ``openai_client.chat.completions``;
    # giving these MagicMock children produces real attribute objects we
    # can hand back to assertions.
    underlying.chat = MagicMock()
    underlying.chat.completions = MagicMock()
    ledger = MagicMock()
    audited = AuditedOpenAI(underlying, ledger, redactor=redactor)
    return audited, underlying, ledger


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


class TestNonStreaming:
    def test_success_records_one_audit_event(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = _make_response(
            "hello world", usage=(10, 5, 15)
        )

        out = audited.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert out.choices[0].message.content == "hello world"
        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["action_type"] == "llm_call"
        assert kw["result"] == "success"
        assert kw["target_system"] == "openai"
        assert kw["target_resource"] == "gpt-4o"
        assert kw["input_data"]["model"] == "gpt-4o"
        assert kw["input_data"]["message_count"] == 1
        assert kw["input_data"]["last_message"] == "hi"
        assert kw["outcome"]["response"] == "hello world"
        assert kw["outcome"]["token_usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        assert "duration_ms" in kw

    def test_failure_records_failure_event_and_reraises(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            audited.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
            )

        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["result"] == "failure"
        assert kw["error_message"] == "boom"
        assert kw["target_resource"] == "gpt-4o-mini"

    def test_token_usage_extraction_when_present(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = _make_response(
            "ok", usage=(7, 3, 10)
        )
        audited.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "x"}]
        )
        outcome = ledger.record_action.call_args.kwargs["outcome"]
        assert outcome["token_usage"]["prompt_tokens"] == 7
        assert outcome["token_usage"]["total_tokens"] == 10

    def test_redaction_in_non_streaming_input(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = _make_response("ok")

        audited.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": "Approve loan for SSN 123-45-6789"},
            ],
        )
        last_message = ledger.record_action.call_args.kwargs["input_data"][
            "last_message"
        ]
        assert "123-45-6789" not in last_message
        assert "[REDACTED:ssn]" in last_message

    def test_redaction_in_non_streaming_response(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = _make_response(
            "Reach me at alice@example.com"
        )

        audited.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
        )
        response = ledger.record_action.call_args.kwargs["outcome"]["response"]
        assert "alice@example.com" not in response
        assert "[REDACTED:email]" in response

    def test_custom_redactor_overrides_default(self):
        # A redactor that blocks the key "secret_field" — verifies the
        # passed-in instance, not the module default, is used.
        custom = Redactor(block_keys={"will_not_match"}, replacement="[X]")
        audited, underlying, ledger = _make_audited(redactor=custom)
        # Use a Luhn-valid card so default patterns *would* fire if the
        # custom redactor were ignored: the custom uses "[X]" replacement,
        # so we can tell which one ran.
        underlying.chat.completions.create.return_value = _make_response(
            "card 4111-1111-1111-1111"
        )
        audited.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "ok"}],
        )
        response = ledger.record_action.call_args.kwargs["outcome"]["response"]
        # Custom replacement applied, default not.
        assert "[X:credit_card]" in response
        assert "[REDACTED" not in response


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreaming:
    def test_streaming_success_records_one_event_on_close(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = iter(
            [_chunk("Hello "), _chunk("world"), _chunk("!")]
        )

        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        chunks = list(stream)
        assert len(chunks) == 3
        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["result"] == "success"
        assert kw["target_system"] == "openai"
        assert kw["outcome"]["response"] == "Hello world!"

    def test_streaming_with_usage_chunk_records_token_usage(self):
        audited, underlying, ledger = _make_audited()
        # OpenAI's newer streaming format puts usage on the final chunk
        # (which has empty delta).
        underlying.chat.completions.create.return_value = iter(
            [_chunk("Hi "), _chunk("there"), _chunk(content=None, usage=(4, 2, 6))]
        )
        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        list(stream)
        outcome = ledger.record_action.call_args.kwargs["outcome"]
        assert outcome["response"] == "Hi there"
        assert outcome["token_usage"] == {
            "prompt_tokens": 4,
            "completion_tokens": 2,
            "total_tokens": 6,
        }

    def test_streaming_over_1mb_cap(self, caplog):
        audited, underlying, ledger = _make_audited()
        # 1.5MB of content, well over the 1MB cap. We use a redactor with
        # patterns disabled to avoid stress-testing regex backtracking on
        # very long synthetic strings — that's a property of the
        # Redactor, not of the streaming logic under test here.
        no_pattern_redactor = Redactor(patterns=[], max_length=10_000_000)
        underlying2 = MagicMock()
        underlying2.chat = MagicMock()
        underlying2.chat.completions = MagicMock()
        ledger2 = MagicMock()
        audited2 = AuditedOpenAI(
            underlying2, ledger2, redactor=no_pattern_redactor
        )

        big_chunk_text = "a" * 300_000
        underlying2.chat.completions.create.return_value = iter(
            [_chunk(big_chunk_text) for _ in range(5)]
        )
        with caplog.at_level(logging.WARNING, logger="vera.integrations.openai"):
            stream = audited2.chat.completions.create(
                stream=True,
                model="gpt-4o",
                messages=[{"role": "user", "content": "x"}],
            )
            list(stream)

        outcome = ledger2.record_action.call_args.kwargs["outcome"]
        recorded = outcome["response"]
        assert recorded.endswith("...[stream truncated by vera at 1MB]")
        # First 1MB is all 'a's; suffix appended after the cap.
        assert recorded[:1_048_576] == "a" * 1_048_576
        assert len(recorded) == 1_048_576 + len(
            "...[stream truncated by vera at 1MB]"
        )
        assert any("exceeded 1MB cap" in r.message for r in caplog.records)

    def test_streaming_iteration_error_records_failure(self):
        audited, underlying, ledger = _make_audited()

        def gen():
            yield _chunk("part1 ")
            yield _chunk("part2 ")
            raise ValueError("network blew up")

        underlying.chat.completions.create.return_value = gen()

        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        with pytest.raises(ValueError, match="network blew up"):
            list(stream)

        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["result"] == "failure"
        assert kw["error_message"] == "network blew up"
        assert kw["outcome"]["partial_response"] == "part1 part2 "

    def test_streaming_via_context_manager_fires_on_exit(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = iter(
            [_chunk("ctx "), _chunk("mgr")]
        )

        with audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        ) as stream:
            chunks = list(stream)
        assert len(chunks) == 2
        ledger.record_action.assert_called_once()
        # __exit__ runs after StopIteration already triggered the success
        # path; the second close call must be a no-op (still one event).
        assert (
            ledger.record_action.call_args.kwargs["outcome"]["response"]
            == "ctx mgr"
        )

    def test_streaming_context_manager_records_failure_on_caller_raise(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = iter(
            [_chunk("partial ")]
        )

        with pytest.raises(RuntimeError, match="caller error"):
            with audited.chat.completions.create(
                stream=True,
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            ) as stream:
                next(iter(stream))
                raise RuntimeError("caller error")

        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["result"] == "failure"
        assert kw["error_message"] == "caller error"
        # Partial buffer captured before the raise.
        assert kw["outcome"]["partial_response"] == "partial "

    def test_streaming_redacts_response_content(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = iter(
            [_chunk("Reach me at "), _chunk("alice@example.com"), _chunk(" thanks")]
        )

        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        list(stream)
        response = ledger.record_action.call_args.kwargs["outcome"]["response"]
        assert "alice@example.com" not in response
        assert "[REDACTED:email]" in response

    def test_streaming_input_data_shape(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.return_value = iter(
            [_chunk("ok")]
        )
        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "hello"},
            ],
        )
        list(stream)
        input_data = ledger.record_action.call_args.kwargs["input_data"]
        assert input_data["model"] == "gpt-4o"
        assert input_data["message_count"] == 2
        assert input_data["last_message"] == "hello"

    def test_streaming_chunks_pass_through_unchanged(self):
        audited, underlying, ledger = _make_audited()
        sentinel_a = _chunk("A")
        sentinel_b = _chunk("B")
        underlying.chat.completions.create.return_value = iter([sentinel_a, sentinel_b])

        stream = audited.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        out = list(stream)
        # Identity preserved: caller sees the exact chunk objects we got
        # from the underlying client. No reshaping or copying.
        assert out[0] is sentinel_a
        assert out[1] is sentinel_b

    def test_streaming_init_failure_records_event(self):
        audited, underlying, ledger = _make_audited()
        underlying.chat.completions.create.side_effect = RuntimeError(
            "auth failed"
        )

        with pytest.raises(RuntimeError, match="auth failed"):
            audited.chat.completions.create(
                stream=True,
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            )
        ledger.record_action.assert_called_once()
        kw = ledger.record_action.call_args.kwargs
        assert kw["result"] == "failure"
        assert kw["error_message"] == "auth failed"


# ---------------------------------------------------------------------------
# Direct iterator tests — close idempotency, malformed chunks
# ---------------------------------------------------------------------------


class TestIteratorEdgeCases:
    def test_close_is_idempotent(self):
        ledger = MagicMock()
        redactor = Redactor()
        it = _AuditedStreamIterator(
            stream=iter([_chunk("x")]),
            ledger=ledger,
            redactor=redactor,
            input_data={"model": "gpt-4o"},
            model="gpt-4o",
            started_at=0.0,
        )
        list(it)
        # Calling __exit__ after natural exhaustion must not double-record.
        it.__exit__(None, None, None)
        assert ledger.record_action.call_count == 1

    def test_malformed_chunk_does_not_raise(self):
        # A chunk with no ``choices`` attribute (or one that raises) must
        # be tolerated — we drop the content but keep the audit alive.
        ledger = MagicMock()
        redactor = Redactor()
        bad = SimpleNamespace()  # no choices, no usage
        it = _AuditedStreamIterator(
            stream=iter([bad, _chunk("good")]),
            ledger=ledger,
            redactor=redactor,
            input_data={"model": "gpt-4o"},
            model="gpt-4o",
            started_at=0.0,
        )
        list(it)
        ledger.record_action.assert_called_once()
        assert (
            ledger.record_action.call_args.kwargs["outcome"]["response"]
            == "good"
        )


# ---------------------------------------------------------------------------
# Default-redactor resolution
# ---------------------------------------------------------------------------


class TestDefaultRedactor:
    def test_resolve_default_returns_redactor(self):
        r = _resolve_default_redactor()
        assert isinstance(r, Redactor)


# ---------------------------------------------------------------------------
# patch_openai / unpatch_openai
# ---------------------------------------------------------------------------


class TestPatchUnpatch:
    def test_patch_unpatch_idempotent(self):
        # We don't have ``openai`` installed in CI by default — skip if so.
        openai_module = pytest.importorskip("openai")

        ledger = MagicMock()
        original_init = openai_module.OpenAI.__init__
        try:
            patch_openai(ledger)
            assert openai_module.OpenAI.__init__ is not original_init
            # Second call is a no-op — does not raise, does not re-wrap.
            patched_init = openai_module.OpenAI.__init__
            patch_openai(ledger)
            assert openai_module.OpenAI.__init__ is patched_init
        finally:
            unpatch_openai()
        assert openai_module.OpenAI.__init__ is original_init

    def test_unpatch_without_patch_is_safe(self):
        # Should not raise even if ``openai`` is missing or never patched.
        unpatch_openai()
        unpatch_openai()
