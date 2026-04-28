"""Tests for the LangChain VeraCallbackHandler.

Skipped at import time if ``langchain-core`` is not installed —
``langchain`` is an optional extra of ``vera-sdk``.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# importorskip BEFORE importing the integration — the integration's module
# top-level raises ImportError when langchain-core is missing.
pytest.importorskip("langchain_core")

from vera.integrations.langchain import VeraCallbackHandler  # noqa: E402
from vera.redaction import Redactor  # noqa: E402


def _make_llm_result(text: str, *, token_usage: dict | None = None):
    """Build a duck-typed object compatible with ``response.generations``
    and ``response.llm_output`` access used by ``on_llm_end``."""
    return SimpleNamespace(
        generations=[[SimpleNamespace(text=text)]],
        llm_output={"token_usage": token_usage} if token_usage is not None else None,
    )


class TestLLMCallbacks:
    def test_on_llm_end_records_redacted_output(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        handler.on_llm_start({}, ["hi"], run_id=run_id)
        handler.on_llm_end(
            _make_llm_result("The patient's SSN is 123-45-6789"),
            run_id=run_id,
        )

        client.record_action.assert_called_once()
        call = client.record_action.call_args[1]
        assert call["action_type"] == "llm_call"
        assert call["result"] == "success"
        assert "[REDACTED:ssn]" in call["outcome"]["output"]
        assert "123-45-6789" not in call["outcome"]["output"]
        assert call["duration_ms"] is not None

    def test_on_llm_error_records_failure(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        handler.on_llm_start({}, ["hi"], run_id=run_id)
        handler.on_llm_error(RuntimeError("boom"), run_id=run_id)

        client.record_action.assert_called_once()
        call = client.record_action.call_args[1]
        assert call["action_type"] == "llm_call"
        assert call["result"] == "failure"
        assert call["error_message"] == "boom"

    def test_token_usage_not_redacted(self):
        """token_usage is a structured numeric dict — keep it as-is."""
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        token_usage = {"total_tokens": 42, "prompt_tokens": 10, "completion_tokens": 32}
        handler.on_llm_start({}, ["hi"], run_id=run_id)
        handler.on_llm_end(
            _make_llm_result("hello world", token_usage=token_usage),
            run_id=run_id,
        )

        call = client.record_action.call_args[1]
        # Identity-preserving: same dict shape and numeric values.
        assert call["outcome"]["token_usage"] == token_usage
        assert isinstance(call["outcome"]["token_usage"]["total_tokens"], int)


class TestChainCallbacks:
    def test_on_chain_end_serializes_dict_outputs(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        outputs = {"answer": "Their SSN is 111-22-3333", "score": 0.9}
        handler.on_chain_start({}, {}, run_id=run_id)
        handler.on_chain_end(outputs, run_id=run_id)

        call = client.record_action.call_args[1]
        out = call["outcome"]["output"]
        # Dict shape preserved (better for indexing than repr()).
        assert isinstance(out, dict)
        assert "answer" in out
        assert "[REDACTED:ssn]" in out["answer"]
        assert "111-22-3333" not in str(out)
        # Non-string values preserved (after going through redactor.serialize).
        assert "0.9" in str(out["score"])

    def test_on_chain_error_records_failure(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        handler.on_chain_start({}, {}, run_id=run_id)
        handler.on_chain_error(ValueError("bad chain"), run_id=run_id)

        call = client.record_action.call_args[1]
        assert call["action_type"] == "chain_execution"
        assert call["result"] == "failure"
        assert call["error_message"] == "bad chain"


class TestToolCallbacks:
    def test_on_tool_end_redacts_output(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        handler.on_tool_start({}, "lookup", run_id=run_id)
        handler.on_tool_end("Result: 123-45-6789", run_id=run_id)

        call = client.record_action.call_args[1]
        assert call["action_type"] == "tool_call"
        assert "[REDACTED:ssn]" in call["outcome"]["output"]


class TestAgentCallbacks:
    def test_on_agent_action_redacts_tool_input(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        action = SimpleNamespace(
            tool="lookup_patient",
            tool_input={"ssn": "123-45-6789", "name": "Alice"},
        )
        handler.on_agent_action(action, run_id=run_id)

        call = client.record_action.call_args[1]
        assert call["action_type"] == "agent_action"
        # block_keys: "ssn" key is redacted entirely.
        rendered = str(call["input_data"]["tool_input"])
        assert "123-45-6789" not in rendered
        assert "[REDACTED" in rendered

    def test_on_agent_finish_redacts_return_values(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        run_id = uuid4()

        finish = SimpleNamespace(
            return_values={"output": "Final answer for SSN 999-88-7777"},
        )
        handler.on_agent_finish(finish, run_id=run_id)

        call = client.record_action.call_args[1]
        assert call["action_type"] == "agent_action"
        assert "[REDACTED:ssn]" in str(call["outcome"]["output"])
        assert "999-88-7777" not in str(call["outcome"]["output"])


class TestRedactorWiring:
    def test_custom_redactor_overrides_default(self):
        client = MagicMock()
        custom = Redactor(replacement="[XXX]")
        handler = VeraCallbackHandler(client=client, redactor=custom)
        run_id = uuid4()

        handler.on_llm_start({}, ["hi"], run_id=run_id)
        handler.on_llm_end(_make_llm_result("ssn 123-45-6789"), run_id=run_id)

        call = client.record_action.call_args[1]
        # Custom replacement format: "[XXX:ssn]" (Redactor injects the
        # pattern name before the closing bracket).
        assert "[XXX:ssn]" in call["outcome"]["output"]

    def test_default_redactor_used_when_not_provided(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        # Same instance returned by get_default_redactor()
        from vera.decorator import get_default_redactor
        assert handler._redactor is get_default_redactor()

    def test_capture_outputs_false_skips_outcome_capture(self):
        client = MagicMock()
        handler = VeraCallbackHandler(client=client, capture_outputs=False)
        run_id = uuid4()

        handler.on_llm_start({}, ["hi"], run_id=run_id)
        handler.on_llm_end(_make_llm_result("plain text output"), run_id=run_id)

        call = client.record_action.call_args[1]
        # No "output" key when capture_outputs=False
        assert "output" not in call["outcome"]

    def test_deprecated_max_length_kwargs_emit_warning(self):
        client = MagicMock()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            VeraCallbackHandler(
                client=client,
                max_input_length=500,
                max_output_length=500,
            )
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "max_input_length" in str(w.message)
            for w in caught
        )

    def test_back_compat_constructor_signature(self):
        """Old call sites that pass only ``client=`` must still work."""
        client = MagicMock()
        handler = VeraCallbackHandler(client=client)
        assert handler.client is client
        assert handler.capture_inputs is True
        assert handler.capture_outputs is True
