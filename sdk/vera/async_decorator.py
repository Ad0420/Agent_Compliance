"""Async version of the @audit decorator.

Works with both sync and async functions. Uses the background queue
by default so audit calls don't add latency to the wrapped function.
"""

import asyncio
import functools
import time
import traceback

_default_async_client = None


def set_default_async_client(client):
    """Set the default AsyncVeraClient used by the @async_audit decorator."""
    global _default_async_client
    _default_async_client = client


def async_audit(action_name: str = "", action_type: str = "function_call", client=None, blocking: bool = False):
    """Decorator that records function calls as action records (async-aware).

    Works with both sync and async functions.

    Args:
        action_name: Name for the action record. Defaults to function name.
        action_type: Type of action. Defaults to "function_call".
        client: AsyncVeraClient instance. Falls back to default.
        blocking: If True, waits for the API call. If False (default), uses
                  the background queue for zero-latency auditing.
    """

    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                effective_client = client or _default_async_client
                if effective_client is None:
                    return await func(*args, **kwargs)

                resolved_name = action_name or func.__name__
                input_data = {
                    "args": [repr(a) for a in args],
                    "kwargs": {k: repr(v) for k, v in kwargs.items()},
                }

                start = time.perf_counter()
                try:
                    result_value = await func(*args, **kwargs)
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    record_kwargs = dict(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="success",
                        input_data=input_data,
                        outcome={"return_value": repr(result_value)},
                        duration_ms=elapsed_ms,
                    )

                    if blocking:
                        await effective_client.record_action(**record_kwargs)
                    else:
                        effective_client.enqueue_action(**record_kwargs)

                    return result_value

                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    record_kwargs = dict(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="failure",
                        input_data=input_data,
                        error_message=str(exc),
                        outcome={"traceback": traceback.format_exc()},
                        duration_ms=elapsed_ms,
                    )

                    if blocking:
                        await effective_client.record_action(**record_kwargs)
                    else:
                        effective_client.enqueue_action(**record_kwargs)

                    raise

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                effective_client = client or _default_async_client
                if effective_client is None:
                    return func(*args, **kwargs)

                resolved_name = action_name or func.__name__
                input_data = {
                    "args": [repr(a) for a in args],
                    "kwargs": {k: repr(v) for k, v in kwargs.items()},
                }

                start = time.perf_counter()
                try:
                    result_value = func(*args, **kwargs)
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    effective_client.enqueue_action(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="success",
                        input_data=input_data,
                        outcome={"return_value": repr(result_value)},
                        duration_ms=elapsed_ms,
                    )
                    return result_value

                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)

                    effective_client.enqueue_action(
                        action_name=resolved_name,
                        action_type=action_type,
                        result="failure",
                        input_data=input_data,
                        error_message=str(exc),
                        outcome={"traceback": traceback.format_exc()},
                        duration_ms=elapsed_ms,
                    )
                    raise

            return sync_wrapper
    return decorator
