"""CrewAI integration — monkey-patches BaseTool._run to audit all tool calls.

Usage:
    from actionledger.integrations.crewai import enable_crewai_auditing
    enable_crewai_auditing(client=ledger_client)
"""

import logging
import threading
import time

logger = logging.getLogger("actionledger.integrations.crewai")

# Thread-local storage for per-thread client references
_local = threading.local()
_original_run = None
_patched = False


def enable_crewai_auditing(client):
    """Monkey-patch crewai.tools.BaseTool._run to record all tool calls.

    Idempotent — calling multiple times updates the client without double-wrapping.

    Args:
        client: ActionLedgerClient instance used for recording.
    """
    global _original_run, _patched

    try:
        from crewai.tools import BaseTool
    except ImportError:
        raise ImportError(
            "crewai is required for CrewAI integration. "
            "Install it with: pip install actionledger[crewai]"
        )

    _local.client = client

    if _patched:
        logger.info("CrewAI auditing already enabled — updated client reference")
        return

    _original_run = BaseTool._run

    def _audited_run(self, *args, **kwargs):
        ledger_client = getattr(_local, "client", None)
        if ledger_client is None:
            return _original_run(self, *args, **kwargs)

        tool_name = getattr(self, "name", self.__class__.__name__)
        tool_description = getattr(self, "description", "")

        input_data = {
            "tool_name": tool_name,
            "tool_description": tool_description[:500] if tool_description else "",
            "args": [repr(a)[:1000] for a in args],
            "kwargs": {k: repr(v)[:1000] for k, v in kwargs.items()},
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
                    outcome={"output": repr(result)[:10000]},
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
    """Restore the original BaseTool._run method."""
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
