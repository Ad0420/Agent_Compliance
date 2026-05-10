import functools
import logging
import time
import traceback

from .redaction import Redactor


logger = logging.getLogger(__name__)


# Module-level client reference — set by the user
_default_client = None

# Module-level redactor — used unless the caller passes ``redactor=`` to
# ``@audit``. A fresh ``Redactor()`` is permissive enough that plain
# strings/numbers without secrets round-trip unchanged, so existing
# callers see no behavioural change.
_default_redactor = Redactor()

# Tracks whether we have already emitted the "no client configured" WARN
# for this process. We only want one warning per process so production
# logs don't get spammed once per audited call.
_empty_client_warned = False

_EMPTY_CLIENT_WARNING = (
    "vera.audit: @audit decorator invoked but no Vera client is configured. "
    "Audit records are NOT being captured. Call vera.set_default_client() "
    "or pass client=."
)


def _warn_empty_client_once() -> None:
    """Emit a single WARNING per process when @audit runs with no client."""
    global _empty_client_warned
    if not _empty_client_warned:
        _empty_client_warned = True
        logger.warning(_EMPTY_CLIENT_WARNING)


def _reset_empty_client_warning() -> None:
    """Reset the once-per-process WARN flag. Intended for tests."""
    global _empty_client_warned
    _empty_client_warned = False


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
                # No client configured — warn once, then run the function
                # without any audit record. Customer code MUST keep working
                # in this state so missing config doesn't break their app.
                _warn_empty_client_once()
                return func(*args, **kwargs)

            effective_redactor = redactor or _default_redactor
            resolved_name = action_name or func.__name__

            # Capture inputs (redacted)
            input_data = effective_redactor.serialize_args(args, kwargs)

            start = time.perf_counter()
            try:
                result_value = func(*args, **kwargs)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - start) * 1000)

                # Vera-side failures (e.g. network errors talking to the
                # ledger) must NEVER mask the customer's exception. Swallow
                # any exception from enqueue_action and log at WARNING.
                # As of v0.4 we use enqueue_action() so the decorator never
                # adds blocking latency to customer code; failures show up
                # asynchronously via the worker thread's classification.
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

        return wrapper
    return decorator
