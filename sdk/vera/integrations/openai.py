"""OpenAI integration — wraps chat completions to audit all LLM calls.

Usage:
    from vera.integrations.openai import AuditedOpenAI
    client = AuditedOpenAI(openai.OpenAI(), ledger_client=ledger)
    response = client.chat.completions.create(model="gpt-4o", messages=[...])

Streaming (``stream=True``) is supported via a buffer-and-record model:
the wrapper forwards every ``ChatCompletionChunk`` to the caller as soon as
it arrives (no extra latency / no UX regression) while accumulating the
delta content in memory. One audit record fires on stream close. The
in-memory buffer is capped at 1MB to bound worst-case memory usage.

Redaction is on by default. The constructor accepts a ``redactor`` kwarg;
``None`` (the default) falls back to ``vera.decorator.get_default_redactor()``.
Pass an explicit ``Redactor`` to customise — e.g. with a tenant-specific
``block_keys`` set — or pass a no-op-configured Redactor to disable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("vera.integrations.openai")


# 1MB cap for streamed content. Chosen as a safety bound on a model that
# buffers the full response before emitting one audit record. If we ever
# need a higher cap we should switch to a chunk-trail model instead of
# raising this number.
_STREAM_BUFFER_CAP = 1_048_576
_STREAM_TRUNCATION_SUFFIX = "...[stream truncated by vera at 1MB]"


def _resolve_default_redactor():
    """Lazy import to avoid an import-time cycle.

    ``vera.decorator`` already imports from ``vera.redaction``, so importing
    it here at call time is safe — no circular path runs through
    ``vera.integrations.openai``.
    """
    from vera.decorator import get_default_redactor

    return get_default_redactor()


class _AuditedStreamIterator:
    """Wraps an OpenAI streaming response.

    Forwards chunks unchanged to the caller, captures content into a 1MB
    buffer, and fires exactly one audit record when the stream closes —
    either via successful exhaustion (``StopIteration``), an iteration
    error, or context-manager ``__exit__``.
    """

    def __init__(
        self,
        stream,
        ledger,
        redactor,
        input_data: dict,
        model: str,
        started_at: float,
    ) -> None:
        self._stream = stream
        self._ledger = ledger
        self._redactor = redactor
        self._input_data = input_data
        self._model = model
        self._started_at = started_at
        self._buffer: list[str] = []
        self._buffer_size = 0
        self._truncated = False
        self._usage: dict | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Iterator protocol
    # ------------------------------------------------------------------

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._record_success()
            raise
        except Exception as exc:
            self._record_failure(exc)
            raise
        self._capture(chunk)
        return chunk

    # ------------------------------------------------------------------
    # Context-manager protocol — OpenAI streams support
    #     with client.chat.completions.create(stream=True, ...) as s:
    #         for chunk in s: ...
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            err = exc_val if exc_val is not None else Exception(
                getattr(exc_type, "__name__", "stream error")
            )
            self._record_failure(err)
        else:
            self._record_success()
        # Best-effort: close the underlying stream if it exposes one.
        close = getattr(self._stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.warning(
                    "Vera: error closing underlying OpenAI stream", exc_info=True
                )
        return False  # never suppress caller exceptions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _capture(self, chunk) -> None:
        """Pull delta content + usage out of a single chunk.

        Wrapped in a broad try/except: a malformed chunk shape must never
        take down the caller's stream. This is auditing infra — failing
        open is the right call.
        """
        try:
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if content and not self._truncated:
                    if self._buffer_size + len(content) > _STREAM_BUFFER_CAP:
                        remaining = _STREAM_BUFFER_CAP - self._buffer_size
                        if remaining > 0:
                            self._buffer.append(content[:remaining])
                            self._buffer_size = _STREAM_BUFFER_CAP
                        self._truncated = True
                        logger.warning(
                            "Vera: OpenAI stream content exceeded 1MB cap; "
                            "audit will record the first 1MB only"
                        )
                    else:
                        self._buffer.append(content)
                        self._buffer_size += len(content)
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self._usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
        except Exception:
            logger.warning("Vera: failed to capture stream chunk", exc_info=True)

    def _record_success(self) -> None:
        if self._closed:
            return
        self._closed = True
        full_text = "".join(self._buffer)
        if self._truncated:
            full_text += _STREAM_TRUNCATION_SUFFIX
        elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        outcome: dict[str, Any] = {"response": self._redactor.serialize(full_text)}
        if self._usage is not None:
            outcome["token_usage"] = self._usage
        try:
            self._ledger.record_action(
                action_name="chat_completion",
                action_type="llm_call",
                result="success",
                target_system="openai",
                target_resource=self._model,
                duration_ms=elapsed_ms,
                input_data=self._input_data,
                outcome=outcome,
            )
        except Exception:
            logger.warning(
                "Failed to record audit event for streamed OpenAI call",
                exc_info=True,
            )

    def _record_failure(self, exc: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        elapsed_ms = int((time.perf_counter() - self._started_at) * 1000)
        partial = "".join(self._buffer)
        try:
            self._ledger.record_action(
                action_name="chat_completion",
                action_type="llm_call",
                result="failure",
                target_system="openai",
                target_resource=self._model,
                duration_ms=elapsed_ms,
                input_data=self._input_data,
                error_message=str(exc),
                outcome={"partial_response": self._redactor.serialize(partial)},
            )
        except Exception:
            logger.warning(
                "Failed to record audit event for streamed OpenAI failure",
                exc_info=True,
            )


class _AuditedCompletions:
    """Wraps openai.chat.completions to record each create() call."""

    def __init__(self, original_completions, ledger_client, redactor=None):
        self._original = original_completions
        self._ledger = ledger_client
        self._redactor = (
            redactor if redactor is not None else _resolve_default_redactor()
        )

    def _build_input_data(self, kwargs: dict) -> dict:
        """Extract the audit-friendly view of the request kwargs.

        Shared between the streaming and non-streaming paths so the two
        emit identical ``input_data`` shapes.
        """
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        input_data: dict[str, Any] = {
            "model": model,
            "message_count": len(messages),
        }
        if messages:
            last_msg = messages[-1]
            content = (
                last_msg.get("content", "")
                if isinstance(last_msg, dict)
                else str(last_msg)
            )
            input_data["last_message"] = self._redactor.serialize(str(content))
        return input_data

    def create(self, **kwargs):
        model = kwargs.get("model", "unknown")
        input_data = self._build_input_data(kwargs)
        start = time.perf_counter()

        if kwargs.get("stream"):
            # Buffer-and-record: get the raw stream, wrap it, return the
            # wrapper. The audit fires when the caller drains the stream.
            try:
                raw_stream = self._original.create(**kwargs)
            except Exception as exc:
                # Failure happened before iteration even started — record
                # immediately so the caller still sees an audit row.
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                try:
                    self._ledger.record_action(
                        action_name="chat_completion",
                        action_type="llm_call",
                        result="failure",
                        target_system="openai",
                        target_resource=model,
                        duration_ms=elapsed_ms,
                        input_data=input_data,
                        error_message=str(exc),
                    )
                except Exception:
                    logger.warning(
                        "Failed to record audit event for OpenAI stream init failure",
                        exc_info=True,
                    )
                raise
            return _AuditedStreamIterator(
                stream=raw_stream,
                ledger=self._ledger,
                redactor=self._redactor,
                input_data=input_data,
                model=model,
                started_at=start,
            )

        # Non-streaming path
        try:
            response = self._original.create(**kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            outcome: dict[str, Any] = {}
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and choice.message:
                    outcome["response"] = self._redactor.serialize(
                        choice.message.content or ""
                    )

            if hasattr(response, "usage") and response.usage:
                outcome["token_usage"] = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            try:
                self._ledger.record_action(
                    action_name="chat_completion",
                    action_type="llm_call",
                    result="success",
                    target_system="openai",
                    target_resource=model,
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    outcome=outcome,
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for OpenAI call", exc_info=True
                )

            return response

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            try:
                self._ledger.record_action(
                    action_name="chat_completion",
                    action_type="llm_call",
                    result="failure",
                    target_system="openai",
                    target_resource=model,
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    error_message=str(exc),
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for OpenAI error", exc_info=True
                )
            raise

    def __getattr__(self, name):
        return getattr(self._original, name)


class _AuditedChat:
    """Proxy for openai.chat that swaps in _AuditedCompletions."""

    def __init__(self, original_chat, ledger_client, redactor=None, **kwargs):
        self._original = original_chat
        self.completions = _AuditedCompletions(
            original_chat.completions, ledger_client, redactor=redactor, **kwargs
        )

    def __getattr__(self, name):
        if name == "completions":
            return self.completions
        return getattr(self._original, name)


class AuditedOpenAI:
    """Wrapper around openai.OpenAI that audits all chat completions.

    Usage:
        client = AuditedOpenAI(openai.OpenAI(), ledger_client=ledger)
        response = client.chat.completions.create(model="gpt-4o", messages=[...])

    Args:
        openai_client: An ``openai.OpenAI`` instance.
        ledger_client: A ``VeraClient`` (or any object exposing
            ``record_action``).
        redactor: Optional :class:`vera.Redactor`. Defaults to
            ``vera.decorator.get_default_redactor()`` so PII / secrets in
            prompts and responses are scrubbed before they hit the audit
            DB. Pass an explicit Redactor to customise.
    """

    def __init__(self, openai_client, ledger_client, redactor=None, **kwargs):
        self._original = openai_client
        self._ledger = ledger_client
        self.chat = _AuditedChat(
            openai_client.chat, ledger_client, redactor=redactor, **kwargs
        )

    def __getattr__(self, name):
        if name == "chat":
            return self.chat
        return getattr(self._original, name)


# Track patch state to prevent double-patching
_openai_patched = False
_openai_original_init = None


def patch_openai(ledger_client, redactor=None):
    """Monkey-patch openai.OpenAI so all future clients are auto-audited.

    Idempotent — calling multiple times is safe. Use unpatch_openai() to restore.

    Usage:
        patch_openai(ledger_client=ledger)
        client = openai.OpenAI()  # Automatically audited
    """
    global _openai_patched, _openai_original_init

    if _openai_patched:
        logger.warning("patch_openai() called but OpenAI is already patched — skipping")
        return

    try:
        import openai as openai_module
    except ImportError:
        raise ImportError(
            "openai is required for OpenAI integration. "
            "Install it with: pip install vera-sdk[openai]"
        )

    _openai_original_init = openai_module.OpenAI.__init__

    def _patched_init(self, *args, **kwargs):
        _openai_original_init(self, *args, **kwargs)
        self.chat = _AuditedChat(self.chat, ledger_client, redactor=redactor)

    openai_module.OpenAI.__init__ = _patched_init
    _openai_patched = True


def unpatch_openai():
    """Restore the original openai.OpenAI.__init__ method."""
    global _openai_patched, _openai_original_init

    if not _openai_patched or _openai_original_init is None:
        return

    try:
        import openai as openai_module
        openai_module.OpenAI.__init__ = _openai_original_init
    except ImportError:
        pass

    _openai_patched = False
    _openai_original_init = None
