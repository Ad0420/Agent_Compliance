"""LangChain callback handler for automatic audit logging."""

import logging
import time
from typing import Any
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    raise ImportError(
        "langchain-core is required for LangChain integration. "
        "Install it with: pip install actionledger[langchain]"
    )

logger = logging.getLogger("actionledger.integrations.langchain")


class ActionLedgerCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that records all LLM/chain/tool/agent actions
    to the Action Ledger.

    Usage:
        handler = ActionLedgerCallbackHandler(client=ledger_client)
        chain.invoke(inputs, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        client,
        capture_inputs: bool = True,
        capture_outputs: bool = True,
        max_input_length: int = 10000,
        max_output_length: int = 10000,
    ):
        super().__init__()
        self.client = client
        self.capture_inputs = capture_inputs
        self.capture_outputs = capture_outputs
        self.max_input_length = max_input_length
        self.max_output_length = max_output_length
        self._run_starts: dict[str, float] = {}

    def _truncate(self, text: str, max_length: int) -> str:
        if len(text) > max_length:
            return text[:max_length] + "...[truncated]"
        return text

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
            outcome["output"] = self._truncate(text, self.max_output_length)

        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            if token_usage:
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
            outcome["output"] = self._truncate(repr(outputs), self.max_output_length)

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
            outcome["output"] = self._truncate(str(output), self.max_output_length)

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
            input_data["tool_input"] = self._truncate(
                repr(getattr(action, "tool_input", "")), self.max_input_length
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
            outcome["output"] = self._truncate(
                str(getattr(finish, "return_values", finish)), self.max_output_length
            )

        self._record(
            action_name="agent_action",
            action_type="agent_action",
            result="success",
            duration_ms=duration,
            outcome=outcome,
            reasoning={"run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None},
        )
