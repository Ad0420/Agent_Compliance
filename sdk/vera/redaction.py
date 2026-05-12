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

import functools
import logging
import re
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)
# Library logging hygiene: ensure a NullHandler is attached so the SDK does
# not emit "No handlers could be found" warnings when the customer's
# application has not configured logging. Idempotent — guards against
# duplicate handlers on re-import in test suites.
if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
    logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# BAA reminder (B3): one-shot INFO log on first Redactor.medtech() use.
# ---------------------------------------------------------------------------

_BAA_REMINDER_LOGGED = False


def _emit_baa_reminder() -> None:
    """Emit a single INFO log reminding customers to sign a BAA.

    Called by :meth:`Redactor.medtech`. Idempotent — subsequent calls do
    nothing. Tests can reset the flag via
    :func:`_reset_baa_reminder_for_tests`.
    """
    global _BAA_REMINDER_LOGGED
    if _BAA_REMINDER_LOGGED:
        return
    _BAA_REMINDER_LOGGED = True
    logger.info(
        "[vera-baa-001] vera.redaction: medtech mode active. Ensure a "
        "Business Associate Agreement (BAA) is signed with Vera before "
        "sending Protected Health Information through this SDK. "
        "See https://usevera.xyz/baa for details."
    )


def _reset_baa_reminder_for_tests() -> None:
    """Test-only: clears the once-per-process flag so tests can re-trigger
    the log. Not intended for production use."""
    global _BAA_REMINDER_LOGGED
    _BAA_REMINDER_LOGGED = False


@functools.lru_cache(maxsize=1)
def _warn_positional_args_with_schema_once() -> None:
    """Emit a once-per-process WARN when positional args meet schema mode.

    Schema rules key on parameter names, which are not available at the
    redactor layer when only positional args are passed. To avoid PHI
    leaks (e.g. ``r.serialize_args(("Sarah Johnson",), {})`` slipping
    through unredacted) we fail closed: positional args are replaced
    wholesale with ``self.replacement``. Customers should bind args to
    parameter names via ``inspect.signature`` in their decorator, or
    pass kwargs.
    """
    logger.warning(
        "vera.redaction: positional args passed to a schema-mode Redactor; "
        "schema rules key on parameter names which are not visible at this "
        "layer. Failing closed and redacting all positional args. Bind args "
        "to parameter names (inspect.signature) or call with kwargs to get "
        "schema-driven behaviour."
    )


# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _default_patterns_cached() -> tuple[tuple[str, re.Pattern], ...]:
    """Compile the default pattern list once per process.

    Returns an immutable tuple so callers that copy via
    :func:`_default_patterns` can safely mutate their copy without
    poisoning the cache. Internal: prefer :func:`_default_patterns`.
    """
    return tuple(_default_patterns_uncached())


def _default_patterns() -> list[tuple[str, re.Pattern]]:
    """Return a fresh list of (name, compiled_pattern) pairs.

    Names are exposed so log output is greppable — e.g. a redacted SSN
    appears as ``[REDACTED:ssn]``.

    Medtech-friendly defaults are included (``mrn``, ``dob``, ``ipv4``,
    ``ipv6``). ICD-10 is intentionally NOT a default because the
    pattern (``[A-Z]\\d{2}(?:\\.\\d{1,4})?``) collides with normal
    English text — customers opt in via a schema with
    ``pattern_name="icd10"``.

    Pattern compilation is cached for the lifetime of the process via
    :func:`_default_patterns_cached`. Each call constructs a fresh list
    around the cached, immutable pattern objects — safe to mutate the
    returned list without poisoning the cache. ``re.Pattern`` objects
    are immutable so they're safe to share.
    """
    return list(_default_patterns_cached())


def _default_patterns_uncached() -> list[tuple[str, re.Pattern]]:
    """Uncached construction of the default pattern list. Called once by
    :func:`_default_patterns_cached`.
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


@functools.lru_cache(maxsize=1)
def _medtech_patterns_cached() -> tuple[tuple[str, re.Pattern], ...]:
    """Compile the medtech extras once per process.

    Returns an immutable tuple so callers using :func:`_medtech_patterns`
    can safely mutate their fresh-list copy without poisoning the cache.
    Internal: prefer :func:`_medtech_patterns`.
    """
    return tuple(_medtech_patterns_uncached())


def _medtech_patterns() -> list[tuple[str, re.Pattern]]:
    """Return a fresh list of medtech extras (name, compiled_pattern).

    Pattern compilation is cached for the lifetime of the process via
    :func:`_medtech_patterns_cached`. Each call returns a fresh list
    around the cached, immutable pattern objects.

    ``icd10`` is intentionally returned here for use via
    :class:`Schema` ``PATTERN`` rules but is NOT included in the
    default-pass list (see :func:`_default_patterns`) — the pattern
    matches too much normal English text to be a safe default.
    """
    return list(_medtech_patterns_cached())


def _medtech_patterns_uncached() -> list[tuple[str, re.Pattern]]:
    """Uncached construction of the medtech extras. Called once by
    :func:`_medtech_patterns_cached`.
    """
    return [
        # MRN: matches ``MRN-12345678``, ``MRN_12345678``, ``MRN12345678``-style
        # identifiers (an ``MRN`` prefix followed by 4-12 digits). Bare
        # digit-only MRNs (no ``MRN`` prefix) are not matched — supply a
        # custom ``Schema`` PATTERN rule with your own regex if your data
        # uses bare numeric MRNs.
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
        # URL containing PHI substrings — replaces the entire URL when an
        # MRN, SSN, DOB, ``patient_id=…`` or ``ssn=…`` is embedded in the
        # path or query. URLs without PHI in path/query pass through
        # unmolested (api endpoints, callback URLs, doc links). The
        # surrounding patterns (``mrn``, ``ssn``, ``dob``) still apply on
        # top — defense-in-depth.
        (
            "url_phi",
            re.compile(
                r"https?://[^\s\"'<>]*(?:"
                r"\bMRN[-_]?\d{4,12}\b"
                r"|\b\d{3}-\d{2}-\d{4}\b"          # SSN
                r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"    # DOB MM/DD/YYYY
                r"|\b\d{4}-\d{2}-\d{2}\b"          # DOB ISO
                r"|patient_id=[^&\s\"'<>]+"
                r"|ssn=[^&\s\"'<>]+"
                r"|mrn=[^&\s\"'<>]+"
                r")[^\s\"'<>]*",
                re.IGNORECASE,
            ),
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


# HIPAA Safe Harbor extra block_keys for medtech mode. Used by
# :meth:`Redactor.medtech` as defense-in-depth on top of the schema —
# even if a customer's schema marks one of these PASSTHROUGH (mistakenly),
# block_keys still wins per the Phase 2 precedence rule. All names are
# lower-cased; the redactor's block_keys lookup is case-insensitive.
#
# Intentional exclusions (CRITICAL fixes — see PR #165 review):
# - Bare ``"patient"``: redacting a kwarg named ``patient`` (e.g.
#   ``def process(patient: PatientRecord)``) replaces the whole value
#   wholesale and skips recursion into the patient object. The schema's
#   deny-by-default for unmapped fields already protects nested PHI.
# - ``"patient_id"``: opaque, randomly-generated patient IDs ARE the
#   HIPAA-safe pattern. The starter schema marks ``patient_id``
#   PASSTHROUGH so audit records remain searchable. Customers whose
#   ``patient_id`` is an MRN-shaped identifier should pass
#   ``extra_block_keys={'patient_id'}`` to override.
# - Bare ``"url"``: redacting every URL field destroys API endpoints,
#   callback URLs, doc links, asset URLs. PHI embedded inside URL
#   strings is caught by the regex pass via the ``url_phi`` pattern
#   (see :func:`_medtech_patterns`).
_MEDTECH_BLOCK_KEYS: set[str] = {
    "patient_name", "first_name", "last_name", "full_name",
    "mrn", "medical_record_number",
    "ssn", "social_security",
    "dob", "date_of_birth", "birthdate",
    "address", "street", "street_address",
    "city", "state", "zip", "zipcode", "zip_code", "postal_code",
    "phone", "phone_number", "mobile", "cell",
    "email", "email_address",
    "diagnosis", "icd10", "icd_10", "icd10_code",
    "medication", "prescription", "rx",
    "insurance_id", "policy_number", "member_id", "subscriber_id",
    "ip", "ip_address", "device_id", "serial",
    "photo", "image_url", "face_photo",
    "audio", "voice_recording",
    "biometric", "fingerprint",
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

    .. warning::
       ``unmapped_policy=FieldPolicy.PASSTHROUGH`` disables
       deny-by-default for unmapped fields. PHI inside nested dicts (or
       any unmapped key) leaks through, because the recursive walk uses
       the same fallback policy at every level. Use only for gradual
       schema rollout. ``unmapped_policy=FieldPolicy.REDACT`` is the
       only safe choice for production medtech / HIPAA workflows.

    Field-name lookup is **case-insensitive**: a schema declared with
    ``"patient_name"`` matches dict keys ``"Patient_Name"``, ``"PATIENT_NAME"``,
    etc. If two schema keys collide on lowercase (e.g. ``"MRN"`` and
    ``"mrn"``), a WARN is logged at init time and the last-declared rule
    wins. Use distinct names instead.
    """

    fields: dict[str, FieldRule] = field(default_factory=dict)
    unmapped_policy: FieldPolicy = FieldPolicy.REDACT

    def __post_init__(self) -> None:
        # Build a case-insensitive view of fields once at init. Schema
        # objects are treated as immutable post-construction (mutating
        # ``fields`` after init would skip this index — documented gotcha).
        self._fields_lower: dict[str, FieldRule] = {}
        seen: dict[str, str] = {}  # lower -> original key
        for k, v in self.fields.items():
            kl = k.lower()
            if kl in seen and seen[kl] != k:
                logger.warning(
                    "vera.redaction: Schema fields collide on lowercase: "
                    "%r and %r both normalize to %r — last-declared wins",
                    seen[kl],
                    k,
                    kl,
                )
            seen[kl] = k
            self._fields_lower[kl] = v

        # Loud warning when PASSTHROUGH disables deny-by-default — this is
        # the documented "gradual rollout" escape hatch but it leaks PHI
        # through unmapped fields, including everything nested under a
        # PASSTHROUGH parent.
        if self.unmapped_policy == FieldPolicy.PASSTHROUGH:
            warnings.warn(
                "Schema.unmapped_policy=PASSTHROUGH disables deny-by-default "
                "for unmapped fields. PHI in unmapped fields (including "
                "nested dicts under a PASSTHROUGH parent) will leak. Use "
                "only for gradual schema rollout. Recommend "
                "Schema.unmapped_policy=REDACT for production.",
                stacklevel=2,
            )

    def rule_for(self, key: str) -> FieldRule:
        """Return the rule for ``key`` (case-insensitive), falling back to
        ``unmapped_policy``.

        Non-string keys are routed to the fallback policy — schema rules
        key on parameter / dict-key names which are conventionally strings.
        """
        if not isinstance(key, str):
            return FieldRule(
                policy=self.unmapped_policy,
                description="non-string key — fallback policy",
            )
        kl = key.lower()
        if kl in self._fields_lower:
            return self._fields_lower[kl]
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

    Pattern layering
    ----------------
    Two distinct uses of named patterns:

    1. The default pass: every ``(name, pattern)`` in ``self.patterns``
       is applied to every string. Customers can replace this list via
       the ``patterns`` constructor arg.
    2. Schema ``PATTERN`` rules: look up a pattern by name in
       ``self._patterns_by_name`` (built from ``self.patterns`` plus
       :func:`_medtech_patterns` for opt-in extras like ``"icd10"``).

    A custom ``patterns`` list shadows the default pass but does NOT
    shadow the ``_medtech_patterns()`` registry — schema rules can
    still reference ``"mrn"``, ``"dob"``, ``"icd10"`` even with custom
    patterns. To override one, register your replacement under the same
    name in ``patterns`` (it wins the index lookup via
    ``setdefault``).
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
        # Reject newlines / null bytes in the replacement string — this
        # value is interpolated into log lines and audit records, so
        # carriage returns and NULs would let a malicious customer-supplied
        # value forge new log entries (CRLF injection / log smuggling).
        if not isinstance(replacement, str):
            raise TypeError("Redactor.replacement must be a string")
        if "\n" in replacement or "\r" in replacement or "\x00" in replacement:
            raise ValueError(
                "Redactor.replacement must not contain newlines or null bytes "
                "(log injection risk)"
            )

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

        # In schema mode, refuse to ``repr()`` unknown object types. The
        # repr of a pydantic model / dataclass / ORM row exposes attribute
        # values, but the schema is keyed on dict keys / parameter names
        # and never inspects object attributes — so a Patient(name='Sarah',
        # mrn='99887766') would slip through. Fail closed: emit a tagged
        # placeholder so the audit reviewer can see what type was scrubbed.
        # Customers who explicitly want to expand whitelisted types should
        # convert to ``dict`` first (or, future work, supply a
        # ``serialize_object`` hook — TODO).
        if self.schema is not None:
            type_name = type(value).__name__
            return self._tagged_replacement(type_name)

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

        Schema mode + positional args: fails closed. Schema rules key on
        parameter names, which are not visible at this layer when only
        positional args are passed. Rather than letting PHI slip through,
        every positional arg is replaced with ``self.replacement`` and a
        once-per-process WARN is emitted. Callers that need schema-driven
        redaction over positional args should bind args to parameter
        names (``inspect.signature``) in their decorator before calling
        ``serialize_args``.
        """
        if args and self.schema is not None:
            # Schema cannot apply to positional args (no parameter names
            # available at this layer). Fail closed: redact every arg.
            _warn_positional_args_with_schema_once()
            serialized_args = [self.replacement for _ in args]
        else:
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
        - Common free-text fields (``description``, ``summary``,
          ``comment``, ``comments``, ``message``, ``transcript``,
          ``audio_transcript``, ``email_body``, ``body``, ``text``):
          ``REDACT``. Free-text fields cannot be safely scrubbed via
          patterns — names, dates, and identifiers slip through any
          regex pass. The starter schema redacts these wholesale by
          default. Override per-field if your application uses these
          names for non-PHI content (e.g. ``"summary"`` of a report).

        This classmethod returns a :class:`Schema` (not a
        :class:`Redactor`) — the customer flow is::

            redactor = Redactor(schema=Redactor.medtech_starter_schema())
        """
        return Schema(
            fields={
                # Container fields — declared PASSTHROUGH so the redactor
                # descends into the value and applies per-key rules at the
                # nested level. Without these, a kwarg named ``patient``
                # (the dominant medtech API shape) would hit the unmapped
                # policy and be replaced wholesale before recursion. The
                # leaf rules below still scrub PHI inside the container.
                "patient": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description=(
                        "Patient container — walks into the value so "
                        "nested per-field rules apply. Customers who want "
                        "the value replaced wholesale should pass "
                        "extra_block_keys={'patient'} to Redactor.medtech()."
                    ),
                ),
                "encounter": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description=(
                        "Encounter container — walks into the value so "
                        "nested per-field rules apply."
                    ),
                ),
                # FHIR-shaped containers — common Bundle/Resource keys.
                "entry": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description="FHIR Bundle.entry list — walks into items.",
                ),
                "resource": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description="FHIR Bundle.entry.resource — walks into the resource.",
                ),
                "resourceType": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description="FHIR resourceType discriminator — not PHI.",
                ),
                # History / events list — recurse into items so per-event
                # rules apply.
                "history": FieldRule(
                    FieldPolicy.PASSTHROUGH,
                    description=(
                        "Patient history list — walks into items so per-event "
                        "rules apply."
                    ),
                ),
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
                # Common free-text fields. Regex cannot reliably scrub PHI
                # from prose, so these are REDACTed wholesale. Override
                # per-field if your domain uses these names for non-PHI.
                "description": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text description — likely contains PHI.",
                ),
                "summary": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text summary — likely contains PHI.",
                ),
                "comment": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text comment.",
                ),
                "comments": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text comments.",
                ),
                "message": FieldRule(
                    FieldPolicy.REDACT,
                    description="Free-text message body.",
                ),
                "transcript": FieldRule(
                    FieldPolicy.REDACT,
                    description="Audio / text transcript — likely contains PHI.",
                ),
                "audio_transcript": FieldRule(
                    FieldPolicy.REDACT,
                    description="Audio transcript — likely contains PHI.",
                ),
                "email_body": FieldRule(
                    FieldPolicy.REDACT,
                    description="Email body — likely contains PHI.",
                ),
                "body": FieldRule(
                    FieldPolicy.REDACT,
                    description="Generic message body — likely contains PHI.",
                ),
                "text": FieldRule(
                    FieldPolicy.REDACT,
                    description="Generic free-text field — likely contains PHI.",
                ),
            },
            unmapped_policy=FieldPolicy.REDACT,
        )

    @classmethod
    def medtech(
        cls,
        *,
        schema: "Schema | None" = None,
        extra_block_keys: set[str] | None = None,
        extra_patterns: list[tuple[str, "re.Pattern"]] | None = None,
        max_length: int = 10_000,
        replacement: str = "[REDACTED]",
        custom_serializer: Callable[[Any], str] | None = None,
    ) -> "Redactor":
        """One-call factory for medtech HIPAA-aware redaction.

        Returns a Redactor preconfigured with:

        - The medtech starter schema (deny-by-default for unmapped fields)
        - Standard regex patterns for SSN, credit cards, emails, phones, AWS
          keys, JWTs, hex secrets, bearer tokens
        - Medtech-specific patterns added: MRN, DOB (multiple formats),
          IPv4/IPv6, ``url_phi`` (URL fields containing PHI in path/query)
        - Default block_keys augmented with HIPAA-specific identifiers
          (:data:`_MEDTECH_BLOCK_KEYS`)

        Args:
            schema: Override the default medtech starter schema. If None,
                uses :meth:`medtech_starter_schema`.
            extra_block_keys: Additional case-insensitive field names to
                always redact. Merged with defaults.
            extra_patterns: Additional named regex patterns. Merged with
                defaults.
            max_length, replacement, custom_serializer: Passed through to
                the Redactor constructor.

        HIPAA compliance note:
            Using :meth:`Redactor.medtech` does NOT make your deployment
            HIPAA-compliant on its own. You MUST have a signed Business
            Associate Agreement (BAA) with Vera before sending PHI through
            this SDK. This factory emits a single INFO log on first use as
            a reminder.

        Opaque patient IDs are HIPAA-safe:
            Use opaque, randomly-generated ``patient_id`` values. The
            starter schema preserves ``patient_id`` (PASSTHROUGH) so audit
            records remain searchable by ID. ``patient_id`` is intentionally
            NOT in the default :data:`_MEDTECH_BLOCK_KEYS` for the same
            reason. If your system uses MRN-shaped or otherwise PHI-bearing
            ``patient_id`` values, pass
            ``extra_block_keys={'patient_id'}`` to force redaction.

        Patient objects recurse:
            A kwarg named ``patient`` (e.g.
            ``def process(patient: PatientRecord)``) is NOT redacted
            wholesale. The redactor walks into the value so the schema's
            per-field rules apply at every depth, and unmapped fields fall
            through to deny-by-default. To redact the entire ``patient``
            kwarg without inspection, pass
            ``extra_block_keys={'patient'}``.

        Free-text PHI warning:
            Free-text fields (notes, transcripts, descriptions) cannot be
            reliably scrubbed via patterns. The starter schema redacts
            common free-text field names. If your data contains PHI in
            fields not on the starter list, declare them explicitly via
            the ``schema`` parameter.

        URL handling:
            URLs without embedded PHI (API endpoints, callback URLs, doc
            links, asset URLs) pass through unchanged. URLs containing
            MRN, SSN, DOB, ``patient_id=…``, ``ssn=…``, or ``mrn=…``
            substrings in path/query are replaced wholesale via the
            ``url_phi`` pattern.

        Performance:
            Safe to call once and reuse the returned Redactor across
            requests. Each call constructs a fresh Redactor instance but
            pattern compilation is cached for the lifetime of the process
            via :func:`functools.lru_cache` on :func:`_default_patterns`
            and :func:`_medtech_patterns`.
        """
        # Default to the canonical medtech starter schema unless overridden.
        if schema is None:
            schema = cls.medtech_starter_schema()

        # Effective block_keys = default ∪ HIPAA-extra ∪ caller-supplied.
        # All lowered for the case-insensitive lookup the Redactor performs.
        merged_block_keys: set[str] = {k.lower() for k in _default_block_keys()}
        merged_block_keys |= {k.lower() for k in _MEDTECH_BLOCK_KEYS}
        if extra_block_keys:
            merged_block_keys |= {k.lower() for k in extra_block_keys}

        # Effective patterns = default + caller-supplied (order preserved).
        merged_patterns: list[tuple[str, re.Pattern]] = list(_default_patterns())
        if extra_patterns:
            merged_patterns.extend(extra_patterns)

        # Emit the BAA reminder once per process before returning. The
        # reminder lives on the module logger; customer logging config
        # decides where it lands.
        _emit_baa_reminder()

        return cls(
            patterns=merged_patterns,
            block_keys=merged_block_keys,
            max_length=max_length,
            replacement=replacement,
            custom_serializer=custom_serializer,
            schema=schema,
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
        # Reuse ``_tagged_replacement`` so PATTERN-mode output matches REDACT-mode
        # output: bracketed default → ``[REDACTED:fieldname]``; non-bracketed
        # custom replacement (``<scrubbed>``) → used verbatim. Pre-fixes a bug
        # where ``"<scrubbed>"`` produced ``"<scrubbed:mrn]"``.
        tag = self._tagged_replacement(name)
        try:
            # Use a callable replacement so ``re.sub`` does NOT interpret
            # backreferences (``\1``, ``\g<...>``) in customer-supplied
            # replacement strings. The previous string form would raise
            # ``re.error`` on something like ``replacement="[MASK\\1]"`` and
            # the bare ``except`` below would fall through, leaking PHI.
            # ``t=tag`` binds at lambda-creation time (no late-binding).
            replaced = pattern.sub(lambda m, t=tag: t, value)
        except Exception:  # noqa: BLE001 — fail open
            logger.warning(
                "vera.redaction: pattern %r raised on field %r; falling closed (REDACT)",
                name,
                key,
                exc_info=True,
            )
            # Fail CLOSED on pattern errors — returning the raw value here
            # would leak PHI in the very case we're trying to scrub.
            return tag

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
                # Callable replacement — re.sub does NOT interpret backrefs
                # in customer-supplied replacement strings. Pre-bind ``tag``
                # via default-arg trick so the lambda captures the value at
                # creation time (avoids late-binding bugs in this loop).
                tag = self._tagged_replacement(name)
                if name == "credit_card":
                    text = pattern.sub(
                        lambda m, t=tag: (
                            t if _luhn_valid(m.group(0)) else m.group(0)
                        ),
                        text,
                    )
                else:
                    text = pattern.sub(lambda m, t=tag: t, text)
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
