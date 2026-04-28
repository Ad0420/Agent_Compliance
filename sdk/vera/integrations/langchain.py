"""LangChain callback handler for automatic audit logging.

The handler runs every captured value (prompts, outputs, tool inputs,
agent return values, etc.) through a :class:`Redactor` before recording.
Redaction is opt-out — pass ``redactor=...`` to override the default,
or ``redactor=Redactor(patterns=[])`` to effectively disable.
"""

import logging
import time
import warnings
from typing import Any
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    raise ImportError(
        "langchain-core is required for LangChain integration. "
        "Install it with: pip install vera-sdk[langchain]"
    )

from vera.redaction import Redactor

logger = logging.getLogger("vera.integrations.langchain")


class VeraCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that records all LLM/chain/tool/agent actions
    to the Vera ledger.

    All captured payloads (prompts, outputs, tool inputs, agent return
    values) are passed through a :class:`Redactor` so PII / secrets do
    not leak into the audit trail. Pass ``redactor=`` to customise; the
    default :func:`vera.decorator.get_default_redactor` is used otherwise.

    ``token_usage`` is intentionally NOT redacted — it is a structured
    numeric dict and benefits from staying indexable.

    Usage:
        handler = VeraCallbackHandler(client=ledger_client)
        chain.invoke(inputs, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        client,
        capture_inputs: bool = True,
        capture_outputs: bool = True,
        max_input_length: int = 10000,   # deprecated — Redactor.max_length now governs
        max_output_length: int = 10000,  # deprecated — Redactor.max_length now governs
        redactor: Redactor | None = None,
    ):
        super().__init__()
        self.client = client
        self.capture_inputs = capture_inputs
        self.capture_outputs = capture_outputs

        # max_input_length / max_output_length are kept in the signature
        # for back-compat. Length capping is now handled by the Redactor.
        # If a caller passes a non-default value we emit a one-time
        # DeprecationWarning so existing code keeps working without noise.
        if max_input_length != 10000 or max_output_length != 10000:
            warnings.warn(
                "max_input_length / max_output_length are deprecated and ignored; "
                "use redactor=Redactor(max_length=...) instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        if redactor is not None:
            self._redactor = redactor
        else:
            from vera.decorator import get_default_redactor
            self._redactor = get_default_redactor()

        self._run_starts: dict[str, float] = {}

    def _elapsed_ms(self, run_id: UUID) -> int | None:
        key = str(run_id)
        start = self._run_starts.pop(key, None)
        if start is not None:
            return int((time.perf_counter() - start) * 1000)
        return None

    def _record(self, **kwargs):
        try:
            self.client.record_action(**kwargs)
        except Exception:
            logger.warning("Failed to record audit event", exc_info=True)

    # ── LLM callbacks ──────────────────────────────────────

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str],
        *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs,
    ) -> None:
        self._run_starts[str(run_id)] = time.perf_counter()

    def on_llm_end(self, response, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        input_data = {}
        outcome = {}

        if self.capture_outputs and response.generations:
            text = response.generations[0][0].text if response.generations[0] else ""
            outcome["output"] = self._redactor.serialize(text)

        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            if token_usage:
                # Structured numeric dict — leave un-redacted so it stays indexable.
                outcome["token_usage"] = token_usage

        self._record(
            action_name="llm_call",
            action_type="llm_call",
            result="success",
            duration_ms=duration,
            input_data=input_data,
            outcome=outcome,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        self._record(
            action_name="llm_call",
            action_type="llm_call",
            result="failure",
            error_message=str(error),
            duration_ms=duration,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    # ── Chain callbacks ────────────────────────────────────

    def on_chain_start(
        self, serialized: dict[str, Any], inputs: dict[str, Any],
        *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs,
    ) -> None:
        self._run_starts[str(run_id)] = time.perf_counter()

    def on_chain_end(self, outputs: dict[str, Any], *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        outcome = {}
        if self.capture_outputs:
            # Pass the dict through the redactor directly — it preserves shape
            # (dict-of-redacted-strings), which is more useful for indexing
            # than a single repr() string.
            outcome["output"] = self._redactor.serialize(outputs)

        self._record(
            action_name="chain_execution",
            action_type="chain_execution",
            result="success",
            duration_ms=duration,
            outcome=outcome,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    def on_chain_error(self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        self._record(
            action_name="chain_execution",
            action_type="chain_execution",
            result="failure",
            error_message=str(error),
            duration_ms=duration,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    # ── Tool callbacks ─────────────────────────────────────

    def on_tool_start(
        self, serialized: dict[str, Any], input_str: str,
        *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs,
    ) -> None:
        self._run_starts[str(run_id)] = time.perf_counter()

    def on_tool_end(self, output: str, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        outcome = {}
        if self.capture_outputs:
            outcome["output"] = self._redactor.serialize(output)

        self._record(
            action_name="tool_call",
            action_type="tool_call",
            result="success",
            duration_ms=duration,
            outcome=outcome,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    def on_tool_error(self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        self._record(
            action_name="tool_call",
            action_type="tool_call",
            result="failure",
            error_message=str(error),
            duration_ms=duration,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    # ── Agent callbacks ────────────────────────────────────

    def on_agent_action(self, action, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        self._run_starts[str(run_id)] = time.perf_counter()
        input_data = {}
        if self.capture_inputs:
            input_data["tool"] = getattr(action, "tool", str(action))
            input_data["tool_input"] = self._redactor.serialize(
                getattr(action, "tool_input", "")
            )

        self._record(
            action_name="agent_action",
            action_type="agent_action",
            result="success",
            input_data=input_data,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )

    def on_agent_finish(self, finish, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs) -> None:
        duration = self._elapsed_ms(run_id)
        outcome = {}
        if self.capture_outputs:
            outcome["output"] = self._redactor.serialize(
                getattr(finish, "return_values", finish)
            )

        self._record(
            action_name="agent_action",
            action_type="agent_action",
            result="success",
            duration_ms=duration,
            outcome=outcome,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )
