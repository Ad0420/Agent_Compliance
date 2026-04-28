import functools
import time
import traceback

from .redaction import Redactor


# Module-level client reference — set by the user
_default_client = None

# Module-level redactor — used unless the caller passes ``redactor=`` to
# ``@audit``. A fresh ``Redactor()`` is permissive enough that plain
# strings/numbers without secrets round-trip unchanged, so existing
# callers see no behavioural change.
_default_redactor = Redactor()


def set_default_client(client):
    """Set the default VeraClient used by the @audit decorator."""
    global _default_client
    _default_client = client


def set_default_redactor(redactor: Redactor) -> None:
    """Replace the module-level default :class:`Redactor`.

    Useful for app-wide policy (e.g. tenant-specific block_keys).
    """
    global _default_redactor
    _default_redactor = redactor


def get_default_redactor() -> Redactor:
    """Return the module-level default :class:`Redactor`."""
    return _default_redactor


def audit(
    action_name: str = "",
    action_type: str = "function_call",
    client=None,
    redactor: Redactor | None = None,
):
    """
    Decorator that records function calls as action records.

    Usage:
        @audit(action_name="process_data")
        def process_data(x, y):
            return x + y

    The decorator captures:
    - Function inputs as input_data (redacted via ``redactor``)
    - Return value in outcome (redacted)
    - Timing as duration_ms
    - Exceptions as result="failure" (traceback redacted)

    Args:
        action_name: Name for the action record. Defaults to function name.
        action_type: Type of action. Defaults to "function_call".
        client: VeraClient instance. Falls back to the module default.
        redactor: :class:`Redactor` used to scrub input_data, outcome,
            and tracebacks. Falls back to the module default. Pass
            ``Redactor(...)`` to customise per-decorator.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            effective_client = client or _default_client
            if effective_client is None:
                # No client configured — just run the function
                return func(*args, **kwargs)

            effective_redactor = redactor or _default_redactor
            resolved_name = action_name or func.__name__

            # Capture inputs (redacted)
            input_data = effective_redactor.serialize_args(args, kwargs)

            start = time.perf_counter()
            try:
                result_value = func(*args, **kwargs)
                elapsed_ms = int((time.perf_counter() - start) * 1000)

                effective_client.record_action(
                    action_name=resolved_name,
                    action_type=action_type,
                    result="success",
                    input_data=input_data,
                    outcome={"return_value": effective_redactor.serialize(result_value)},
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
                    outcome={
                        "traceback": effective_redactor.serialize(traceback.format_exc())
                    },
                    duration_ms=elapsed_ms,
                )
                raise

        return wrapper
    return decorator
