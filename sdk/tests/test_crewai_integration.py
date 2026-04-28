"""Tests for the CrewAI integration (BaseTool._run monkey-patch).

The real ``crewai`` package is heavy and not installable in many CI
sandboxes. We try ``pytest.importorskip("crewai")`` first; if it fails
we install a minimal fake ``crewai.tools`` module into ``sys.modules``
so we can still test the wrapping logic — the integration only depends
on a duck-typed ``BaseTool`` class with a ``_run`` method, ``name``,
and ``description`` attributes, which is straightforward to fake.

This split is intentional: the SDK's CrewAI integration is a
monkey-patch over a single attribute, so testing against a stand-in
class exercises the same code path as the real package.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# ── Real-or-fake crewai resolution ─────────────────────────────────────

def _install_fake_crewai() -> type:
    """Install a fake ``crewai.tools.BaseTool`` and return the class."""
    fake_crewai = types.ModuleType("crewai")
    fake_tools = types.ModuleType("crewai.tools")

    class FakeBaseTool:
        name = "fake_base_tool"
        description = "A fake base tool"

        def _run(self, *args, **kwargs):
            return f"ran with args={args!r} kwargs={kwargs!r}"

    fake_tools.BaseTool = FakeBaseTool
    fake_crewai.tools = fake_tools
    sys.modules["crewai"] = fake_crewai
    sys.modules["crewai.tools"] = fake_tools
    return FakeBaseTool


try:
    import crewai  # noqa: F401
    from crewai.tools import BaseTool  # type: ignore  # noqa: F401
    _USING_REAL_CREWAI = True
except ImportError:
    _install_fake_crewai()
    _USING_REAL_CREWAI = False


# Import the integration AFTER crewai (real or fake) is in sys.modules.
from vera.integrations.crewai import (  # noqa: E402
    enable_crewai_auditing,
    disable_crewai_auditing,
)
from vera.redaction import Redactor  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_patch_state():
    """Always start each test with the patch disabled."""
    disable_crewai_auditing()
    yield
    disable_crewai_auditing()


def _fresh_tool_subclass(name: str = "test_tool", description: str = "A test tool"):
    """Build a fresh subclass of the (real or fake) BaseTool for a test."""
    from crewai.tools import BaseTool  # re-import — sys.modules may have been mutated

    class _Tool(BaseTool):
        pass

    _Tool.name = name
    _Tool.description = description
    return _Tool


# ── Tests ──────────────────────────────────────────────────────────────


class TestEnableDisable:
    def test_enable_patches_base_tool_run(self):
        from crewai.tools import BaseTool
        original = BaseTool._run
        client = MagicMock()
        enable_crewai_auditing(client)
        assert BaseTool._run is not original

    def test_disable_restores_original_run(self):
        from crewai.tools import BaseTool
        original = BaseTool._run
        client = MagicMock()
        enable_crewai_auditing(client)
        assert BaseTool._run is not original
        disable_crewai_auditing()
        assert BaseTool._run is original

    def test_enable_is_idempotent(self):
        from crewai.tools import BaseTool
        client = MagicMock()
        enable_crewai_auditing(client)
        first_patch = BaseTool._run
        # Calling again must NOT double-wrap.
        enable_crewai_auditing(client)
        assert BaseTool._run is first_patch


class TestSuccessfulToolCall:
    def test_successful_run_records_audit_event(self):
        client = MagicMock()
        enable_crewai_auditing(client)

        Tool = _fresh_tool_subclass(name="lookup", description="Lookup tool")
        tool = Tool()
        result = tool._run("hello")

        assert "ran with" in result
        client.record_action.assert_called_once()
        call = client.record_action.call_args[1]
        assert call["action_name"] == "lookup"
        assert call["action_type"] == "tool_call"
        assert call["result"] == "success"
        assert call["framework"] == "crewai"
        assert call["duration_ms"] is not None
        assert "output" in call["outcome"]

    def test_args_and_kwargs_are_redacted(self):
        client = MagicMock()
        enable_crewai_auditing(client)

        Tool = _fresh_tool_subclass()
        tool = Tool()
        tool._run("My SSN is 123-45-6789", patient_id="999-88-7777")

        call = client.record_action.call_args[1]
        # Positional arg redacted.
        rendered_args = str(call["input_data"]["args"])
        assert "[REDACTED:ssn]" in rendered_args
        assert "123-45-6789" not in rendered_args
        # kwargs also redacted.
        rendered_kwargs = str(call["input_data"]["kwargs"])
        assert "999-88-7777" not in rendered_kwargs

    def test_tool_description_is_redacted(self):
        client = MagicMock()
        enable_crewai_auditing(client)

        Tool = _fresh_tool_subclass(
            name="leaky",
            description="Looks up SSN 123-45-6789",
        )
        tool = Tool()
        tool._run()

        call = client.record_action.call_args[1]
        desc = call["input_data"]["tool_description"]
        assert "[REDACTED:ssn]" in desc
        assert "123-45-6789" not in desc

    def test_result_is_redacted(self):
        """Stub the pre-patch ``_original_run`` indirectly: we install a
        leaky implementation as the unpatched ``BaseTool._run`` BEFORE
        enabling auditing, so the patch wraps it and we can observe
        redaction of the return value."""
        from crewai.tools import BaseTool

        # Install leaky impl as the pristine method.
        def leaky_run(self, *args, **kwargs):
            return "Patient SSN: 555-66-7777"

        original = BaseTool._run
        BaseTool._run = leaky_run
        try:
            client = MagicMock()
            enable_crewai_auditing(client)

            Tool = _fresh_tool_subclass(name="leaky_tool")
            tool = Tool()
            tool._run()

            call = client.record_action.call_args[1]
            assert "[REDACTED:ssn]" in str(call["outcome"]["output"])
            assert "555-66-7777" not in str(call["outcome"]["output"])
        finally:
            disable_crewai_auditing()
            BaseTool._run = original


class TestFailureBehaviour:
    def test_tool_exception_re_raised_and_recorded(self):
        """Install a failing implementation as the pristine ``BaseTool._run``,
        then verify the patched wrapper records a failure event AND
        re-raises the original exception."""
        from crewai.tools import BaseTool

        def failing_run(self, *args, **kwargs):
            raise RuntimeError("kaboom")

        original = BaseTool._run
        BaseTool._run = failing_run
        try:
            client = MagicMock()
            enable_crewai_auditing(client)

            Tool = _fresh_tool_subclass(name="failing_tool")
            tool = Tool()
            with pytest.raises(RuntimeError, match="kaboom"):
                tool._run()

            client.record_action.assert_called_once()
            call = client.record_action.call_args[1]
            assert call["result"] == "failure"
            assert call["error_message"] == "kaboom"
            assert call["framework"] == "crewai"
        finally:
            disable_crewai_auditing()
            BaseTool._run = original


class TestRedactorWiring:
    def test_custom_redactor_used(self):
        client = MagicMock()
        custom = Redactor(replacement="[XXX]")
        enable_crewai_auditing(client, redactor=custom)

        Tool = _fresh_tool_subclass()
        tool = Tool()
        tool._run("Patient SSN 123-45-6789")

        call = client.record_action.call_args[1]
        assert "[XXX:ssn]" in str(call["input_data"]["args"])

    def test_default_redactor_used_when_not_provided(self):
        from vera.integrations import crewai as crewai_mod
        client = MagicMock()
        enable_crewai_auditing(client)

        from vera.decorator import get_default_redactor
        assert crewai_mod._local.redactor is get_default_redactor()

    def test_re_enable_swaps_redactor_without_double_wrap(self):
        from vera.integrations import crewai as crewai_mod
        from crewai.tools import BaseTool

        client = MagicMock()
        first_redactor = Redactor(replacement="[A]")
        enable_crewai_auditing(client, redactor=first_redactor)
        first_patch = BaseTool._run
        assert crewai_mod._local.redactor is first_redactor

        second_redactor = Redactor(replacement="[B]")
        enable_crewai_auditing(client, redactor=second_redactor)
        # Same patched function (no double-wrap)…
        assert BaseTool._run is first_patch
        # …but redactor reference updated.
        assert crewai_mod._local.redactor is second_redactor


class TestNoClientFallthrough:
    def test_no_client_local_falls_through_to_original(self):
        """If somehow ``_local.client`` is unset on this thread, the
        patched function must still call the original ``_run``."""
        from vera.integrations import crewai as crewai_mod

        # Enable, then clear the thread-local client to simulate a thread
        # that never called enable_crewai_auditing.
        client = MagicMock()
        enable_crewai_auditing(client)
        crewai_mod._local.client = None

        Tool = _fresh_tool_subclass()
        tool = Tool()
        result = tool._run("hello")

        # Original ran, but no audit event recorded.
        assert "ran with" in result
        client.record_action.assert_not_called()
