"""OpenAI integration — wraps chat completions to audit all LLM calls.

Usage:
    from vera.integrations.openai import AuditedOpenAI
    client = AuditedOpenAI(openai.OpenAI(), ledger_client=ledger)
    response = client.chat.completions.create(model="gpt-4o", messages=[...])

Note: streaming (stream=True) is not handled in v1.
"""

import logging
import time

logger = logging.getLogger("vera.integrations.openai")


class _AuditedCompletions:
    """Wraps openai.chat.completions to record each create() call."""

    def __init__(self, original_completions, ledger_client, max_input_length=10000, max_output_length=10000):
        self._original = original_completions
        self._ledger = ledger_client
        self._max_input = max_input_length
        self._max_output = max_output_length

    def _truncate(self, text: str, max_length: int) -> str:
        if len(text) > max_length:
            return text[:max_length] + "...[truncated]"
        return text

    def create(self, **kwargs):
        if kwargs.get("stream"):
            logger.warning(
                "Vera: stream=True is not yet supported for auditing. "
                "This call will NOT be recorded in the audit trail."
            )
            return self._original.create(**kwargs)

        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        input_data = {
            "model": model,
            "message_count": len(messages),
        }
        if messages:
            last_msg = messages[-1]
            content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
            input_data["last_message"] = self._truncate(str(content), self._max_input)

        start = time.perf_counter()
        try:
            response = self._original.create(**kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            outcome = {}
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and choice.message:
                    outcome["response"] = self._truncate(
                        choice.message.content or "", self._max_output
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
                logger.warning("Failed to record audit event for OpenAI call", exc_info=True)

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
                logger.warning("Failed to record audit event for OpenAI error", exc_info=True)
            raise

    def __getattr__(self, name):
        return getattr(self._original, name)


class _AuditedChat:
    """Proxy for openai.chat that swaps in _AuditedCompletions."""

    def __init__(self, original_chat, ledger_client, **kwargs):
        self._original = original_chat
        self.completions = _AuditedCompletions(
            original_chat.completions, ledger_client, **kwargs
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
    """

    def __init__(self, openai_client, ledger_client, **kwargs):
        self._original = openai_client
        self._ledger = ledger_client
        self.chat = _AuditedChat(openai_client.chat, ledger_client, **kwargs)

    def __getattr__(self, name):
        if name == "chat":
            return self.chat
        return getattr(self._original, name)


# Track patch state to prevent double-patching
_openai_patched = False
_openai_original_init = None


def patch_openai(ledger_client):
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
        self.chat = _AuditedChat(self.chat, ledger_client)

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
