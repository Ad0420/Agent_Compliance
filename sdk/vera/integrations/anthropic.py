"""Anthropic integration — wraps Messages API to audit all Claude calls.

Usage:
    import anthropic
    from vera.integrations.anthropic import AuditedAnthropic

    client = AuditedAnthropic(anthropic.Anthropic(), ledger_client=ledger)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}],
    )

Streaming is fully audited via either entry point:

    # 1. Iterator-style streaming via messages.create(stream=True)
    for event in client.messages.create(model=..., messages=[...], stream=True):
        ...

    # 2. High-level context-manager streaming via messages.stream(...)
    with client.messages.stream(model=..., messages=[...]) as stream:
        for token in stream.text_stream:
            print(token, end="")

In both cases content is buffered in memory (capped at 1MB to bound
memory) and emitted as a single audit record on stream close. Captured
text is run through the configured :class:`~vera.redaction.Redactor`
before it lands in the audit DB.
"""

from __future__ import annotations

import logging
import time

from ..redaction import Redactor

logger = logging.getLogger("vera.integrations.anthropic")


def _resolve_default_redactor() -> Redactor:
    """Return the SDK-wide default :class:`Redactor`.

    Imported lazily so this module doesn't pull ``vera.decorator`` at
    import time (avoids circulars and keeps the integration cheap to
    import in environments that never call the decorator).
    """
    from ..decorator import get_default_redactor
    return get_default_redactor()


# ---------------------------------------------------------------------------
# Stream recorder
# ---------------------------------------------------------------------------


class _StreamRecorder:
    """Accumulates streamed Anthropic content + usage; emits one audit record on close.

    Memory is bounded by ``BUFFER_CAP`` (1MB chars). Once the cap is
    hit, further text is discarded and the recorded ``response`` is
    suffixed with ``...[stream truncated by vera at 1MB]``.

    The recorder is idempotent — :meth:`record_success` /
    :meth:`record_failure` are safe to call multiple times. Only the
    first call emits an audit record.
    """

    BUFFER_CAP = 1_048_576  # 1MB

    def __init__(self, ledger, redactor: Redactor, input_data, model, started_at):
        self._ledger = ledger
        self._redactor = redactor
        self._input_data = input_data
        self._model = model
        self._started_at = started_at
        self._buffer: list[str] = []
        self._buffer_size = 0
        self._truncated = False
        self._usage = None
        self._stop_reason = None
        self._closed = False

    # ------------------------------------------------------------------
    # Feed methods
    # ------------------------------------------------------------------

    def feed_text(self, text: str) -> None:
        if not text or self._truncated:
            return
        new_size = self._buffer_size + len(text)
        if new_size > self.BUFFER_CAP:
            remaining = self.BUFFER_CAP - self._buffer_size
            if remaining > 0:
                self._buffer.append(text[:remaining])
                self._buffer_size = self.BUFFER_CAP
            self._truncated = True
            logger.warning(
                "Vera: Anthropic stream content exceeded 1MB cap; "
                "audit will record the first 1MB only"
            )
        else:
            self._buffer.append(text)
            self._buffer_size = new_size

    def feed_event(self, event) -> None:
        """Capture state from a raw event yielded by ``messages.create(stream=True)``."""
        try:
            etype = getattr(event, "type", None)
            if etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                text = getattr(delta, "text", None) if delta else None
                if text:
                    self.feed_text(text)
            elif etype == "message_delta":
                usage = getattr(event, "usage", None)
                if usage is not None:
                    self._usage = {
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                    }
                delta = getattr(event, "delta", None)
                stop = getattr(delta, "stop_reason", None) if delta else None
                if stop:
                    self._stop_reason = stop
            elif etype == "message_start":
                msg = getattr(event, "message", None)
                if msg is not None:
                    usage = getattr(msg, "usage", None)
                    if usage is not None and self._usage is None:
                        self._usage = {
                            "input_tokens": getattr(usage, "input_tokens", None),
                            "output_tokens": getattr(usage, "output_tokens", None),
                        }
            elif etype == "message_stop":
                pass  # close handler will fire
        except Exception:
            logger.warning(
                "Vera: failed to capture Anthropic stream event", exc_info=True
            )

    def feed_final_message(self, final_message) -> None:
        """Pull usage + stop_reason off a final ``Message`` (high-level .stream() path)."""
        try:
            usage = getattr(final_message, "usage", None)
            if usage is not None:
                self._usage = {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                }
            stop = getattr(final_message, "stop_reason", None)
            if stop:
                self._stop_reason = stop
        except Exception:
            logger.warning("Vera: failed to capture final message", exc_info=True)

    # ------------------------------------------------------------------
    # Close (emit one audit record)
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        if self._closed:
            return
        self._closed = True
        full = "".join(self._buffer)
        if self._truncated:
            full += "...[stream truncated by vera at 1MB]"
        elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        outcome = {"response": self._redactor.serialize(full)}
        if self._stop_reason:
            outcome["stop_reason"] = self._stop_reason
        if self._usage is not None:
            total = (self._usage.get("input_tokens") or 0) + (
                self._usage.get("output_tokens") or 0
            )
            outcome["token_usage"] = {**self._usage, "total_tokens": total}
        try:
            self._ledger.record_action(
                action_name="messages_create",
                action_type="llm_call",
                result="success",
                target_system="anthropic",
                target_resource=self._model,
                duration_ms=elapsed_ms,
                input_data=self._input_data,
                outcome=outcome,
            )
        except Exception:
            logger.warning(
                "Failed to record audit event for streamed Anthropic call",
                exc_info=True,
            )

    def record_failure(self, exc: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        try:
            self._ledger.record_action(
                action_name="messages_create",
                action_type="llm_call",
                result="failure",
                target_system="anthropic",
                target_resource=self._model,
                duration_ms=elapsed_ms,
                input_data=self._input_data,
                error_message=str(exc),
                outcome={
                    "partial_response": self._redactor.serialize("".join(self._buffer))
                },
            )
        except Exception:
            logger.warning(
                "Failed to record audit event for streamed Anthropic failure",
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Stream wrappers
# ---------------------------------------------------------------------------


class _AuditedRawStream:
    """Wraps the iterator returned by ``messages.create(stream=True)``.

    Forwards every event to the caller while feeding the recorder. On
    StopIteration the recorder emits a success audit; on any other
    exception it emits a failure audit and re-raises.
    """

    def __init__(self, original_iter, recorder: _StreamRecorder):
        self._iter = original_iter
        self._recorder = recorder

    def __iter__(self):
        return self

    def __next__(self):
        try:
            event = next(self._iter)
        except StopIteration:
            self._recorder.record_success()
            raise
        except BaseException as exc:
            self._recorder.record_failure(exc)
            raise
        self._recorder.feed_event(event)
        return event

    def __enter__(self):
        # Some users wrap the iterator in ``with`` even on the raw path;
        # fall through to the underlying object's CM if it has one.
        enter = getattr(self._iter, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        # If the user breaks out of iteration, emit on context exit.
        if exc is not None:
            self._recorder.record_failure(exc)
        else:
            self._recorder.record_success()
        original_exit = getattr(self._iter, "__exit__", None)
        if original_exit is not None:
            return original_exit(exc_type, exc, tb)
        return False

    def close(self):
        close = getattr(self._iter, "close", None)
        if close is not None:
            close()
        self._recorder.record_success()

    def __getattr__(self, name):
        return getattr(self._iter, name)


class _AuditedMessageStream:
    """Wraps Anthropic's high-level ``MessageStream`` context manager.

    Forwards the original API surface (``text_stream``, ``__iter__``,
    ``get_final_message``, etc.) and feeds the recorder.
    """

    def __init__(self, original_stream, recorder: _StreamRecorder):
        self._stream = original_stream
        self._recorder = recorder

    # The ``MessageStream`` returned by anthropic's SDK is itself a
    # context manager — we mirror that.
    def __enter__(self):
        # The original .stream(...) call returns a context-manager
        # object; if it's not yet entered, do so.
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            entered = enter()
            # Some SDK versions return ``self`` from __enter__, others
            # may return a different object — keep the one we got.
            self._stream = entered
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc is None:
                # Pull final message details (usage, stop_reason) before
                # closing the underlying stream.
                try:
                    final = self._stream.get_final_message()
                except Exception:
                    logger.warning(
                        "Vera: get_final_message() failed during stream exit",
                        exc_info=True,
                    )
                    final = None
                if final is not None:
                    self._recorder.feed_final_message(final)
                self._recorder.record_success()
            else:
                self._recorder.record_failure(exc)
        finally:
            original_exit = getattr(self._stream, "__exit__", None)
            if original_exit is not None:
                return original_exit(exc_type, exc, tb)
        return False

    # Token-by-token text stream — wrap with a generator that feeds the
    # recorder as the user iterates.
    @property
    def text_stream(self):
        original = self._stream.text_stream

        def _gen():
            for chunk in original:
                self._recorder.feed_text(chunk)
                yield chunk

        return _gen()

    def __iter__(self):
        # Iterating the stream yields raw events; feed via feed_event.
        for event in self._stream:
            self._recorder.feed_event(event)
            yield event

    def get_final_message(self):
        final = self._stream.get_final_message()
        # Feed in case the user calls this directly without exiting yet;
        # the recorder is idempotent on close.
        self._recorder.feed_final_message(final)
        return final

    def get_final_text(self):
        # Best-effort passthrough for SDK helpers that surface concatenated text.
        getter = getattr(self._stream, "get_final_text", None)
        if getter is None:
            raise AttributeError("get_final_text")
        return getter()

    def until_done(self):
        getter = getattr(self._stream, "until_done", None)
        if getter is None:
            raise AttributeError("until_done")
        return getter()

    def close(self):
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()
        self._recorder.record_success()

    def __getattr__(self, name):
        # Catch-all passthrough for any other MessageStream methods we
        # haven't explicitly handled (e.g. ``on``, ``current_message_snapshot``).
        return getattr(self._stream, name)


# ---------------------------------------------------------------------------
# Audited messages object
# ---------------------------------------------------------------------------


class _AuditedMessages:
    """Wraps anthropic.messages to record each create() / stream() call."""

    def __init__(
        self,
        original_messages,
        ledger_client,
        redactor: Redactor | None = None,
    ):
        self._original = original_messages
        self._ledger = ledger_client
        self._redactor = redactor if redactor is not None else _resolve_default_redactor()

    # ------------------------------------------------------------------
    # Input-data helper (shared between create + stream paths)
    # ------------------------------------------------------------------

    def _build_input_data(self, kwargs: dict) -> dict:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        input_data = {
            "model": model,
            "message_count": len(messages),
            "max_tokens": kwargs.get("max_tokens"),
        }
        if messages:
            last_msg = messages[-1]
            content = (
                last_msg.get("content", "")
                if isinstance(last_msg, dict)
                else str(last_msg)
            )
            if isinstance(content, list):
                # content blocks format — extract text blocks
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = " ".join(text_parts)
            input_data["last_message"] = self._redactor.serialize(str(content))

        if kwargs.get("system"):
            input_data["system_prompt_length"] = len(str(kwargs["system"]))
        return input_data

    # ------------------------------------------------------------------
    # create() — supports stream=True via the iterator wrapper
    # ------------------------------------------------------------------

    def create(self, **kwargs):
        input_data = self._build_input_data(kwargs)
        model = kwargs.get("model", "unknown")

        if kwargs.get("stream"):
            start = time.perf_counter()
            try:
                raw = self._original.create(**kwargs)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                try:
                    self._ledger.record_action(
                        action_name="messages_create",
                        action_type="llm_call",
                        result="failure",
                        target_system="anthropic",
                        target_resource=model,
                        duration_ms=elapsed_ms,
                        input_data=input_data,
                        error_message=str(exc),
                    )
                except Exception:
                    logger.warning(
                        "Failed to record audit event for Anthropic stream-init failure",
                        exc_info=True,
                    )
                raise
            recorder = _StreamRecorder(
                ledger=self._ledger,
                redactor=self._redactor,
                input_data=input_data,
                model=model,
                started_at=start,
            )
            return _AuditedRawStream(raw, recorder)

        start = time.perf_counter()
        try:
            response = self._original.create(**kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            outcome = {}

            # Extract text from content blocks
            if hasattr(response, "content") and response.content:
                text_blocks = [
                    block.text
                    for block in response.content
                    if hasattr(block, "type") and block.type == "text"
                ]
                if text_blocks:
                    outcome["response"] = self._redactor.serialize(
                        "\n".join(text_blocks)
                    )

            if hasattr(response, "stop_reason") and response.stop_reason:
                outcome["stop_reason"] = response.stop_reason

            if hasattr(response, "usage") and response.usage:
                outcome["token_usage"] = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens
                    + response.usage.output_tokens,
                }

            try:
                self._ledger.record_action(
                    action_name="messages_create",
                    action_type="llm_call",
                    result="success",
                    target_system="anthropic",
                    target_resource=model,
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    outcome=outcome,
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for Anthropic call",
                    exc_info=True,
                )

            return response

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            try:
                self._ledger.record_action(
                    action_name="messages_create",
                    action_type="llm_call",
                    result="failure",
                    target_system="anthropic",
                    target_resource=model,
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    error_message=str(exc),
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for Anthropic error",
                    exc_info=True,
                )
            raise

    # ------------------------------------------------------------------
    # stream() — high-level context-manager API
    # ------------------------------------------------------------------

    def stream(self, **kwargs):
        input_data = self._build_input_data(kwargs)
        model = kwargs.get("model", "unknown")
        start = time.perf_counter()
        try:
            raw_stream = self._original.stream(**kwargs)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            try:
                self._ledger.record_action(
                    action_name="messages_create",
                    action_type="llm_call",
                    result="failure",
                    target_system="anthropic",
                    target_resource=model,
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    error_message=str(exc),
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for Anthropic stream-init failure",
                    exc_info=True,
                )
            raise
        recorder = _StreamRecorder(
            ledger=self._ledger,
            redactor=self._redactor,
            input_data=input_data,
            model=model,
            started_at=start,
        )
        return _AuditedMessageStream(raw_stream, recorder)

    def __getattr__(self, name):
        return getattr(self._original, name)


# ---------------------------------------------------------------------------
# Top-level wrapper
# ---------------------------------------------------------------------------


class AuditedAnthropic:
    """Wrapper around anthropic.Anthropic that audits all Messages API calls.

    Streaming via either ``messages.create(stream=True)`` or
    ``messages.stream(...)`` is fully audited — content is buffered in
    memory (1MB cap) and emitted as a single audit record on close.

    Args:
        anthropic_client: an instance of ``anthropic.Anthropic``.
        ledger_client: a ``vera.VeraClient`` (or compatible).
        redactor: a :class:`vera.redaction.Redactor` to scrub captured
            content before it lands in the audit DB. Defaults to the
            SDK-wide redactor (see ``vera.decorator.get_default_redactor``).

    Usage:
        import anthropic
        from vera.integrations.anthropic import AuditedAnthropic

        ledger = VeraClient(api_url=..., api_key=..., agent_name="my-agent")
        client = AuditedAnthropic(anthropic.Anthropic(), ledger_client=ledger)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Summarize this document..."}],
        )
        # The call is automatically recorded in the Vera audit trail.
    """

    def __init__(
        self,
        anthropic_client,
        ledger_client,
        redactor: Redactor | None = None,
    ):
        self._original = anthropic_client
        self._ledger = ledger_client
        self._redactor = redactor if redactor is not None else _resolve_default_redactor()
        self.messages = _AuditedMessages(
            anthropic_client.messages,
            ledger_client,
            redactor=self._redactor,
        )

    def __getattr__(self, name):
        if name == "messages":
            return self.messages
        return getattr(self._original, name)
