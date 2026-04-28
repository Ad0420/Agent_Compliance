"""PII / secret redaction for the Vera SDK.

The :class:`Redactor` is used by the ``@audit`` and ``@async_audit``
decorators to scrub function arguments, return values, and tracebacks
before they are written to the audit trail.

Design goals:
- Stdlib-only (``re``, ``typing``, ``logging``).
- Fail open: redaction must never raise. On any internal exception we
  log a warning and return the original value coerced to ``str``.
- Greppable: every default pattern is named so audit logs stay easy to
  search after redaction.
- Configurable per-call: callers can pass ``patterns``, ``block_keys``,
  a ``custom_serializer``, etc. Defaults are sensible for fintech /
  medtech workloads (SSN, credit card with Luhn, email, phone, AWS
  keys, JWTs, hex secrets, bearer tokens).

Note: the redactor is intentionally only wired into the decorators.
Direct callers of ``client.record_action()`` are responsible for their
own redaction (this is documented in the SDK README).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

def _default_patterns() -> list[tuple[str, re.Pattern]]:
    """Return a fresh list of (name, compiled_pattern) pairs.

    Names are exposed so log output is greppable — e.g. a redacted SSN
    appears as ``[REDACTED:ssn]``.
    """
    return [
        ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        # Credit card: 13–19 digits, optionally separated by spaces or dashes.
        # We confirm with a Luhn check inside ``_apply_patterns`` so we don't
        # false-positive on order numbers, tracking codes, etc.
        ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
        ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
        (
            "phone_us",
            re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        ),
        ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
        (
            "jwt",
            re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        ),
        # Aggressive: catches API keys, hashes, anything 32+ hex chars.
        ("hex_secret", re.compile(r"\b[a-fA-F0-9]{32,}\b")),
        (
            "bearer_token",
            re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
        ),
    ]


def _default_block_keys() -> set[str]:
    return {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "token",
        "ssn",
        "social_security",
        "credit_card",
        "card_number",
        "cvv",
        "pin",
        "private_key",
        "authorization",
    }


# ---------------------------------------------------------------------------
# Luhn check (used to confirm credit-card matches)
# ---------------------------------------------------------------------------

def _luhn_valid(candidate: str) -> bool:
    """Return True if the digits in ``candidate`` pass the Luhn checksum."""
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    # Iterate from rightmost; double every second digit.
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------------

class Redactor:
    """Scrub PII and secrets out of arbitrary Python values.

    Public methods:
        - :meth:`serialize` — turn any value into a redacted string.
        - :meth:`serialize_args` — convert ``(args, kwargs)`` into the
          ``{"args": [...], "kwargs": {...}}`` shape expected by
          ``input_data``.

    Behaviour rules (see module docstring for rationale):

    1. ``serialize(value)`` routes by type. ``dict``/``list``/``tuple``
       recurse. ``str`` runs through the regex pass. Primitives use
       ``str(value)``. Anything else falls back to ``repr(value)`` and
       is then run through the regex pass.
    2. After redaction, any string longer than ``max_length`` is
       truncated with the ``...[truncated]`` suffix (matching the
       existing integration helpers).
    3. ``serialize_args`` honours ``block_keys``: if a *kwarg* key
       matches case-insensitively, the whole value is replaced with
       ``replacement`` regardless of pattern matches.
    4. Redaction never raises. Any internal exception is logged and we
       fall back to ``str(value)`` — this is auditing infrastructure;
       failing closed (dropping audit records) is worse than logging a
       value verbatim.
    """

    def __init__(
        self,
        patterns: list[tuple[str, re.Pattern]] | None = None,
        block_keys: set[str] | None = None,
        max_length: int = 10_000,
        replacement: str = "[REDACTED]",
        custom_serializer: Callable[[Any], str] | None = None,
    ) -> None:
        self.patterns = patterns if patterns is not None else _default_patterns()
        self.block_keys = {
            k.lower() for k in (block_keys if block_keys is not None else _default_block_keys())
        }
        self.max_length = max_length
        self.replacement = replacement
        self.custom_serializer = custom_serializer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def serialize(self, value: Any) -> Any:
        """Return a redacted representation of ``value``.

        For containers the return value preserves shape (dict stays a
        dict, list stays a list) so the audit DB can still index nested
        fields. Leaves are always strings.
        """
        # Custom hook: short-circuit if the user-provided serializer
        # returns something. Returning ``None`` means "fall through".
        if self.custom_serializer is not None:
            try:
                hook = self.custom_serializer(value)
            except Exception:  # noqa: BLE001 — fail open
                logger.warning(
                    "vera.redaction: custom_serializer raised; falling through",
                    exc_info=True,
                )
                hook = None
            if hook is not None:
                return self._truncate(self._apply_patterns(str(hook)))

        # Containers — recurse.
        if isinstance(value, dict):
            return {k: self._serialize_value_with_key(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.serialize(v) for v in value]
        if isinstance(value, tuple):
            # Preserve tuple-ness so callers that round-trip through JSON
            # can distinguish if they care; most won't.
            return tuple(self.serialize(v) for v in value)

        # Strings — regex pass.
        if isinstance(value, str):
            return self._truncate(self._apply_patterns(value))

        # Primitives — coerce and pattern-pass (numbers can still embed
        # things like SSNs in ``str(value)`` but it's cheap to check).
        if isinstance(value, (int, float, bool)) or value is None:
            return self._truncate(self._apply_patterns(str(value)))

        # Anything else: try repr, fall back to str on failure.
        try:
            text = repr(value)
        except Exception:  # noqa: BLE001 — fail open
            try:
                text = str(value)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "vera.redaction: could not stringify value of type %s",
                    type(value).__name__,
                )
                return self.replacement
        return self._truncate(self._apply_patterns(text))

    def serialize_args(self, args: tuple, kwargs: dict) -> dict:
        """Return ``{"args": [...], "kwargs": {...}}`` matching the
        existing ``input_data`` shape used by the decorators."""
        try:
            serialized_args = [self.serialize(a) for a in args]
        except Exception:  # noqa: BLE001 — fail open
            logger.warning(
                "vera.redaction: failed to serialize positional args",
                exc_info=True,
            )
            serialized_args = [self._safe_str(a) for a in args]

        serialized_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            try:
                if isinstance(k, str) and k.lower() in self.block_keys:
                    serialized_kwargs[k] = self.replacement
                else:
                    serialized_kwargs[k] = self.serialize(v)
            except Exception:  # noqa: BLE001 — fail open
                logger.warning(
                    "vera.redaction: failed to serialize kwarg %r", k, exc_info=True
                )
                serialized_kwargs[k] = self._safe_str(v)

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _serialize_value_with_key(self, key: Any, value: Any) -> Any:
        """Apply ``block_keys`` to nested dict entries too."""
        if isinstance(key, str) and key.lower() in self.block_keys:
            return self.replacement
        return self.serialize(value)

    def _apply_patterns(self, text: str) -> str:
        """Run every default pattern against ``text``.

        Wrapped in a broad try/except so a pathological regex (or input)
        can't take the audit pipeline down with it.
        """
        if not text:
            return text
        try:
            for name, pattern in self.patterns:
                if name == "credit_card":
                    text = pattern.sub(
                        lambda m, n=name: (
                            f"{self.replacement[:-1]}:{n}]"
                            if _luhn_valid(m.group(0))
                            else m.group(0)
                        ),
                        text,
                    )
                else:
                    text = pattern.sub(
                        f"{self.replacement[:-1]}:{name}]", text
                    )
            return text
        except Exception:  # noqa: BLE001 — fail open
            logger.warning(
                "vera.redaction: pattern application failed; returning raw value",
                exc_info=True,
            )
            return text

    def _truncate(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        if len(text) > self.max_length:
            return text[: self.max_length] + "...[truncated]"
        return text

    @staticmethod
    def _safe_str(value: Any) -> str:
        try:
            return str(value)
        except Exception:  # noqa: BLE001
            return "<unstringifiable>"


__all__ = ["Redactor"]
