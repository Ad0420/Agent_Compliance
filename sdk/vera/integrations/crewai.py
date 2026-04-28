"""CrewAI integration — monkey-patches BaseTool._run to audit all tool calls.

All captured args/kwargs/results are passed through a :class:`Redactor`
so PII / secrets do not leak into the audit trail. Pass ``redactor=`` to
override the default.

Usage:
    from vera.integrations.crewai import enable_crewai_auditing
    enable_crewai_auditing(client=ledger_client)
"""

import logging
import threading
import time

from vera.redaction import Redactor

logger = logging.getLogger("vera.integrations.crewai")

# Thread-local storage for per-thread client / redactor references
_local = threading.local()
_original_run = None
_patched = False


def enable_crewai_auditing(client, redactor: Redactor | None = None):
    """Monkey-patch ``crewai.tools.BaseTool._run`` to record all tool calls.

    Idempotent — calling multiple times updates the client / redactor
    without double-wrapping.

    Args:
        client: VeraClient instance used for recording.
        redactor: Optional :class:`Redactor` used to scrub args/kwargs
            and results. Falls back to
            :func:`vera.decorator.get_default_redactor`.
    """
    global _original_run, _patched

    try:
        from crewai.tools import BaseTool
    except ImportError:
        raise ImportError(
            "crewai is required for CrewAI integration. "
            "Install it with: pip install vera-sdk[crewai]"
        )

    _local.client = client
    if redactor is not None:
        _local.redactor = redactor
    else:
        from vera.decorator import get_default_redactor
        _local.redactor = get_default_redactor()

    if _patched:
        logger.info("CrewAI auditing already enabled — updated client/redactor reference")
        return

    _original_run = BaseTool._run

    def _audited_run(self, *args, **kwargs):
        ledger_client = getattr(_local, "client", None)
        if ledger_client is None:
            return _original_run(self, *args, **kwargs)

        redactor = getattr(_local, "redactor", None)
        # Defensive: another thread might call into the patched _run before
        # `_local.redactor` is initialised on that thread.
        if redactor is None:
            from vera.decorator import get_default_redactor
            redactor = get_default_redactor()

        tool_name = getattr(self, "name", self.__class__.__name__)
        tool_description = getattr(self, "description", "")

        input_data = {
            "tool_name": tool_name,
            "tool_description": redactor.serialize(tool_description) if tool_description else "",
            "args": [redactor.serialize(a) for a in args],
            "kwargs": {k: redactor.serialize(v) for k, v in kwargs.items()},
        }

        start = time.perf_counter()
        try:
            result = _original_run(self, *args, **kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            try:
                ledger_client.record_action(
                    action_name=tool_name,
                    action_type="tool_call",
                    result="success",
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    outcome={"output": redactor.serialize(result)},
                    framework="crewai",
                )
            except Exception:
                logger.warning("Failed to record audit event for CrewAI tool call", exc_info=True)

            return result

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            try:
                ledger_client.record_action(
                    action_name=tool_name,
                    action_type="tool_call",
                    result="failure",
                    duration_ms=elapsed_ms,
                    input_data=input_data,
                    error_message=str(exc),
                    framework="crewai",
                )
            except Exception:
                logger.warning("Failed to record audit event for CrewAI tool error", exc_info=True)
            raise

    BaseTool._run = _audited_run
    _patched = True


def disable_crewai_auditing():
    """Restore the original BaseTool._run method and clear thread-local state."""
    global _original_run, _patched

    if not _patched or _original_run is None:
        return

    try:
        from crewai.tools import BaseTool
        BaseTool._run = _original_run
    except ImportError:
        pass

    _original_run = None
    _patched = False
    _local.client = None
    _local.redactor = None
