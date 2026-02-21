import functools
import time
import traceback


# Module-level client reference — set by the user
_default_client = None


def set_default_client(client):
    """Set the default ActionLedgerClient used by the @audit decorator."""
    global _default_client
    _default_client = client


def audit(action_name: str = "", action_type: str = "function_call", client=None):
    """
    Decorator that records function calls as action records.

    Usage:
        @audit(action_name="process_data")
        def process_data(x, y):
            return x + y

    The decorator captures:
    - Function inputs as input_data
    - Return value in outcome
    - Timing as duration_ms
    - Exceptions as result="failure"
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            effective_client = client or _default_client
            if effective_client is None:
                # No client configured — just run the function
                return func(*args, **kwargs)

            resolved_name = action_name or func.__name__

            # Capture inputs
            input_data = {"args": [repr(a) for a in args], "kwargs": {k: repr(v) for k, v in kwargs.items()}}

            start = time.perf_counter()
            try:
                result_value = func(*args, **kwargs)
                elapsed_ms = int((time.perf_counter() - start) * 1000)

                effective_client.record_action(
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

                effective_client.record_action(
                    action_name=resolved_name,
                    action_type=action_type,
                    result="failure",
                    input_data=input_data,
                    error_message=str(exc),
                    outcome={"traceback": traceback.format_exc()},
                    duration_ms=elapsed_ms,
                )
                raise

        return wrapper
    return decorator
