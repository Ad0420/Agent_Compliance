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

Schema-driven mode (A6 hardening)
---------------------------------
Regex-only redaction is "false safety" for medtech / PHI workloads —
patient names and free-text clinical notes leak no matter how many
patterns you stack. The :class:`Schema` model lets a customer declare
which fields contain PHI and how each should be handled. Unmapped
fields are denied (replaced) by default, so adding a new field to your
function signature can never accidentally leak PHI without an explicit
schema update. Defense-in-depth: the existing regex pass and
``block_keys`` set both still apply on top of schema rules.

Example::

    from vera.redaction import Redactor, Schema, FieldRule, FieldPolicy

    schema = Schema(fields={
        "patient_id":   FieldRule(FieldPolicy.PASSTHROUGH),  # opaque ID
        "patient_name": FieldRule(FieldPolicy.REDACT),
        "mrn":          FieldRule(FieldPolicy.PATTERN, pattern_name="mrn"),
        "notes":        FieldRule(FieldPolicy.REDACT),       # free-text PHI
    })
    redactor = Redactor(schema=schema)

    @audit(redactor=redactor)
    def process_patient(patient_id: str, mrn: str, notes: str): ...

Note: the redactor is intentionally only wired into the decorators.
Direct callers of ``client.record_action()`` are responsible for their
own redaction (this is documented in the SDK README).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

def _default_patterns() -> list[tuple[str, re.Pattern]]:
    """Return a fresh list of (name, compiled_pattern) pairs.

    Names are exposed so log output is greppable — e.g. a redacted SSN
    appears as ``[REDACTED:ssn]``.

    Medtech-friendly defaults are included (``mrn``, ``dob``, ``ipv4``,
    ``ipv6``). ICD-10 is intentionally NOT a default because the
    pattern (``[A-Z]\\d{2}(?:\\.\\d{1,4})?``) collides with normal
    English text — customers opt in via a schema with
    ``pattern_name="icd10"``.
    """
    base = [
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
    # Medtech / network additions for the *default* regex pass. ICD-10 is
    # explicitly excluded — its pattern (``[A-Z]\d{2}(?:\.\d{1,4})?``)
    # collides with normal English text. Customers opt in via a Schema
    # with ``pattern_name="icd10"`` (still resolvable through
    # :func:`_medtech_patterns`).
    base.extend(
        (name, pat) for name, pat in _medtech_patterns() if name != "icd10"
    )
    return base


def _medtech_patterns() -> list[tuple[str, re.Pattern]]:
    """Extra named patterns useful for medtech and network metadata.

    ``icd10`` is intentionally returned here for use via
    :class:`Schema` ``PATTERN`` rules but is NOT included in the
    default-pass list (see :func:`_default_patterns`) — the pattern
    matches too much normal English text to be a safe default.
    """
    return [
        # MRN: "MRN-12345678", "MRN_12345678", "MRN12345678".
        ("mrn", re.compile(r"\bMRN[-_]?\d{4,12}\b", re.IGNORECASE)),
        # DOB: MM/DD/YYYY, M/D/YYYY, YYYY-MM-DD, DD-Mon-YYYY.
        (
            "dob",
            re.compile(
                r"\b(?:"
                r"\d{1,2}/\d{1,2}/\d{2,4}"           # MM/DD/YYYY
                r"|\d{4}-\d{2}-\d{2}"                # YYYY-MM-DD (ISO)
                r"|\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}"  # DD-Mon-YYYY
                r")\b",
                re.IGNORECASE,
            ),
        ),
        # IPv4 dotted quad — bounded so we don't match e.g. version strings.
        (
            "ipv4",
            re.compile(
                r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
                r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b"
            ),
        ),
        # IPv6: simplified — accepts 8-group full form and ``::`` shorthand.
        (
            "ipv6",
            re.compile(
                r"(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"
                r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"
                r"|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"
                r"|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}"
                r"|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}"
                r"|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}"
                r"|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}"
                r"|[0-9a-fA-F]{1,4}:(?:(?::[0-9a-fA-F]{1,4}){1,6}))"
            ),
        ),
        # ICD-10: "J45.909", "E11", "Z99.89" — opt-in via Schema PATTERN rule.
        ("icd10", re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,4})?\b")),
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
# Schema model (A6: schema-driven redaction)
# ---------------------------------------------------------------------------

class FieldPolicy(str, Enum):
    """How a field should be handled by the schema-driven Redactor.

    - ``PASSTHROUGH``: safe to send as-is — opaque IDs, non-PHI metadata.
      The regex pass still runs on the value as defense-in-depth.
    - ``REDACT``: always replace value with ``[REDACTED:fieldname]``.
      Use this for free-text PHI (clinical notes, names) where regex
      cannot reliably scrub.
    - ``PATTERN``: apply a named regex pattern; the matching substring
      is replaced and the rest is left intact (and still runs through
      the default regex pass).
    """

    PASSTHROUGH = "passthrough"
    REDACT = "redact"
    PATTERN = "pattern"


@dataclass
class FieldRule:
    """Rule for a single named field in the redaction schema.

    Attributes:
        policy: How the field should be handled.
        pattern_name: Required if ``policy == FieldPolicy.PATTERN``. Must
            be a name registered in the redactor's ``patterns`` list (or
            the medtech extras such as ``"mrn"``, ``"dob"``,
            ``"icd10"``). If unknown at apply time the redactor
            fails closed (REDACTs the value) and logs a WARN.
        description: Human-readable docs for the rule. Helps audit
            reviewers understand why a field is tagged a particular way.
    """

    policy: FieldPolicy
    pattern_name: str | None = None
    description: str = ""


@dataclass
class Schema:
    """Customer-declared field schema for schema-driven redaction.

    Fields not present in :attr:`fields` are handled according to
    :attr:`unmapped_policy`. Default is ``REDACT`` — any unmapped field
    is fully replaced with ``[REDACTED:UNMAPPED]``. This is the
    deny-by-default safety property: no PHI sneaks through unless you
    explicitly mapped it.

    The escape hatch for backwards compat / gradual adoption is
    ``unmapped_policy=FieldPolicy.PASSTHROUGH`` — unmapped fields run
    the regex pass only.
    """

    fields: dict[str, FieldRule] = field(default_factory=dict)
    unmapped_policy: FieldPolicy = FieldPolicy.REDACT

    def rule_for(self, key: str) -> FieldRule:
        """Return the rule for ``key``, falling back to ``unmapped_policy``."""
        if key in self.fields:
            return self.fields[key]
        return FieldRule(
            policy=self.unmapped_policy,
            description="unmapped field — fallback policy",
        )


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
    5. Schema mode (when ``schema`` is non-None) layers on top: dict
       keys are first checked against ``block_keys`` (defense-in-depth
       — block_keys always wins), then routed by the schema's per-key
       :class:`FieldRule`. Unmapped keys fall back to
       ``schema.unmapped_policy`` (deny-by-default).

    Schema mode and the @audit decorator
    ------------------------------------
    The decorator passes ``{"args": [...], "kwargs": {...}}`` as
    ``input_data``. Customer function parameters land at *kwarg* keys,
    so the schema's keys should match the function's parameter names.

    Given ``def process_patient(patient_id: str, notes: str): ...``,
    declare::

        Schema(fields={
            "patient_id": FieldRule(FieldPolicy.PASSTHROUGH),
            "notes":      FieldRule(FieldPolicy.REDACT),
        })

    and the @audit decorator's ``input_data["kwargs"]`` will redact
    ``notes`` while passing ``patient_id`` through. Schema rule lookup
    on dicts at any nesting level uses the leaf key only — path-based
    rules are intentionally out of scope for this PR.
    """

    def __init__(
        self,
        patterns: list[tuple[str, re.Pattern]] | None = None,
        block_keys: set[str] | None = None,
        max_length: int = 10_000,
        replacement: str = "[REDACTED]",
        custom_serializer: Callable[[Any], str] | None = None,
        schema: Schema | None = None,
    ) -> None:
        self.patterns = patterns if patterns is not None else _default_patterns()
        self.block_keys = {
            k.lower() for k in (block_keys if block_keys is not None else _default_block_keys())
        }
        self.max_length = max_length
        self.replacement = replacement
        self.custom_serializer = custom_serializer
        self.schema = schema
        # Indexed view of patterns by name for O(1) PATTERN-rule lookup.
        # Built once at init; ``patterns`` is treated as immutable post-construct.
        self._patterns_by_name: dict[str, re.Pattern] = {
            name: pat for name, pat in self.patterns
        }
        # Also include medtech-only patterns (e.g. icd10) so PATTERN rules
        # can reference them even when they're not in the default pass.
        for name, pat in _medtech_patterns():
            self._patterns_by_name.setdefault(name, pat)

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
        existing ``input_data`` shape used by the decorators.

        When ``schema`` is set on the redactor, kwarg keys are matched
        against the schema's field names. ``block_keys`` is checked
        first as defense-in-depth: a key in ``block_keys`` is always
        replaced even if the schema says ``PASSTHROUGH``.
        """
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
                serialized_kwargs[k] = self._serialize_value_with_key(k, v)
            except Exception:  # noqa: BLE001 — fail open
                logger.warning(
                    "vera.redaction: failed to serialize kwarg %r", k, exc_info=True
                )
                serialized_kwargs[k] = self._safe_str(v)

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    # ------------------------------------------------------------------
    # Schema starter helpers
    # ------------------------------------------------------------------

    @classmethod
    def medtech_starter_schema(cls) -> Schema:
        """Return a starter :class:`Schema` for canonical patient encounters.

        The schema is a *starting point* — customers should review and
        customize for their domain. Tags reflect conservative defaults:

        - ``patient_id``: ``PASSTHROUGH`` (opaque internal ID; not PHI).
        - ``patient_name``, ``first_name``, ``last_name``: ``REDACT``
          (cannot be safely scrubbed by regex).
        - ``dob`` / ``date_of_birth``: ``PATTERN`` with ``"dob"`` —
          accepts and masks the date itself.
        - ``mrn`` / ``medical_record_number``: ``PATTERN`` with ``"mrn"``.
        - ``notes`` / ``clinical_notes``: ``REDACT`` (free-text PHI).
        - ``icd10_code`` / ``diagnosis_code``: ``REDACT``. Use
          ``FieldPolicy.PATTERN`` with ``pattern_name="icd10"`` instead
          if you want to keep the surrounding text and mask only the
          code itself.
        - ``street_address``, ``address``, ``city``, ``zip``: ``REDACT``.
        - ``email``, ``phone``: ``REDACT`` (regex pass also catches them).
        - ``ip_address``: ``PATTERN`` with ``"ipv4"``.

        This classmethod returns a :class:`Schema` (not a
        :class:`Redactor`) — the customer flow is::

            redactor = Redactor(schema=Redactor.medtech_starter_schema())
        """
        return Schema(
            fields={
                # Opaque IDs (not PHI).
                "patient_id": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description="Opaque internal patient ID — not PHI.",
                ),
                "encounter_id": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description="Opaque encounter / visit ID — not PHI.",
                ),
                # Names — free text, cannot be safely regex-scrubbed.
                "patient_name": FieldRule(
                    FieldPolicy.REDACT,
                    description="Patient full name — PHI under HIPAA Safe Harbor.",
                ),
                "first_name": FieldRule(
                    FieldPolicy.REDACT,
                    description="Patient given name — PHI.",
                ),
                "last_name": FieldRule(
                    FieldPolicy.REDACT,
                    description="Patient family name — PHI.",
                ),
                # Dates of birth.
                "dob": FieldRule(
                    FieldPolicy.PATTERN,
                    pattern_name="dob",
                    description="Date of birth — masked via dob pattern.",
                ),
                "date_of_birth": FieldRule(
                    FieldPolicy.PATTERN,
                    pattern_name="dob",
                    description="Date of birth — masked via dob pattern.",
                ),
                # Medical record numbers.
                "mrn": FieldRule(
                    FieldPolicy.PATTERN,
                    pattern_name="mrn",
                    description="Medical record number — masked via mrn pattern.",
                ),
                "medical_record_number": FieldRule(
                    FieldPolicy.PATTERN,
                    pattern_name="mrn",
                    description="Medical record number — masked via mrn pattern.",
                ),
                # Free-text clinical content.
                "notes": FieldRule(
                    FieldPolicy.REDACT,
                    description=(
                        "Free-text clinical notes — REDACTed wholesale. "
                        "Regex cannot safely scrub names from prose."
                    ),
                ),
                "clinical_notes": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text clinical notes — REDACTed wholesale.",
                ),
                "chief_complaint": FieldRule(
                    FieldPolicy.REDACT,
                    description="Chief complaint free text — REDACTed wholesale.",
                ),
                # Diagnosis codes.
                "icd10_code": FieldRule(
                    FieldPolicy.REDACT,
                    description=(
                        "ICD-10 diagnosis code. REDACTed by default; "
                        "use FieldPolicy.PATTERN with pattern_name='icd10' "
                        "to mask only the code while keeping context."
                    ),
                ),
                "diagnosis_code": FieldRule(
                    FieldPolicy.REDACT,
                    description="Diagnosis code — REDACTed by default.",
                ),
                # Addresses.
                "street_address": FieldRule(
                    FieldPolicy.REDACT,
                    description="Street address — PHI under HIPAA Safe Harbor.",
                ),
                "address": FieldRule(
                    FieldPolicy.REDACT,
                    description="Postal address — PHI.",
                ),
                "city": FieldRule(
                    FieldPolicy.REDACT,
                    description="City — PHI when paired with other identifiers.",
                ),
                "zip": FieldRule(
                    FieldPolicy.REDACT,
                    description="ZIP / postal code — PHI under HIPAA Safe Harbor.",
                ),
                "zip_code": FieldRule(
                    FieldPolicy.REDACT,
                    description="ZIP / postal code — PHI.",
                ),
                # Contact info.
                "email": FieldRule(
                    FieldPolicy.REDACT,
                    description="Email address — PHI in a clinical context.",
                ),
                "phone": FieldRule(
                    FieldPolicy.REDACT,
                    description="Phone number — PHI in a clinical context.",
                ),
                # Network metadata.
                "ip_address": FieldRule(
                    FieldPolicy.PATTERN,
                    pattern_name="ipv4",
                    description="Client IPv4 address — masked via ipv4 pattern.",
                ),
            },
            unmapped_policy=FieldPolicy.REDACT,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _serialize_value_with_key(self, key: Any, value: Any) -> Any:
        """Apply ``block_keys`` and (optionally) the schema rule for ``key``.

        Order of precedence:
            1. ``block_keys`` (defense-in-depth — always wins).
            2. Schema rule, if a schema is configured.
            3. Default behaviour — recursive :meth:`serialize`.
        """
        # 1. block_keys: defense-in-depth. A key in block_keys is replaced
        #    wholesale even if the schema says PASSTHROUGH.
        if isinstance(key, str) and key.lower() in self.block_keys:
            return self.replacement

        # 2. Schema mode.
        if self.schema is not None and isinstance(key, str):
            return self._apply_schema_rule(key, value)

        # 3. Default: recurse.
        return self.serialize(value)

    def _apply_schema_rule(self, key: str, value: Any) -> Any:
        """Apply the schema rule for ``key`` to ``value``.

        See :class:`FieldPolicy` for the per-policy semantics. Failure
        modes:
            - PATTERN with an unknown ``pattern_name`` → fail closed
              (REDACT) and log a WARN. PHI doesn't leak when a customer
              fat-fingers a pattern name.
            - PATTERN where the pattern doesn't match → the value runs
              through the default regex pass via :meth:`serialize` —
              defense-in-depth.
        """
        rule = self.schema.rule_for(key)
        policy = rule.policy

        if policy == FieldPolicy.REDACT:
            # Tagged replacement so audit reviewers can see *which* field
            # was redacted by schema policy. Falls back to bare
            # ``self.replacement`` if the user has customised the format.
            return self._tagged_replacement(key)

        if policy == FieldPolicy.PATTERN:
            return self._apply_pattern_rule(key, value, rule)

        # PASSTHROUGH — recurse via serialize() so the regex pass still
        # runs as defense-in-depth.
        return self.serialize(value)

    def _apply_pattern_rule(self, key: str, value: Any, rule: FieldRule) -> Any:
        """Handle ``FieldPolicy.PATTERN`` for a single key.

        Looks up ``rule.pattern_name`` in the redactor's pattern index.
        Unknown name → fail closed (REDACT) + WARN. Known name → apply
        the named pattern, then fall through to the default regex pass
        for defense-in-depth.
        """
        name = rule.pattern_name
        if not name or name not in self._patterns_by_name:
            logger.warning(
                "vera.redaction: schema field %r references unknown pattern %r — "
                "failing closed (REDACT)",
                key,
                name,
            )
            return self._tagged_replacement(key)

        # Coerce the value to a string for pattern matching. Non-string
        # values still get the regex pass applied via _apply_patterns()
        # at the end of serialize().
        if not isinstance(value, str):
            return self.serialize(value)

        pattern = self._patterns_by_name[name]
        try:
            replaced = pattern.sub(f"{self.replacement[:-1]}:{name}]", value)
        except Exception:  # noqa: BLE001 — fail open
            logger.warning(
                "vera.redaction: pattern %r raised on field %r; falling through",
                name,
                key,
                exc_info=True,
            )
            replaced = value

        # Run the default pass on top — defense-in-depth.
        return self._truncate(self._apply_patterns(replaced))

    def _tagged_replacement(self, key: str) -> str:
        """Return ``[REDACTED:<key>]`` if ``replacement`` is the default,
        otherwise the raw replacement (so customer-overridden values are
        respected verbatim).
        """
        if self.replacement.startswith("[") and self.replacement.endswith("]"):
            return f"{self.replacement[:-1]}:{key}]"
        return self.replacement

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


__all__ = [
    "Redactor",
    "Schema",
    "FieldRule",
    "FieldPolicy",
]
