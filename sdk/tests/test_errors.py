"""Tests for the branded exception hierarchy in :mod:`vera.errors`.

Covers:

* The seven transport-layer classes that pre-date Phase 1 PR 6
  (``VeraError`` + 6 subclasses), retrofitted to carry the four-field
  error-discipline template (``user_facing_reason``, ``developer_reason``,
  ``fix_url``, ``docs_url``) while preserving the v0.3.x positional
  signature.
* The five new domain-layer classes added in Phase 1 PR 6
  (``PolicyBlock``, ``PendingReview``, ``WrongKeyTier``,
  ``TenantMissingOrInvalid``, ``ReviewerCredentialsInsufficient``).
* ``to_dict()`` round-trip — the structured-logging contract every error
  in the catalog must satisfy.
* Backward compatibility — the v0.3.x ``VeraSubclass("message")``
  positional construction MUST keep working without any new kwargs.
"""

import warnings

import pytest

from vera import (
    PendingReview,
    PolicyBlock,
    ReviewerCredentialsInsufficient,
    TenantMissingOrInvalid,
    VeraAuthError,
    VeraClientError,
    VeraError,
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
    WrongKeyTier,
)
from vera.errors import (
    DOC_BASE,
    TENANT_REASON_MALFORMED,
    TENANT_REASON_MISSING,
    TENANT_REASON_PHI_SHAPE,
)


# Each transport-layer subclass paired with its catalog ``code``. Codes
# were realigned to ``docs/error-discipline.md`` in Phase 1 PR 6 — auth
# went from ``"auth"`` → ``"invalid_api_key"``, timeout / network went to
# the shared ``"gate_timeout_or_network"`` bucket.
ALL_TRANSPORT_SUBCLASSES = [
    (VeraAuthError, "invalid_api_key"),
    (VeraRateLimitError, "rate_limit"),
    (VeraServerError, "server"),
    (VeraTimeoutError, "gate_timeout_or_network"),
    (VeraNetworkError, "gate_timeout_or_network"),
    (VeraValidationError, "validation"),
]


class TestHierarchy:
    @pytest.mark.parametrize("cls,_code", ALL_TRANSPORT_SUBCLASSES)
    def test_subclasses_inherit_from_vera_error(self, cls, _code):
        assert issubclass(cls, VeraError)
        assert issubclass(cls, Exception)

    @pytest.mark.parametrize("cls,_code", ALL_TRANSPORT_SUBCLASSES)
    def test_isinstance_resolves_to_base(self, cls, _code):
        err = cls("boom")
        assert isinstance(err, VeraError)
        assert isinstance(err, Exception)

    def test_base_class_can_be_raised_and_caught(self):
        with pytest.raises(VeraError):
            raise VeraError("base")

    @pytest.mark.parametrize("cls,_code", ALL_TRANSPORT_SUBCLASSES)
    def test_subclass_can_be_caught_as_base(self, cls, _code):
        with pytest.raises(VeraError):
            raise cls("boom")

    def test_veraclienterror_alias_resolves_to_validation(self):
        # The v0.3.x catch-all alias used by external integrations.
        assert VeraClientError is VeraValidationError

    @pytest.mark.parametrize(
        "cls",
        [
            PolicyBlock,
            PendingReview,
            WrongKeyTier,
            TenantMissingOrInvalid,
            ReviewerCredentialsInsufficient,
        ],
    )
    def test_new_classes_inherit_from_vera_error(self, cls):
        assert issubclass(cls, VeraError)


class TestErrorMessage:
    def test_str_includes_doc_url_with_code(self):
        err = VeraAuthError("invalid api key")
        rendered = str(err)
        assert "invalid api key" in rendered
        assert f"{DOC_BASE}/invalid_api_key" in rendered

    def test_str_includes_request_id_when_provided(self):
        err = VeraServerError("upstream 502", request_id="abc123")
        rendered = str(err)
        assert "abc123" in rendered
        assert "request_id=abc123" in rendered
        assert f"{DOC_BASE}/server" in rendered

    def test_str_omits_request_id_when_absent(self):
        err = VeraTimeoutError("read timeout")
        rendered = str(err)
        assert "request_id" not in rendered
        assert f"{DOC_BASE}/gate_timeout_or_network" in rendered

    @pytest.mark.parametrize("cls,code", ALL_TRANSPORT_SUBCLASSES)
    def test_each_subclass_uses_its_own_code(self, cls, code):
        err = cls("x")
        assert err.code == code
        assert f"/{code}" in str(err)

    def test_base_class_uses_generic_code(self):
        err = VeraError("generic")
        assert err.code == "vera_error"
        assert f"{DOC_BASE}/vera_error" in str(err)


class TestAttributes:
    def test_request_id_stored(self):
        err = VeraRateLimitError("slow down", request_id="req-1")
        assert err.request_id == "req-1"

    def test_request_id_defaults_to_none(self):
        err = VeraRateLimitError("slow down")
        assert err.request_id is None

    def test_status_code_stored(self):
        err = VeraAuthError("nope", status_code=401)
        assert err.status_code == 401

    def test_status_code_defaults_to_none(self):
        err = VeraAuthError("nope")
        assert err.status_code is None

    def test_both_attributes_round_trip(self):
        err = VeraValidationError(
            "bad payload", request_id="r-9", status_code=422
        )
        assert err.request_id == "r-9"
        assert err.status_code == 422
        rendered = str(err)
        assert "bad payload" in rendered
        assert "r-9" in rendered
        assert f"{DOC_BASE}/validation" in rendered


class TestTemplateFields:
    """Every error MUST carry the four-field template per docs/error-discipline.md."""

    @pytest.mark.parametrize(
        "cls",
        [
            VeraError,
            VeraAuthError,
            VeraRateLimitError,
            VeraServerError,
            VeraTimeoutError,
            VeraNetworkError,
            VeraValidationError,
            PolicyBlock,
            PendingReview,
            WrongKeyTier,
            TenantMissingOrInvalid,
            ReviewerCredentialsInsufficient,
        ],
    )
    def test_every_class_supplies_template_defaults(self, cls):
        # Construct with no args — defaults MUST populate every template field.
        err = cls()
        # All four must be non-empty strings or recognisable URLs.
        assert err.user_facing_reason
        assert err.developer_reason
        assert err.fix_url
        assert err.docs_url
        # docs_url canonicalised to the catalog base.
        assert err.docs_url.startswith(DOC_BASE + "/")

    def test_caller_overrides_take_precedence(self):
        err = VeraAuthError(
            "boom",
            user_facing_reason="custom user copy",
            developer_reason="custom dev copy",
            fix_url="https://example.com/fix",
        )
        assert err.user_facing_reason == "custom user copy"
        assert err.developer_reason == "custom dev copy"
        assert err.fix_url == "https://example.com/fix"

    def test_message_falls_back_into_developer_reason(self):
        # The v0.3.x convention was that the positional message described
        # the technical condition. Preserve that semantic — message MUST
        # be reachable via ``developer_reason`` when none is supplied.
        err = VeraServerError("upstream 502")
        assert err.developer_reason == "upstream 502"


class TestToDict:
    def test_base_to_dict_round_trips_template(self):
        err = VeraAuthError(
            "boom",
            request_id="abc",
            status_code=401,
            user_facing_reason="custom user",
            developer_reason="custom dev",
            fix_url="https://example.com/fix",
        )
        d = err.to_dict()
        assert d["code"] == "invalid_api_key"
        assert d["user_facing_reason"] == "custom user"
        assert d["developer_reason"] == "custom dev"
        assert d["fix_url"] == "https://example.com/fix"
        assert d["docs_url"] == f"{DOC_BASE}/invalid_api_key"
        assert d["request_id"] == "abc"
        assert d["status_code"] == 401

    def test_policy_block_to_dict_carries_typed_fields(self):
        err = PolicyBlock(
            reason="BAA required",
            citation="HIPAA § 164.504(e)",
            fix_url="https://app.usevera.xyz/baa",
            retryable=False,
            request_id="r1",
        )
        d = err.to_dict()
        assert d["code"] == "policy_block"
        assert d["reason"] == "BAA required"
        assert d["citation"] == "HIPAA § 164.504(e)"
        assert d["retryable"] is False
        assert d["fix_url"] == "https://app.usevera.xyz/baa"
        assert d["request_id"] == "r1"

    def test_pending_review_to_dict_carries_typed_fields(self):
        err = PendingReview(
            review_id="rev-1",
            expected_resolution="2026-05-23T12:00:00Z",
            webhook_url="https://example.com/hook",
            required_role="attending_physician",
            request_id="r2",
        )
        d = err.to_dict()
        assert d["code"] == "pending_review"
        assert d["review_id"] == "rev-1"
        assert d["expected_resolution"] == "2026-05-23T12:00:00Z"
        assert d["webhook_url"] == "https://example.com/hook"
        assert d["required_role"] == "attending_physician"

    def test_pending_review_to_dict_serializes_datetime(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
        err = PendingReview(review_id="rev-1", expected_resolution=dt)
        d = err.to_dict()
        assert d["expected_resolution"] == dt.isoformat()

    def test_wrong_key_tier_to_dict_carries_typed_fields(self):
        err = WrongKeyTier(
            key_kind="test",
            required="live",
            endpoint="POST /v1/gates/evaluate",
            request_id="r3",
        )
        d = err.to_dict()
        assert d["code"] == "wrong_key_tier"
        assert d["key_kind"] == "test"
        assert d["required"] == "live"
        assert d["endpoint"] == "POST /v1/gates/evaluate"

    def test_tenant_missing_to_dict(self):
        err = TenantMissingOrInvalid(reason=TENANT_REASON_MISSING)
        d = err.to_dict()
        assert d["code"] == "tenant_missing"
        assert d["reason"] == TENANT_REASON_MISSING
        assert d["provided_value"] is None

    def test_tenant_malformed_to_dict(self):
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED,
            provided_value="bad value with spaces",
        )
        d = err.to_dict()
        assert d["code"] == "tenant_invalid_or_phi"
        assert d["reason"] == TENANT_REASON_MALFORMED
        assert d["provided_value"] == "bad value with spaces"

    def test_tenant_phi_shape_redacts_provided_value(self):
        # PHI-shape values MUST NEVER round-trip through to_dict — otherwise
        # we'd defeat the heuristic by logging the very value we're trying
        # not to surface.
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_PHI_SHAPE,
            provided_value="123-45-6789",  # synthetic SSN-shape
        )
        d = err.to_dict()
        assert d["code"] == "tenant_invalid_or_phi"
        assert d["reason"] == TENANT_REASON_PHI_SHAPE
        assert d["provided_value"] is None

    def test_reviewer_credentials_insufficient_to_dict(self):
        err = ReviewerCredentialsInsufficient(
            review_id="rev-7",
            reviewer_role="md",
            required_role="dea_licensed_prescriber",
            request_id="r9",
        )
        d = err.to_dict()
        assert d["code"] == "reviewer_credentials_insufficient"
        assert d["review_id"] == "rev-7"
        assert d["reviewer_role"] == "md"
        assert d["required_role"] == "dea_licensed_prescriber"


class TestBackwardCompat:
    """The v0.3.x signature ``cls("message")`` MUST keep working."""

    @pytest.mark.parametrize(
        "cls",
        [
            VeraError,
            VeraAuthError,
            VeraRateLimitError,
            VeraServerError,
            VeraTimeoutError,
            VeraNetworkError,
            VeraValidationError,
        ],
    )
    def test_positional_message_only(self, cls):
        err = cls("boom")
        # The rendered string includes the message, exactly as v0.3.x did.
        assert "boom" in str(err)
        # request_id / status_code default to None.
        assert err.request_id is None
        assert err.status_code is None

    @pytest.mark.parametrize(
        "cls",
        [
            VeraError,
            VeraAuthError,
            VeraRateLimitError,
            VeraServerError,
            VeraTimeoutError,
            VeraNetworkError,
            VeraValidationError,
        ],
    )
    def test_positional_with_request_id_kwarg(self, cls):
        # The v0.3.x kwargs (``request_id``, ``status_code``) still work
        # exactly as before — new kwargs are additive.
        err = cls("boom", request_id="abc", status_code=500)
        assert err.request_id == "abc"
        assert err.status_code == 500
        assert "abc" in str(err)

    def test_no_args_construction_works(self):
        # A few v0.3.x integrations do ``raise VeraError()`` and rely on
        # defaults. Don't break them.
        err = VeraError()
        assert err.code == "vera_error"


class TestDomainErrorConstructors:
    """Smoke tests that each new domain class accepts its documented fields."""

    def test_policy_block_full_signature(self):
        err = PolicyBlock(
            reason="BAA expired",
            citation="HIPAA § 164.504(e)",
            fix_url="https://app.usevera.xyz/customers/abc",
            retryable=False,
            user_facing_reason="The Business Associate Agreement has expired.",
            developer_reason="customers.baa_signed_at past expiry window.",
            request_id="rid-1",
        )
        assert err.reason == "BAA expired"
        assert err.citation == "HIPAA § 164.504(e)"
        assert err.retryable is False
        assert err.fix_url == "https://app.usevera.xyz/customers/abc"
        assert "expired" in err.user_facing_reason
        assert err.request_id == "rid-1"

    def test_pending_review_full_signature(self):
        err = PendingReview(
            review_id="rev-42",
            expected_resolution="2026-05-23T12:00:00Z",
            webhook_url="https://customer.example/hook",
            required_role="attending_physician",
            request_id="rid-2",
        )
        assert err.review_id == "rev-42"
        assert err.expected_resolution == "2026-05-23T12:00:00Z"
        assert err.webhook_url == "https://customer.example/hook"
        assert err.required_role == "attending_physician"
        assert "rev-42" in err.developer_reason
        assert "attending_physician" in err.developer_reason

    def test_wrong_key_tier_full_signature(self):
        err = WrongKeyTier(
            key_kind="test",
            required="live",
            endpoint="POST /v1/gates/evaluate",
        )
        assert err.key_kind == "test"
        assert err.required == "live"
        assert err.endpoint == "POST /v1/gates/evaluate"
        assert "test" in err.developer_reason
        assert "live" in err.developer_reason

    def test_tenant_missing_default_signature(self):
        err = TenantMissingOrInvalid()
        assert err.reason == TENANT_REASON_MISSING
        assert err.code == "tenant_missing"
        assert "tenant_id" in err.developer_reason

    def test_reviewer_credentials_full_signature(self):
        err = ReviewerCredentialsInsufficient(
            review_id="rev-7",
            reviewer_role="md",
            required_role="dea_licensed_prescriber",
        )
        assert err.review_id == "rev-7"
        assert err.reviewer_role == "md"
        assert err.required_role == "dea_licensed_prescriber"
        assert "dea_licensed_prescriber" in err.developer_reason


class TestPHIShapeRedaction:
    """Belt-and-suspenders: ``provided_value`` MUST be redacted whenever it
    matches a PHI-shape pattern, regardless of the ``reason`` the caller
    supplied. The backend may classify an SSN-shaped value as
    ``tenant_malformed`` while the SDK would call it ``phi_shape_detected``;
    trusting the caller's reason here would leak the value into structured
    logs.
    """

    def test_tenant_malformed_with_phi_shape_value_is_redacted(self):
        # The headline regression: backend mis-classifies SSN-shaped value
        # as ``tenant_malformed``. The SDK MUST redact it before storing.
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED,
            provided_value="123-45-6789",
        )
        assert err.provided_value is None
        d = err.to_dict()
        assert d["provided_value"] is None
        # And the synthesised developer_reason MUST NOT leak it either.
        assert "123-45-6789" not in err.developer_reason

    @pytest.mark.parametrize(
        "phi_value",
        [
            "123-45-6789",           # SSN with dashes
            "123456789",             # SSN without dashes
            "1985-03-12",            # ISO DOB
            "03/12/1985",            # US DOB
            "03-12-1985",            # alt DOB
            "smith_19850312",        # name + number
            "John 1985",             # name + number with space
            "19850312_smith",        # number + name
        ],
    )
    def test_phi_shape_redacted_for_every_reason(self, phi_value):
        for reason in (TENANT_REASON_MISSING, TENANT_REASON_MALFORMED):
            err = TenantMissingOrInvalid(reason=reason, provided_value=phi_value)
            assert err.provided_value is None, (
                f"reason={reason!r} value={phi_value!r} should redact"
            )
            assert phi_value not in err.developer_reason

    def test_normal_tenant_id_is_not_redacted(self):
        # Genuine tenant IDs that don't match PHI shape MUST pass through —
        # over-redacting destroys diagnostic info but never PHI.
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED,
            provided_value="acme-corp-prod",
        )
        assert err.provided_value == "acme-corp-prod"


class TestDefensivePHILikelyRedaction:
    """Second layer: whitespace + digit combos are over-redacted.

    The strict :func:`_looks_like_phi` heuristic uses ``fullmatch`` against
    single-token shapes and misses multi-word strings like
    ``"John Doe 1972"`` or ``"Jane Smith DOB 03 14 1972"`` (the regex
    ``[A-Za-z]+[\\s_-]+\\d{4,}`` doesn't anchor a four-token sentence).
    Those exact strings are the most common PHI-leak shape: a developer
    pastes a patient name + DOB into a ``tenant=`` kwarg.

    The :func:`_is_likely_phi` defensive filter catches the gap by
    redacting ANY string with both whitespace AND a digit. Legitimate
    tenant ids never contain whitespace, so this costs nothing in
    practice.
    """

    @pytest.mark.parametrize(
        "phi_value",
        [
            "John Doe 1972",                 # name + DOB year
            "Jane Smith DOB 03 14 1972",     # name + labeled DOB
            "123 main street",               # number + words
            "Patient 12345 admitted",        # patient id sentence
            "DOB 1985",                      # labeled year
        ],
    )
    def test_whitespace_plus_digit_is_redacted_for_all_reasons(self, phi_value):
        for reason in (
            TENANT_REASON_MISSING,
            TENANT_REASON_MALFORMED,
            TENANT_REASON_PHI_SHAPE,
        ):
            err = TenantMissingOrInvalid(reason=reason, provided_value=phi_value)
            assert err.provided_value is None, (
                f"reason={reason!r} value={phi_value!r} should redact"
            )
            assert phi_value not in err.developer_reason, (
                f"reason={reason!r} leaked {phi_value!r} into developer_reason: "
                f"{err.developer_reason!r}"
            )
            d = err.to_dict()
            assert d["provided_value"] is None
            assert phi_value not in (d.get("developer_reason") or "")

    def test_malformed_emits_distinct_message_for_likely_phi(self):
        # When the defensive heuristic fires (not the strict one), the
        # synthesised developer_reason should call that out so the operator
        # knows the value was deliberately suppressed (vs. simply absent).
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED,
            provided_value="John Doe 1972",
        )
        assert "value redacted" in err.developer_reason
        assert "whitespace" in err.developer_reason
        assert "John" not in err.developer_reason
        assert "1972" not in err.developer_reason

    @pytest.mark.parametrize(
        "safe_value",
        [
            "acme_corp_us_east_2",   # snake_case + digit, no whitespace
            "tenant_42",             # short id + digit
            "us-east-1",             # region code
            "tenant",                # letters only
        ],
    )
    def test_normal_tenant_ids_without_whitespace_keep_diagnostic(self, safe_value):
        # Whitespace is the trip; pure alphanumeric + dash/underscore are
        # legitimate tenant ids and must keep diagnostic info. (Note:
        # values like ``customer-12345`` would be redacted by the strict
        # ``_looks_like_phi`` heuristic — ``[A-Za-z]+[_-]+\\d{4,}`` matches
        # them. That's the existing strict layer; we don't reverse it
        # here.)
        err = TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED,
            provided_value=safe_value,
        )
        assert err.provided_value == safe_value
        assert safe_value in err.developer_reason


class TestDocsUrlRenameWarnings:
    """The three transport classes whose ``code`` (and therefore the
    ``docs_url`` slug inside ``str(err)``) was renamed in Phase 1 PR 6
    MUST emit a one-shot DeprecationWarning per renamed class per process
    so log-grep / alerting operators see the change in CI before it shows
    up in alert noise.
    """

    def setup_method(self):
        from vera.errors import _reset_docs_url_rename_warnings

        _reset_docs_url_rename_warnings()

    @pytest.mark.parametrize(
        "cls,old_slug,new_slug",
        [
            (VeraAuthError, "auth", "invalid_api_key"),
            (VeraTimeoutError, "timeout", "gate_timeout_or_network"),
            (VeraNetworkError, "network", "gate_timeout_or_network"),
        ],
    )
    def test_str_emits_deprecation_warning_once(self, cls, old_slug, new_slug):
        from vera.errors import _reset_docs_url_rename_warnings

        _reset_docs_url_rename_warnings()
        err = cls("boom")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # First str() call -> exactly one warning.
            _ = str(err)
            # Second str() on the same instance -> no further warning.
            _ = str(err)
            # Third str() on a fresh instance of the SAME class -> still
            # no warning, because the dedupe is process-wide per class.
            _ = str(cls("again"))

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1, (
            f"expected exactly one DeprecationWarning for {cls.__name__}, "
            f"got {len(dep_warnings)}: {[str(w.message) for w in dep_warnings]}"
        )
        msg = str(dep_warnings[0].message)
        assert f"errors/{old_slug}" in msg
        assert f"errors/{new_slug}" in msg
        assert cls.__name__ in msg

    def test_warnings_are_independent_per_class(self):
        # VeraTimeoutError and VeraNetworkError both collapsed onto the
        # ``gate_timeout_or_network`` code — they MUST still warn
        # independently so operators see each rename.
        from vera.errors import _reset_docs_url_rename_warnings

        _reset_docs_url_rename_warnings()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = str(VeraTimeoutError("t"))
            _ = str(VeraNetworkError("n"))
        dep_warnings = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(dep_warnings) == 2
        messages = [str(w.message) for w in dep_warnings]
        assert any("VeraTimeoutError" in m for m in messages)
        assert any("VeraNetworkError" in m for m in messages)
