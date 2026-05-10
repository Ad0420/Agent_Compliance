"""Async version of the @audit decorator.

Works with both sync and async functions. Uses the background queue
by default so audit calls don't add latency to the wrapped function.
"""

import asyncio
import functools
import logging
import time
import traceback

from .redaction import Redactor


logger = logging.getLogger(__name__)

_default_async_client = None

# Module-level redactor — used unless the caller passes ``redactor=`` to
# ``@async_audit``. Mirrors the sync decorator.
_default_redactor = Redactor()

# Tracks whether we have already emitted the "no client configured" WARN
# for this process. Mirrors the sync decorator's behaviour — one WARN per
# process, never per call.
_empty_client_warned = False

_EMPTY_CLIENT_WARNING = (
    "vera.audit: @audit decorator invoked but no Vera client is configured. "
    "Audit records are NOT being captured. Call vera.set_default_client() "
    "or pass client=."
)


def _warn_empty_client_once() -> None:
    """Emit a single WARNING per process when @async_audit runs with no client."""
    global _empty_client_warned
    if not _empty_client_warned:
        _empty_client_warned = True
        logger.warning(_EMPTY_CLIENT_WARNING)


def _reset_empty_client_warning() -> None:
    """Reset the once-per-process WARN flag. Intended for tests."""
    global _empty_client_warned
    _empty_client_warned = False


def set_default_async_client(client):
    """Set the default AsyncVeraClient used by the @async_audit decorator."""
    global _default_async_client
    _default_async_client = client


def set_default_redactor(redactor: Redactor) -> None:
    """Replace the module-level default :class:`Redactor` for async audits."""
    global _default_redactor
    _default_redactor = redactor


def get_default_redactor() -> Redactor:
    """Return the module-level default :class:`Redactor` for async audits."""
    return _default_redactor


def async_audit(
    action_name: str = "",
    action_type: str = "function_call",
    client=None,
    blocking: bool = False,
    redactor: Redactor | None = None,
):
    """Decorator that records function calls as action records (async-aware).

    Works with both sync and async functions.

    Args:
        action_name: Name for the action record. Defaults to function name.
        action_type: Type of action. Defaults to "function_call".
        client: AsyncVeraClient instance. Falls back to default.
        blocking: If True, waits for the API call. If False (default), uses
                  the background queue for zero-latency auditing.
        redactor: :class:`Redactor` used to scrub input_data, outcome,
            and tracebacks. Falls back to the module default. Pass
            ``Redactor(...)`` to customise per-decorator.
    """

    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                effective_client = client or _default_async_client
                if effective_client is None:
                    _warn_empty_client_once()
                    return await func(*args, **kwargs)

                effective_redactor = redactor or _default_redactor
                resolved_name = action_name or func.__name__
                input_data = effective_redactor.serialize_args(args, kwargs)

                start = time.perf_counter()
                try:
                    result_value = await func(*args, **kwargs)
                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    record_kwargs = dict(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="failure",
                        input_data=input_data,
                        error_message=str(exc),
                        outcome={
                            "traceback": effective_redactor.serialize(traceback.format_exc())
                        },
                        duration_ms=elapsed_ms,
                    )

                    # Vera-side failures must NEVER mask the customer's
                    # exception. Swallow any exception from the audit
                    # call and log at WARNING.
                    try:
                        if blocking:
                            await effective_client.record_action(**record_kwargs)
                        else:
                            effective_client.enqueue_action(**record_kwargs)
                    except Exception as audit_exc:  # noqa: BLE001
                        logger.warning(
                            "vera.audit: failed to record failure for %s: %s",
                            resolved_name,
                            audit_exc,
                        )
                    raise

                elapsed_ms = int((time.perf_counter() - start) * 1000)

                record_kwargs = dict(
                    action_name=resolved_name,
                    action_type=action_type,
                    result="success",
                    input_data=input_data,
                    outcome={"return_value": effective_redactor.serialize(result_value)},
                    duration_ms=elapsed_ms,
                )

                try:
                    if blocking:
                        await effective_client.record_action(**record_kwargs)
                    else:
                        effective_client.enqueue_action(**record_kwargs)
                except Exception as audit_exc:  # noqa: BLE001
                    logger.warning(
                        "vera.audit: failed to record success for %s: %s",
                        resolved_name,
                        audit_exc,
                    )

                return result_value

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                effective_client = client or _default_async_client
                if effective_client is None:
                    _warn_empty_client_once()
                    return func(*args, **kwargs)

                effective_redactor = redactor or _default_redactor
                resolved_name = action_name or func.__name__
                input_data = effective_redactor.serialize_args(args, kwargs)

                start = time.perf_counter()
                try:
                    result_value = func(*args, **kwargs)
                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    try:
                        effective_client.enqueue_action(
                            action_name=resolved_name,
                            action_type=action_type,
                            result="failure",
                            input_data=input_data,
                            error_message=str(exc),
                            outcome={
                                "traceback": effective_redactor.serialize(traceback.format_exc())
                            },
                            duration_ms=elapsed_ms,
                        )
                    except Exception as audit_exc:  # noqa: BLE001
                        logger.warning(
                            "vera.audit: failed to record failure for %s: %s",
                            resolved_name,
                            audit_exc,
                        )
                    raise

                elapsed_ms = int((time.perf_counter() - start) * 1000)

                try:
                    effective_client.enqueue_action(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="success",
                        input_data=input_data,
                        outcome={"return_value": effective_redactor.serialize(result_value)},
                        duration_ms=elapsed_ms,
                    )
                except Exception as audit_exc:  # noqa: BLE001
                    logger.warning(
                        "vera.audit: failed to record success for %s: %s",
                        resolved_name,
                        audit_exc,
                    )
                return result_value

            return sync_wrapper
    return decorator
