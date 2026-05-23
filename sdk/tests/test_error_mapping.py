"""Tests for the httpx-layer status + body ``code`` → branded error mapping.

Phase 1 PR 6 Stream D2 — :func:`vera.client.wrap_httpx_error` now reads
the backend's JSON error envelope and dispatches on ``body['code']``
before falling back to status-class mapping. These tests mock httpx
responses and assert the right branded class fires for each row of the
mapping table in the PR description.

The Phase 2 backend code paths (``baa_required``, ``policy_block``,
``reviewer_credentials_insufficient``, ...) don't ship yet — these tests
prove the SDK mapping is ready so that when the backend lands the
envelope, no SDK release is needed.
"""

from __future__ import annotations

import httpx
import pytest

import vera.client as client_mod
from vera import (
    PendingReview,
    PolicyBlock,
    ReviewerCredentialsInsufficient,
    TenantMissingOrInvalid,
    VeraAuthError,
    VeraClient,
    VeraError,
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraValidationError,
    WrongKeyTier,
)
from vera.errors import (
    TENANT_REASON_MALFORMED,
    TENANT_REASON_MISSING,
    TENANT_REASON_PHI_SHAPE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sync(monkeypatch) -> VeraClient:
    """Sync client with retry budget shrunk so failure tests don't sleep."""
    monkeypatch.setattr(client_mod, "MAX_RETRIES", 1)
    monkeypatch.setattr(client_mod, "RETRY_BACKOFF_BASE", 0.0)
    return VeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )


def _patch_transport(c, handler):
    c._client._transport = httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Body ``code`` → branded class dispatch
# ---------------------------------------------------------------------------


class TestBodyCodeDispatch:
    """Each row in the PR-description mapping table fires the right class."""

    def test_403_baa_required_raises_policy_block(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "baa_required",
            "reason": "BAA required for live actions",
            "citation": "HIPAA § 164.504(e)",
            "fix_url": "https://app.vera.io/api-keys?create=1",
            "retryable": False,
            "detail": "BAA missing",
        }
        _patch_transport(c, lambda req: httpx.Response(403, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        err = ei.value
        assert err.reason == "BAA required for live actions"
        assert err.citation == "HIPAA § 164.504(e)"
        assert err.fix_url == "https://app.vera.io/api-keys?create=1"
        assert err.retryable is False
        assert err.status_code == 403
        c.close()

    def test_403_baa_expired_raises_policy_block(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "baa_expired",
            "reason": "BAA expired",
            "citation": "HIPAA § 164.504(e)",
            "fix_url": "https://app.vera.io/customers/abc",
            "retryable": False,
        }
        _patch_transport(c, lambda req: httpx.Response(403, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        assert ei.value.reason == "BAA expired"
        assert "abc" in ei.value.fix_url
        c.close()

    def test_403_wrong_key_tier_raises_wrong_key_tier(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "wrong_key_tier",
            "key_kind": "test",
            "required": "live",
            "endpoint": "POST /v1/gates/evaluate",
            "detail": "wrong key tier",
        }
        _patch_transport(c, lambda req: httpx.Response(403, json=body))
        with pytest.raises(WrongKeyTier) as ei:
            c.record_action(action_name="x")
        err = ei.value
        assert err.key_kind == "test"
        assert err.required == "live"
        assert err.endpoint == "POST /v1/gates/evaluate"
        assert err.status_code == 403
        c.close()

    def test_403_reviewer_credentials_insufficient(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "reviewer_credentials_insufficient",
            "review_id": "rev-7",
            "reviewer_role": "md",
            "required_role": "dea_licensed_prescriber",
            "detail": "role mismatch",
        }
        _patch_transport(c, lambda req: httpx.Response(403, json=body))
        with pytest.raises(ReviewerCredentialsInsufficient) as ei:
            c.record_action(action_name="x")
        err = ei.value
        assert err.review_id == "rev-7"
        assert err.reviewer_role == "md"
        assert err.required_role == "dea_licensed_prescriber"
        c.close()

    def test_422_policy_block_raises_policy_block(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "policy_block",
            "reason": "controlled-substance DEA check failed",
            "citation": "DEA 21 CFR § 1306.04",
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        assert ei.value.citation == "DEA 21 CFR § 1306.04"
        assert ei.value.status_code == 422
        c.close()

    def test_422_tenant_missing_raises_tenant(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {"code": "tenant_missing", "detail": "tenant_id required"}
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(TenantMissingOrInvalid) as ei:
            c.record_action(action_name="x")
        assert ei.value.reason == TENANT_REASON_MISSING
        assert ei.value.code == "tenant_missing"
        c.close()

    def test_422_tenant_malformed_raises_tenant(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "tenant_malformed",
            "provided_value": "tenant with spaces",
            "detail": "bad tenant_id",
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(TenantMissingOrInvalid) as ei:
            c.record_action(action_name="x")
        assert ei.value.reason == TENANT_REASON_MALFORMED
        assert ei.value.provided_value == "tenant with spaces"
        assert ei.value.code == "tenant_invalid_or_phi"
        c.close()

    def test_422_phi_shape_redacts_provided_value(self, monkeypatch):
        c = _make_sync(monkeypatch)
        # If the backend echoes the offending value, the SDK MUST redact it
        # before storing — logging it would defeat the heuristic.
        body = {
            "code": "phi_shape_in_tenant_id",
            "provided_value": "123-45-6789",
            "detail": "tenant_id matches PHI shape",
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(TenantMissingOrInvalid) as ei:
            c.record_action(action_name="x")
        assert ei.value.reason == TENANT_REASON_PHI_SHAPE
        # provided_value MUST be redacted when reason is phi_shape_detected.
        assert ei.value.provided_value is None
        c.close()

    def test_401_unauthorized_code_raises_vera_auth(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {"code": "unauthorized", "detail": "no auth"}
        _patch_transport(c, lambda req: httpx.Response(401, json=body))
        with pytest.raises(VeraAuthError) as ei:
            c.record_action(action_name="x")
        assert ei.value.status_code == 401
        c.close()

    def test_401_invalid_api_key_raises_vera_auth(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {"code": "invalid_api_key", "detail": "key rejected"}
        _patch_transport(c, lambda req: httpx.Response(401, json=body))
        with pytest.raises(VeraAuthError) as ei:
            c.record_action(action_name="x")
        # body's detail surfaces into developer_reason.
        assert "key rejected" in ei.value.developer_reason
        c.close()


# ---------------------------------------------------------------------------
# Fallback paths — unknown code, missing code, 5xx, etc.
# ---------------------------------------------------------------------------


class TestStatusCodeFallback:
    def test_403_unknown_code_falls_back_to_vera_auth(self, monkeypatch):
        # An unknown ``code`` MUST NOT crash — fall through to status mapping.
        c = _make_sync(monkeypatch)
        body = {"code": "something_new_we_dont_know", "detail": "future error"}
        _patch_transport(c, lambda req: httpx.Response(403, json=body))
        with pytest.raises(VeraAuthError) as ei:
            c.record_action(action_name="x")
        assert ei.value.status_code == 403
        c.close()

    def test_403_no_body_code_falls_back_to_vera_auth(self, monkeypatch):
        c = _make_sync(monkeypatch)
        # Backend that doesn't (yet) emit ``code`` — still works.
        _patch_transport(c, lambda req: httpx.Response(403, json={"detail": "no"}))
        with pytest.raises(VeraAuthError):
            c.record_action(action_name="x")
        c.close()

    def test_422_no_body_code_falls_back_to_validation(self, monkeypatch):
        c = _make_sync(monkeypatch)
        _patch_transport(c, lambda req: httpx.Response(422, json={"detail": "bad"}))
        with pytest.raises(VeraValidationError) as ei:
            c.record_action(action_name="x")
        # body's detail surfaces into developer_reason.
        assert "bad" in ei.value.developer_reason
        c.close()

    def test_429_no_body_code_falls_back_to_rate_limit(self, monkeypatch):
        c = _make_sync(monkeypatch)
        _patch_transport(c, lambda req: httpx.Response(429, json={"detail": "slow"}))
        with pytest.raises(VeraRateLimitError):
            c.record_action(action_name="x")
        c.close()

    def test_503_5xx_carries_developer_reason_with_body(self, monkeypatch):
        c = _make_sync(monkeypatch)
        _patch_transport(
            c, lambda req: httpx.Response(503, json={"detail": "service down"})
        )
        with pytest.raises(VeraServerError) as ei:
            c.record_action(action_name="x")
        err = ei.value
        assert err.status_code == 503
        # ``developer_reason`` surfaces the body so customers can correlate.
        assert "service down" in err.developer_reason
        c.close()

    def test_empty_body_does_not_crash(self, monkeypatch):
        c = _make_sync(monkeypatch)
        _patch_transport(c, lambda req: httpx.Response(500))
        with pytest.raises(VeraServerError):
            c.record_action(action_name="x")
        c.close()

    def test_non_json_body_does_not_crash(self, monkeypatch):
        c = _make_sync(monkeypatch)
        _patch_transport(
            c,
            lambda req: httpx.Response(500, content=b"<html>oops</html>"),
        )
        with pytest.raises(VeraServerError):
            c.record_action(action_name="x")
        c.close()

    def test_non_dict_json_body_does_not_crash(self, monkeypatch):
        c = _make_sync(monkeypatch)
        # FastAPI's stock validation handler can emit a list of errors —
        # the SDK must not blow up trying to ``body.get("code")``.
        _patch_transport(
            c, lambda req: httpx.Response(422, json=["err1", "err2"])
        )
        with pytest.raises(VeraValidationError):
            c.record_action(action_name="x")
        c.close()


# ---------------------------------------------------------------------------
# X-Request-ID propagation onto branded errors
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    def test_request_id_on_policy_block(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {"code": "policy_block", "reason": "blocked", "citation": "x"}
        _patch_transport(
            c,
            lambda req: httpx.Response(
                422, json=body, headers={"X-Request-ID": "rid-policy"}
            ),
        )
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        assert ei.value.request_id == "rid-policy"
        c.close()

    def test_request_id_on_wrong_key_tier(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {"code": "wrong_key_tier", "key_kind": "test", "required": "live"}
        _patch_transport(
            c,
            lambda req: httpx.Response(
                403, json=body, headers={"X-Request-ID": "rid-tier"}
            ),
        )
        with pytest.raises(WrongKeyTier) as ei:
            c.record_action(action_name="x")
        assert ei.value.request_id == "rid-tier"
        c.close()

    def test_request_id_lowercase_header(self, monkeypatch):
        # Some proxies normalise headers — the SDK already handled this for
        # transport errors; verify it also works for branded domain ones.
        c = _make_sync(monkeypatch)
        body = {"code": "tenant_missing"}
        _patch_transport(
            c,
            lambda req: httpx.Response(
                422, json=body, headers={"x-request-id": "lc-rid"}
            ),
        )
        with pytest.raises(TenantMissingOrInvalid) as ei:
            c.record_action(action_name="x")
        assert ei.value.request_id == "lc-rid"
        c.close()


# ---------------------------------------------------------------------------
# Direct wrap_httpx_error tests — guard the public helper directly so PR 8
# (the @vera.gate decorator) can rely on it without spinning up a VeraClient.
# ---------------------------------------------------------------------------


class TestWrapHttpxError:
    def _make_status_error(
        self, status: int, body: dict | list | None = None, headers: dict | None = None
    ) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", "http://localhost/v1/actions")
        response = httpx.Response(
            status, request=request, json=body if body is not None else {},
            headers=headers or {},
        )
        return httpx.HTTPStatusError(
            f"HTTP {status}", request=request, response=response
        )

    def test_wrap_dispatches_policy_block(self):
        exc = self._make_status_error(
            422,
            body={"code": "policy_block", "reason": "blocked", "citation": "x"},
        )
        out = client_mod.wrap_httpx_error(exc)
        assert isinstance(out, PolicyBlock)
        assert out.reason == "blocked"

    def test_wrap_dispatches_pending_review(self):
        # ``pending_review`` is in the dispatch table for future use — the
        # SDK will surface it when the backend emits the code (today, the
        # async ruling path is unsealed).
        exc = self._make_status_error(
            422,
            body={
                "code": "pending_review",
                "review_id": "rev-42",
                "required_role": "attending_physician",
            },
        )
        out = client_mod.wrap_httpx_error(exc)
        assert isinstance(out, PendingReview)
        assert out.review_id == "rev-42"
        assert out.required_role == "attending_physician"

    def test_wrap_returns_unchanged_for_non_httpx_exception(self):
        e = ValueError("not httpx")
        assert client_mod.wrap_httpx_error(e) is e

    def test_wrap_routes_network_error(self):
        out = client_mod.wrap_httpx_error(httpx.ConnectError("dns fail"))
        assert isinstance(out, VeraNetworkError)

    def test_wrap_propagates_request_id_to_branded_error(self):
        exc = self._make_status_error(
            422,
            body={"code": "policy_block", "reason": "blocked"},
            headers={"X-Request-ID": "abc-xyz"},
        )
        out = client_mod.wrap_httpx_error(exc)
        assert isinstance(out, VeraError)
        assert out.request_id == "abc-xyz"


# ---------------------------------------------------------------------------
# Polish fixes (PR-194 review)
# ---------------------------------------------------------------------------


class TestPolicyBlockRichDeveloperReason:
    """When the backend doesn't supply ``developer_reason`` but DOES supply
    ``reason`` + ``citation``, the PolicyBlock constructor builds a rich
    ``"<reason> (citation=<citation>)"`` developer_reason. The backend
    ``detail`` field (FastAPI's default error string) MUST NOT clobber it.
    """

    def test_rich_developer_reason_preserved_when_backend_only_sets_detail(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "policy_block",
            "reason": "BAA required",
            "citation": "HIPAA § 164.504(e)",
            "detail": "BAA missing",  # FastAPI's terse default
            # no explicit developer_reason
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        # The rich format wins, NOT the bare "BAA missing" detail.
        assert "BAA required" in ei.value.developer_reason
        assert "HIPAA § 164.504(e)" in ei.value.developer_reason
        assert "citation=" in ei.value.developer_reason
        c.close()

    def test_explicit_backend_developer_reason_wins(self, monkeypatch):
        c = _make_sync(monkeypatch)
        body = {
            "code": "policy_block",
            "reason": "BAA required",
            "citation": "HIPAA § 164.504(e)",
            "developer_reason": "customers.baa_signed_at past expiry; tenant=acme",
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        assert "customers.baa_signed_at" in ei.value.developer_reason
        c.close()


class TestDeveloperReasonTruncation:
    """5xx bodies (HTML stack traces, reflected headers) MUST be truncated
    before landing in ``developer_reason`` → Sentry → structured logs.
    """

    def test_oversized_5xx_body_is_truncated(self, monkeypatch):
        c = _make_sync(monkeypatch)
        # 10KB body (well over the 2048-char cap).
        huge = "X" * 10_000
        _patch_transport(
            c,
            lambda req: httpx.Response(500, json={"detail": huge}),
        )
        with pytest.raises(VeraServerError) as ei:
            c.record_action(action_name="x")
        reason = ei.value.developer_reason
        # Truncated to the documented cap, with the marker present.
        assert len(reason) <= 2048
        assert reason.endswith("...[truncated]")
        c.close()

    def test_oversized_developer_reason_field_is_truncated(self, monkeypatch):
        c = _make_sync(monkeypatch)
        huge = "Y" * 10_000
        body = {
            "code": "policy_block",
            "reason": "blocked",
            "citation": "ref",
            "developer_reason": huge,
        }
        _patch_transport(c, lambda req: httpx.Response(422, json=body))
        with pytest.raises(PolicyBlock) as ei:
            c.record_action(action_name="x")
        assert len(ei.value.developer_reason) <= 2048
        assert ei.value.developer_reason.endswith("...[truncated]")
        c.close()


class TestXRequestIdCaseInsensitive:
    """``httpx.Headers`` is case-insensitive — one ``.get`` handles every
    casing an upstream proxy might emit. Asserting this explicitly so the
    test passes for the right reason (not because of dead fallback code).
    """

    @pytest.mark.parametrize(
        "header_name",
        ["X-Request-ID", "x-request-id", "X-REQUEST-ID", "x-Request-Id"],
    )
    def test_x_request_id_case_insensitive(self, monkeypatch, header_name):
        c = _make_sync(monkeypatch)
        _patch_transport(
            c,
            lambda req: httpx.Response(
                401, json={"detail": "no"}, headers={header_name: "rid-case"}
            ),
        )
        with pytest.raises(VeraAuthError) as ei:
            c.record_action(action_name="x")
        assert ei.value.request_id == "rid-case", (
            f"header {header_name!r} should match case-insensitively"
        )
        c.close()
