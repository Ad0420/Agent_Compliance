"""Internal helpers for emitting DeprecationWarning with consistent formatting."""

from __future__ import annotations

import warnings
from functools import wraps
from typing import Any, Callable


def deprecated(
    *,
    reason: str,
    removed_in: str,
    replacement: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for callables whose behavior is changing or being removed.

    Args:
        reason: short human description of the deprecation.
        removed_in: target version where the deprecated behavior will be
            removed (e.g. ``"0.5.0"``).
        replacement: optional pointer to the recommended alternative.

    The DeprecationWarning is emitted on every call. If you only want to warn
    once per call site, use :func:`deprecated_once`.
    """
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        msg = f"{fn.__qualname__} is deprecated: {reason}. Will be removed in v{removed_in}."
        if replacement:
            msg += f" Use {replacement} instead."

        @wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return fn(*args, **kwargs)

        return inner

    return wrap


_warned_once: set[str] = set()


def deprecated_once(key: str, message: str) -> None:
    """Emit a DeprecationWarning exactly once per process for the given key."""
    if key in _warned_once:
        return
    _warned_once.add(key)
    warnings.warn(message, DeprecationWarning, stacklevel=3)
