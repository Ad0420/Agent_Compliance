"""Branded exception hierarchy for the Vera SDK.

These wrap underlying httpx errors so callers can catch Vera-specific failures
without depending on httpx internals. Each error carries an optional
``request_id`` (from the server's ``X-Request-ID`` response header) and a docs
URL for the corresponding error code.

12-class catalog (Phase 1 PR 6)
-------------------------------
Per ``docs/error-discipline.md`` (the cross-phase PR-gate checklist), every
error path in the SDK must surface the four-field template:

* ``user_facing_reason`` — one sentence, plain language, safe to render to a
  CEO or in-house counsel; no stack traces, no field names, no hex IDs.
* ``developer_reason`` — the specific technical condition that triggered the
  error (field/value/state).
* ``fix_url`` — deep link into the dashboard that lands the user on the
  remediation screen.
* ``docs_url`` — deep link into Vera's docs site explaining the error class.

The catalog ships in two slices:

* The seven generic transport-layer errors (``VeraError``, ``VeraAuthError``,
  ``VeraRateLimitError``, ``VeraServerError``, ``VeraTimeoutError``,
  ``VeraNetworkError``, ``VeraValidationError``) which were public API ahead
  of the v0.4 client refactor and continue to be raised by ``record_action``
  + the background flush worker. These have been retrofitted to accept the
  template fields as keyword-only kwargs so old call sites keep working.
* Five new domain-layer errors (``PolicyBlock``, ``PendingReview``,
  ``WrongKeyTier``, ``TenantMissingOrInvalid``, ``ReviewerCredentialsInsufficient``)
  raised by the policy / gate / tenant resolver paths landing across
  Phase 1 PRs 7-9. The httpx wrapper in :mod:`vera.client` activates these
  defensively against current 401/403/422 envelopes; once the backend ships
  the structured ``code`` field for the matching paths, the mapping fires
  automatically without SDK changes.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

DOC_BASE = "https://docs.usevera.xyz/errors"

# ---------------------------------------------------------------------------
# Backward-compat: docs_url slug renames (Phase 1 PR 6).
# ---------------------------------------------------------------------------
#
# Three transport-layer classes had their ``code`` (and therefore the
# ``docs_url`` slug rendered into ``str(err)``) renamed to match the
# 12-class catalog in ``docs/error-discipline.md``:
#
#   * VeraAuthError:    "auth"    -> "invalid_api_key"
#   * VeraTimeoutError: "timeout" -> "gate_timeout_or_network"
#   * VeraNetworkError: "network" -> "gate_timeout_or_network"
#
# Constructor signatures, ``except`` matching, and ``to_dict()`` field names
# are unchanged — only the slug rendered into the URL substring changed. To
# catch operators whose log-grep / alerting matched the old URL substrings,
# the first ``str(err)`` call against a renamed class emits a one-shot
# DeprecationWarning per renamed code per process.
_DOCS_URL_RENAMES: dict[str, tuple[str, str]] = {
    # new_code -> (old_code, class_name_for_message)
    "invalid_api_key": ("auth", "VeraAuthError"),
    "gate_timeout_or_network_timeout": ("timeout", "VeraTimeoutError"),
    "gate_timeout_or_network_network": ("network", "VeraNetworkError"),
}

# Module-level dedupe — ensures the warning fires exactly once per renamed
# class per process. Keyed by the renamed-class identifier (NOT the shared
# new code) so VeraTimeoutError and VeraNetworkError each warn independently
# even though they collapsed onto the same ``gate_timeout_or_network`` code.
_warned_codes: set[str] = set()


def _warn_docs_url_renamed_once(rename_key: str) -> None:
    """Emit a one-shot DeprecationWarning for a renamed docs_url slug."""
    if rename_key in _warned_codes:
        return
    if rename_key not in _DOCS_URL_RENAMES:
        return
    _warned_codes.add(rename_key)
    old_code, class_name = _DOCS_URL_RENAMES[rename_key]
    new_code = (
        "invalid_api_key"
        if rename_key == "invalid_api_key"
        else "gate_timeout_or_network"
    )
    warnings.warn(
        f"{class_name} docs_url changed: errors/{old_code} -> errors/{new_code}. "
        "Update log-grep / alerting.",
        DeprecationWarning,
        stacklevel=2,
    )


def _reset_docs_url_rename_warnings() -> None:
    """Reset the once-per-process dedupe set. Intended for tests."""
    _warned_codes.clear()

# Default ``fix_url`` for errors where the remediation surface hasn't been
# built yet (per docs/error-discipline.md, ``null`` is not allowed — point at
# a documented support fallback instead).
SUPPORT_URL = "https://docs.usevera.xyz/support"


def _docs_url_for(code: str) -> str:
    """Build the canonical ``docs_url`` for a given error code."""
    return f"{DOC_BASE}/{code}"


class VeraError(Exception):
    """Base class for all Vera SDK errors.

    Conforms to the four-field error-discipline template defined in
    ``docs/error-discipline.md``. Subclasses inherit the template and set
    sensible defaults; callers can override any field at construction time.

    Attributes:
        code: Stable short identifier — drives the ``docs_url`` suffix and
            matches the catalog in ``docs/error-discipline.md``.
        message: The original positional message (kept for ``__str__``
            backward compat with the v0.3.x signature).
        user_facing_reason: One-sentence plain-language explanation for
            customer-facing surfaces.
        developer_reason: Specific technical condition that triggered the
            error — what ``__str__`` returns (engineer-grade).
        fix_url: Deep link into the dashboard remediation screen, or the
            documented support fallback if no screen exists yet.
        docs_url: Deep link into Vera's docs site for this error class.
        request_id: Server-emitted ``X-Request-ID`` echo, if available.
        status_code: HTTP status code that triggered the error, if any.
    """

    code: str = "vera_error"
    # Subclasses override these defaults so a bare ``VeraAuthError("boom")``
    # construction still produces a meaningful four-field payload. Callers
    # who want bespoke copy pass ``user_facing_reason=`` / ``developer_reason=``
    # / ``fix_url=`` at construction time and override per-instance.
    default_user_facing_reason: str = (
        "Something went wrong talking to Vera. Please retry or contact support."
    )
    default_developer_reason: str = "Unclassified Vera SDK error."
    default_fix_url: str = SUPPORT_URL

    def __init__(
        self,
        message: str = "",
        *,
        request_id: str | None = None,
        status_code: int | None = None,
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        fix_url: str | None = None,
        docs_url: str | None = None,
    ):
        self.message = message
        self.request_id = request_id
        self.status_code = status_code
        self.user_facing_reason = (
            user_facing_reason
            if user_facing_reason is not None
            else self.default_user_facing_reason
        )
        # ``developer_reason`` falls back to ``message`` first (preserves the
        # v0.3.x behaviour where the positional message was the engineer copy),
        # then to the class-level default.
        self.developer_reason = (
            developer_reason
            if developer_reason is not None
            else (message or self.default_developer_reason)
        )
        self.fix_url = fix_url if fix_url is not None else self.default_fix_url
        self.docs_url = docs_url if docs_url is not None else _docs_url_for(self.code)
        # Preserve the v0.3.x rendered string so existing tests and log
        # patterns (request_id=..., — see docs URL) keep working.
        # The new ``[fix=...]`` token is additive and ONLY appears when
        # the caller customised ``fix_url`` away from the class default
        # (i.e. the backend returned a remediation URL). Snapshot tests
        # that match on the v0.3.x string still pass — they didn't set
        # ``fix_url`` so the token doesn't render. Wave 2B PR B1.
        suffix = ""
        if request_id:
            suffix += f" [request_id={request_id}]"
        if self.fix_url and self.fix_url != self.default_fix_url:
            suffix += f" [fix={self.fix_url}]"
        suffix += f" — see {self.docs_url}"
        rendered = f"{message}{suffix}" if message else self.developer_reason + suffix
        super().__init__(rendered)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error to the four-field template + metadata.

        Used by structured logs, the dashboard error renderer, and the
        ``vera.errors.ensure_complete`` lint helper (planned). Matches the
        JSON shape documented in ``docs/error-discipline.md`` plus
        ``status_code`` and ``request_id`` for correlation.
        """
        return {
            "code": self.code,
            "user_facing_reason": self.user_facing_reason,
            "developer_reason": self.developer_reason,
            "fix_url": self.fix_url,
            "docs_url": self.docs_url,
            "request_id": self.request_id,
            "status_code": self.status_code,
        }


# ---------------------------------------------------------------------------
# Transport-layer errors (existing 7 — retrofitted with template fields).
# ---------------------------------------------------------------------------


class VeraAuthError(VeraError):
    """401/403: API key missing, invalid, or revoked."""

    code = "invalid_api_key"
    default_user_facing_reason = (
        "Vera could not authenticate this request. Verify your API key in the "
        "dashboard."
    )
    default_developer_reason = (
        "Server rejected the request with 401/403 — API key is missing, "
        "malformed, or revoked."
    )
    default_fix_url = "https://app.usevera.xyz/settings/api-keys"

    def __str__(self) -> str:  # pragma: no cover — exercised by warn test
        _warn_docs_url_renamed_once("invalid_api_key")
        return super().__str__()


class VeraRateLimitError(VeraError):
    """429: too many requests."""

    code = "rate_limit"
    default_user_facing_reason = (
        "Vera is throttling requests from your account. Retry shortly."
    )
    default_developer_reason = (
        "Server returned 429 — request rate exceeded the per-key quota."
    )
    default_fix_url = "https://app.usevera.xyz/settings/usage"


class VeraServerError(VeraError):
    """5xx: Vera service is unavailable."""

    code = "server"
    default_user_facing_reason = (
        "Vera is temporarily unavailable. Please retry in a moment."
    )
    default_developer_reason = (
        "Server returned 5xx — upstream service failure; SDK retries exhausted."
    )
    default_fix_url = "https://status.usevera.xyz"


class VeraTimeoutError(VeraError):
    """Request timed out."""

    code = "gate_timeout_or_network"
    default_user_facing_reason = (
        "Vera did not respond in time. Please retry."
    )
    default_developer_reason = (
        "Request timed out before the server responded."
    )
    default_fix_url = "https://status.usevera.xyz"

    def __str__(self) -> str:  # pragma: no cover — exercised by warn test
        _warn_docs_url_renamed_once("gate_timeout_or_network_timeout")
        return super().__str__()


class VeraNetworkError(VeraError):
    """Network failure (DNS, TLS, connection refused, etc.)."""

    code = "gate_timeout_or_network"
    default_user_facing_reason = (
        "Vera could not be reached over the network."
    )
    default_developer_reason = (
        "Network-layer failure (DNS, TLS, connection refused, or response decode)."
    )
    default_fix_url = "https://status.usevera.xyz"

    def __str__(self) -> str:  # pragma: no cover — exercised by warn test
        _warn_docs_url_renamed_once("gate_timeout_or_network_network")
        return super().__str__()


class VeraValidationError(VeraError):
    """4xx other than 401/403/429: malformed request."""

    code = "validation"
    default_user_facing_reason = (
        "Vera rejected this request because of a malformed payload."
    )
    default_developer_reason = (
        "Server returned 4xx (non-auth, non-rate-limit) — request payload "
        "failed validation."
    )
    default_fix_url = SUPPORT_URL


# Backward-compat: the catch-all client-side validation error used by the
# httpx wrapper. Alias kept so existing imports keep working.
VeraClientError = VeraValidationError


# ---------------------------------------------------------------------------
# Domain-layer errors (5 new — Phase 1 PR 6 / Stream D1).
# ---------------------------------------------------------------------------


class PolicyBlock(VeraError):
    """Gate evaluation returned BLOCK; the action MUST NOT be executed.

    Raised by ``@vera.gate`` (Phase 2) when the policy decision is BLOCK,
    and by the httpx wrapper when the backend signals ``code='policy_block'``
    or ``code='baa_required'`` / ``code='baa_expired'`` on a 403/422 response.

    Fields:
        reason: Short human-readable reason ("BAA required for live actions",
            "Controlled-substance DEA check failed").
        citation: Regulation reference, e.g. ``"HIPAA § 164.504(e)"``.
        fix_url: Dashboard URL to the remediation screen (BAA upload, policy
            pack install, etc.).
        retryable: Whether the calling agent should re-attempt after the
            customer resolves the underlying condition (usually ``False`` —
            BLOCK is terminal until the operator acts).
    """

    code = "policy_block"
    default_user_facing_reason = (
        "This action was blocked by a compliance policy and was not executed."
    )
    default_developer_reason = "Gate evaluation returned BLOCK."
    default_fix_url = SUPPORT_URL

    def __init__(
        self,
        reason: str = "",
        citation: str = "",
        *,
        fix_url: str | None = None,
        retryable: bool = False,
        # --- NEW in Wave 2B PR B1 (additive; all default to falsy so
        # existing v1.0.x callers ``PolicyBlock("reason", "cite")`` and
        # ``except PolicyBlock as e: e.reason`` keep working unchanged).
        gate_name: str = "",
        reason_detail: str | None = None,
        required_role: str | None = None,
        # ---
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        docs_url: str | None = None,
    ):
        self.reason = reason
        self.citation = citation
        self.retryable = retryable
        self.gate_name = gate_name
        self.reason_detail = reason_detail
        self.required_role = required_role
        # ``developer_reason`` defaults to "<reason> (citation=<citation>)"
        # so logs make it obvious which rule fired. When ``reason_detail``
        # is present, prefer it — it's the engineer-grade explanation the
        # gate provided (the SDK already runs it through the PHI redactor
        # in ``gate._safe_reason_detail`` before stamping it here).
        if developer_reason is None:
            if reason_detail:
                developer_reason = reason_detail
            elif reason:
                developer_reason = (
                    f"{reason} (citation={citation})" if citation else reason
                )
        super().__init__(
            reason,
            request_id=request_id,
            status_code=status_code,
            user_facing_reason=user_facing_reason,
            developer_reason=developer_reason,
            fix_url=fix_url,
            docs_url=docs_url,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            reason=self.reason,
            citation=self.citation,
            retryable=self.retryable,
            gate_name=self.gate_name,
            reason_detail=self.reason_detail,
            required_role=self.required_role,
        )
        return d


class PendingReview(VeraError):
    """Gate evaluation returned REQUIRE_HITL; the action is awaiting attestation.

    Raised by ``@vera.gate`` (Phase 2) when the policy decision is
    REQUIRE_HITL. The action MAY have proceeded as a draft (per gate
    semantics) but the audit record is not finalised until a reviewer
    completes the Review.

    Fields:
        review_id: Server-assigned identifier; pass to
            ``client.get_review(review_id)`` to poll status.
        expected_resolution: ISO-8601 timestamp or human-readable string for
            when the reviewer SLA expects a decision.
        webhook_url: Optional URL the reviewer's verdict will POST to.
        required_role: Role the reviewer must hold (e.g.
            ``"attending_physician"``, ``"dea_licensed_prescriber"``).
    """

    code = "pending_review"
    default_user_facing_reason = (
        "This action is awaiting human review and has not yet been completed."
    )
    default_developer_reason = "Gate evaluation returned REQUIRE_HITL."
    default_fix_url = "https://app.usevera.xyz/reviews"

    def __init__(
        self,
        review_id: str = "",
        expected_resolution: Any = None,
        webhook_url: str | None = None,
        required_role: str | None = None,
        *,
        # --- NEW in Wave 2B PR B1 (additive; all default to falsy so
        # ``except PendingReview as e: e.review_id`` patterns keep
        # working unchanged on existing v1.0.x callers).
        gate_name: str = "",
        reason: str = "",
        reason_detail: str | None = None,
        citation: str | None = None,
        # ---
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        fix_url: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        docs_url: str | None = None,
    ):
        self.review_id = review_id
        self.expected_resolution = expected_resolution
        self.webhook_url = webhook_url
        self.required_role = required_role
        self.gate_name = gate_name
        self.reason = reason
        self.reason_detail = reason_detail
        self.citation = citation
        if developer_reason is None:
            # Prefer the gate's ``reason_detail`` when present (engineer
            # grade per the Ruling contract; PHI-scrubbed upstream by
            # ``gate._safe_reason_detail``). Fall through to the legacy
            # structured "review_id=...; required_role=..." string for
            # callers that don't supply ``reason_detail`` (back-compat).
            if reason_detail:
                developer_reason = reason_detail
            else:
                parts = ["Gate evaluation returned REQUIRE_HITL"]
                if review_id:
                    parts.append(f"review_id={review_id}")
                if required_role:
                    parts.append(f"required_role={required_role}")
                developer_reason = "; ".join(parts) + "."
        message = f"Pending review {review_id}" if review_id else "Pending review"
        super().__init__(
            message,
            request_id=request_id,
            status_code=status_code,
            user_facing_reason=user_facing_reason,
            developer_reason=developer_reason,
            fix_url=fix_url,
            docs_url=docs_url,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            review_id=self.review_id,
            expected_resolution=(
                self.expected_resolution.isoformat()
                if hasattr(self.expected_resolution, "isoformat")
                else self.expected_resolution
            ),
            webhook_url=self.webhook_url,
            required_role=self.required_role,
            gate_name=self.gate_name,
            reason=self.reason,
            reason_detail=self.reason_detail,
            citation=self.citation,
        )
        return d


class WrongKeyTier(VeraError):
    """Caller used an ``al_test_*`` key against a production-only endpoint, or vice versa.

    Raised by the httpx wrapper when the backend signals
    ``code='wrong_key_tier'`` on a 403. The remediation is either rotating
    to a key of the correct tier or routing the call to the matching
    environment.

    Fields:
        key_kind: The tier of the key the caller provided
            (``'test'`` or ``'live'``).
        required: The tier the endpoint requires (``'test'`` or ``'live'``).
        endpoint: The path that was called (e.g.
            ``"POST /v1/gates/evaluate"``).
    """

    code = "wrong_key_tier"
    default_user_facing_reason = (
        "This action requires a different API key environment (test vs. live)."
    )
    default_developer_reason = (
        "Key tier does not match endpoint requirement."
    )
    default_fix_url = "https://app.usevera.xyz/settings/api-keys"

    def __init__(
        self,
        key_kind: str = "",
        required: str = "",
        endpoint: str = "",
        *,
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        fix_url: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        docs_url: str | None = None,
    ):
        self.key_kind = key_kind
        self.required = required
        self.endpoint = endpoint
        if developer_reason is None and (key_kind or required or endpoint):
            developer_reason = (
                f"Key tier '{key_kind}' rejected for endpoint '{endpoint}' "
                f"(requires '{required}')."
            )
        message = (
            f"wrong key tier: '{key_kind}' on '{endpoint}' (requires '{required}')"
            if (key_kind or endpoint)
            else "wrong key tier"
        )
        super().__init__(
            message,
            request_id=request_id,
            status_code=status_code,
            user_facing_reason=user_facing_reason,
            developer_reason=developer_reason,
            fix_url=fix_url,
            docs_url=docs_url,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            key_kind=self.key_kind,
            required=self.required,
            endpoint=self.endpoint,
        )
        return d


# Allowed values for ``TenantMissingOrInvalid.reason``. Kept in sync with
# ``docs/error-discipline.md`` and the backend's tenant-resolver enum
# (Phase 1 PR 7 / Stream D3-D4).
TENANT_REASON_MISSING = "missing"
TENANT_REASON_MALFORMED = "malformed"
TENANT_REASON_PHI_SHAPE = "phi_shape_detected"


# Defense-in-depth PHI-shape detector. The backend's classifier MAY disagree
# with the SDK's (e.g. backend labels an SSN-shaped value ``tenant_malformed``
# while the SDK would call it ``phi_shape_detected``). If we only redacted
# on the explicit ``phi_shape_detected`` reason, a backend misclassification
# would echo a bare SSN/DOB into ``provided_value`` and into structured logs.
#
# Lean toward false-positive (over-redact) — losing a diagnostic string is
# vastly cheaper than logging PHI. Patterns are anchored to the FULL value
# (full-match semantics via ``fullmatch``) so legitimate tenant IDs that
# merely *contain* digits aren't redacted.
_PHI_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{3}-\d{2}-\d{4}"),          # SSN with dashes
    re.compile(r"\d{9}"),                       # SSN without dashes
    re.compile(r"\d{4}-\d{2}-\d{2}"),          # ISO date (DOB)
    re.compile(r"\d{2}/\d{2}/\d{4}"),          # US date (DOB)
    re.compile(r"\d{2}-\d{2}-\d{4}"),          # alt date (DOB)
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),    # loose US date
    # name + number combos ("John Smith 1985-03-12", "smith_19850312")
    re.compile(r"[A-Za-z]+[\s_-]+\d{4,}"),
    re.compile(r"\d{4,}[\s_-]+[A-Za-z]+"),
)


def _looks_like_phi(value: Any) -> bool:
    """Return True if ``value`` matches any PHI-shape heuristic.

    Conservative — runs against ``str(value)`` and uses ``fullmatch`` so a
    perfectly-shaped SSN / DOB / name+number triggers but a long tenant id
    that merely *contains* digits does not.
    """
    if value is None:
        return False
    try:
        s = str(value)
    except Exception:
        return True  # something weird — fail closed
    if not s:
        return False
    for pat in _PHI_SHAPE_PATTERNS:
        if pat.fullmatch(s):
            return True
    return False


def _is_likely_phi(value: Any) -> bool:
    """Defensive over-redaction trigger: whitespace + digits is suspicious.

    The strict :func:`_looks_like_phi` heuristic uses ``fullmatch`` against
    a narrow set of single-token shapes (SSN, ISO date, ``name_1985``). It
    does NOT fire on natural-language combinations like ``"John Doe 1972"``
    or ``"Jane Smith DOB 03 14 1972"`` because they contain multiple words
    with internal whitespace that the existing patterns don't anchor.

    Those exact shapes are extremely common PHI leak vectors (a developer
    accidentally passing a patient name + DOB as a tenant id). Rather than
    teach :func:`_looks_like_phi` every variant of "PII written like a
    sentence", we add a coarser second filter: any string containing BOTH
    whitespace AND a digit is treated as likely-PHI and over-redacted.

    Legitimate tenant ids (``acme_corp_us_east_2``, ``customer-12345``)
    do not contain whitespace and are unaffected. Losing a diagnostic
    string is vastly cheaper than echoing PHI into ``provided_value`` or
    ``developer_reason``.
    """
    if not isinstance(value, str):
        return False
    has_whitespace = bool(re.search(r"\s", value))
    has_digit = bool(re.search(r"\d", value))
    return has_whitespace and has_digit


class TenantMissingOrInvalid(VeraError):
    """The action requires a ``tenant_id`` but none was resolved (or it's invalid).

    Raised by the httpx wrapper when the backend signals
    ``code='tenant_missing'`` / ``code='tenant_malformed'`` /
    ``code='phi_shape_in_tenant_id'`` on a 422. Also raised by the SDK
    tenant resolver (Phase 1 PR 7) when no resolver was bound or when the
    resolved value fails the ``^[a-zA-Z0-9_-]{1,64}$`` format regex or the
    PHI-shape heuristic on a live key.

    Fields:
        reason: One of ``'missing'``, ``'malformed'``, ``'phi_shape_detected'``.
        provided_value: The offending value — populated ONLY when safe to
            echo (i.e. NOT for ``'phi_shape_detected'``, where echoing the
            value would defeat the heuristic's purpose).
    """

    code = "tenant_missing"
    default_user_facing_reason = (
        "This action requires a tenant identifier that we could not resolve."
    )
    default_developer_reason = (
        "No tenant_id could be resolved for this call."
    )
    default_fix_url = "https://docs.usevera.xyz/sdk/tenant-resolver"

    def __init__(
        self,
        reason: str = TENANT_REASON_MISSING,
        provided_value: str | None = None,
        *,
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        fix_url: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        docs_url: str | None = None,
    ):
        self.reason = reason
        # NEVER echo a PHI-shape value — that would defeat the purpose of the
        # heuristic (the value is the thing we're trying NOT to log).
        #
        # Belt-and-suspenders, layered:
        #   1. Explicit PHI reason — always redact.
        #   2. Strict :func:`_looks_like_phi` (SSN / DOB / ``name_1985``)
        #      fullmatch — redact even when the backend mis-labeled the
        #      reason as ``malformed``.
        #   3. Defensive :func:`_is_likely_phi` (whitespace + digit) —
        #      catches multi-word combinations like ``"John Doe 1972"``
        #      that the strict patterns miss because they don't fullmatch
        #      a sentence-shaped string. Lean toward false-positive:
        #      losing a diagnostic string is cheaper than logging PHI.
        likely_phi = _is_likely_phi(provided_value)
        if (
            reason == TENANT_REASON_PHI_SHAPE
            or _looks_like_phi(provided_value)
            or likely_phi
        ):
            self.provided_value = None
        else:
            self.provided_value = provided_value

        # Per-reason ``code`` so the catalog stays granular (see
        # ``docs/error-discipline.md`` 12-class table).
        if reason == TENANT_REASON_PHI_SHAPE:
            self.code = "tenant_invalid_or_phi"
        elif reason == TENANT_REASON_MALFORMED:
            self.code = "tenant_invalid_or_phi"
        else:
            self.code = "tenant_missing"

        if developer_reason is None:
            if reason == TENANT_REASON_PHI_SHAPE:
                developer_reason = (
                    "tenant_id matches the PHI-shape heuristic — value redacted; "
                    "rejected hard on al_live_*."
                )
            elif reason == TENANT_REASON_MALFORMED:
                # Use the post-redaction ``self.provided_value`` (None when
                # any PHI heuristic fired) so we don't leak via developer_reason.
                # When the defensive whitespace-and-digit heuristic tripped,
                # emit a distinct message so the operator knows WHY the value
                # was redacted (a generic ``(value redacted)`` would be opaque).
                safe_value = self.provided_value
                if likely_phi:
                    developer_reason = (
                        "tenant_id failed the regex check "
                        "(value redacted: contains whitespace + digits)"
                    )
                else:
                    developer_reason = (
                        f"tenant_id failed the ^[a-zA-Z0-9_-]{{1,64}}$ format check"
                        + (f" (provided={safe_value!r})." if safe_value else ".")
                    )
            else:
                developer_reason = (
                    "No tenant_id resolved — pass tenant_id=, use the "
                    "vera.tenant context manager, or bind a resolver via "
                    "vera.set_default_tenant_resolver()."
                )
        message = f"tenant_id problem: {reason}"
        super().__init__(
            message,
            request_id=request_id,
            status_code=status_code,
            user_facing_reason=user_facing_reason,
            developer_reason=developer_reason,
            fix_url=fix_url,
            docs_url=docs_url,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            reason=self.reason,
            provided_value=self.provided_value,
        )
        return d


class ReviewerCredentialsInsufficient(VeraError):
    """Callback attestation rejected — reviewer's role doesn't match the gate's required_role.

    Raised by the httpx wrapper when the backend signals
    ``code='reviewer_credentials_insufficient'`` on a 403, typically from
    ``POST /v1/reviews/{id}/complete`` (Phase 2). The remediation is to
    route the review to a reviewer holding the required role / license.

    Fields:
        review_id: Identifier of the review the attestation targeted.
        reviewer_role: Role asserted by the reviewer attempting to complete.
        required_role: Role the gate's policy requires.
    """

    code = "reviewer_credentials_insufficient"
    default_user_facing_reason = (
        "The reviewer who tried to complete this review does not hold the "
        "required role."
    )
    default_developer_reason = (
        "Reviewer attestation rejected — role mismatch."
    )
    default_fix_url = "https://app.usevera.xyz/reviews"

    def __init__(
        self,
        review_id: str = "",
        reviewer_role: str = "",
        required_role: str = "",
        *,
        user_facing_reason: str | None = None,
        developer_reason: str | None = None,
        fix_url: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        docs_url: str | None = None,
    ):
        self.review_id = review_id
        self.reviewer_role = reviewer_role
        self.required_role = required_role
        if developer_reason is None and (reviewer_role or required_role):
            developer_reason = (
                f"Reviewer role '{reviewer_role}' does not satisfy required "
                f"role '{required_role}' on review {review_id!r}."
            )
        message = (
            f"reviewer role '{reviewer_role}' insufficient for review "
            f"{review_id!r} (requires '{required_role}')"
            if review_id
            else "reviewer credentials insufficient"
        )
        super().__init__(
            message,
            request_id=request_id,
            status_code=status_code,
            user_facing_reason=user_facing_reason,
            developer_reason=developer_reason,
            fix_url=fix_url,
            docs_url=docs_url,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            review_id=self.review_id,
            reviewer_role=self.reviewer_role,
            required_role=self.required_role,
        )
        return d


# ---------------------------------------------------------------------------
# Backend ``code`` → SDK class mapping (used by vera.client.wrap_httpx_error).
# ---------------------------------------------------------------------------

# Maps the ``code`` string the backend emits in its error envelope to the
# branded SDK class that should be raised. Wired here (rather than as a
# big if/elif inside ``wrap_httpx_error``) so PRs that add new codes only
# need to edit this table — the dispatch logic stays one line.
#
# Codes for Phase 2 backend paths (``baa_required``, ``baa_expired``,
# ``reviewer_credentials_insufficient``, etc.) are wired defensively here:
# they're harmless until the backend actually emits them, at which point
# the mapping fires automatically without an SDK release.
CODE_TO_ERROR_CLASS: dict[str, type[VeraError]] = {
    # Auth
    "missing_api_key": VeraAuthError,
    "invalid_api_key": VeraAuthError,
    "unauthorized": VeraAuthError,
    # Wrong tier
    "wrong_key_tier": WrongKeyTier,
    # Policy block — BAA family + generic policy_block
    "policy_block": PolicyBlock,
    "baa_required": PolicyBlock,
    "baa_expired": PolicyBlock,
    # HITL
    "pending_review": PendingReview,
    "reviewer_credentials_insufficient": ReviewerCredentialsInsufficient,
    # Tenant
    "tenant_missing": TenantMissingOrInvalid,
    "tenant_malformed": TenantMissingOrInvalid,
    "phi_shape_in_tenant_id": TenantMissingOrInvalid,
    "tenant_invalid_or_phi": TenantMissingOrInvalid,
    # Rate limit
    "rate_limit": VeraRateLimitError,
}


__all__ = [
    # Constants
    "DOC_BASE",
    "SUPPORT_URL",
    "TENANT_REASON_MISSING",
    "TENANT_REASON_MALFORMED",
    "TENANT_REASON_PHI_SHAPE",
    # Transport-layer (existing 7)
    "VeraError",
    "VeraAuthError",
    "VeraRateLimitError",
    "VeraServerError",
    "VeraTimeoutError",
    "VeraNetworkError",
    "VeraValidationError",
    "VeraClientError",
    # Domain-layer (new 5)
    "PolicyBlock",
    "PendingReview",
    "WrongKeyTier",
    "TenantMissingOrInvalid",
    "ReviewerCredentialsInsufficient",
    # Mapping
    "CODE_TO_ERROR_CLASS",
]
