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

Note: streaming (with client.messages.stream()) is not audited in v1.
Use client.messages.create() for audited calls.
"""

import logging
import time

logger = logging.getLogger("vera.integrations.anthropic")


class _AuditedMessages:
    """Wraps anthropic.messages to record each create() call."""

    def __init__(self, original_messages, ledger_client, max_input_length=10000, max_output_length=10000):
        self._original = original_messages
        self._ledger = ledger_client
        self._max_input = max_input_length
        self._max_output = max_output_length

    def _truncate(self, text: str, max_length: int) -> str:
        if len(text) > max_length:
            return text[:max_length] + "...[truncated]"
        return text

    def create(self, **kwargs):
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        input_data = {
            "model": model,
            "message_count": len(messages),
            "max_tokens": kwargs.get("max_tokens"),
        }
        if messages:
            last_msg = messages[-1]
            content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
            if isinstance(content, list):
                # content blocks format — extract text blocks
                text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                content = " ".join(text_parts)
            input_data["last_message"] = self._truncate(str(content), self._max_input)

        if kwargs.get("system"):
            input_data["system_prompt_length"] = len(str(kwargs["system"]))

        start = time.perf_counter()
        try:
            response = self._original.create(**kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            outcome = {}

            # Extract text from content blocks
            if hasattr(response, "content") and response.content:
                text_blocks = [
                    block.text for block in response.content
                    if hasattr(block, "type") and block.type == "text"
                ]
                if text_blocks:
                    outcome["response"] = self._truncate(
                        "\n".join(text_blocks), self._max_output
                    )

            if hasattr(response, "stop_reason"):
                outcome["stop_reason"] = response.stop_reason

            if hasattr(response, "usage") and response.usage:
                outcome["token_usage"] = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
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
                logger.warning("Failed to record audit event for Anthropic call", exc_info=True)

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
                logger.warning("Failed to record audit event for Anthropic error", exc_info=True)
            raise

    @property
    def stream(self):
        """Streaming is not audited. Calls are passed through with a warning."""
        logger.warning(
            "Vera: streaming (client.messages.stream()) is not yet "
            "supported for auditing. These calls will NOT be recorded in the "
            "audit trail. Use client.messages.create() for audited calls."
        )
        return self._original.stream

    def __getattr__(self, name):
        return getattr(self._original, name)


class AuditedAnthropic:
    """Wrapper around anthropic.Anthropic that audits all Messages API calls.

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

    def __init__(self, anthropic_client, ledger_client, max_input_length=10000, max_output_length=10000):
        self._original = anthropic_client
        self._ledger = ledger_client
        self.messages = _AuditedMessages(
            anthropic_client.messages,
            ledger_client,
            max_input_length=max_input_length,
            max_output_length=max_output_length,
        )

    def __getattr__(self, name):
        if name == "messages":
            return self.messages
        return getattr(self._original, name)
