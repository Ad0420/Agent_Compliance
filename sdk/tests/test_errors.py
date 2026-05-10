"""Tests for the branded exception hierarchy in :mod:`vera.errors`."""

import pytest

from vera import (
    VeraError,
    VeraAuthError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraNetworkError,
    VeraValidationError,
)
from vera.errors import DOC_BASE


ALL_SUBCLASSES = [
    (VeraAuthError, "auth"),
    (VeraRateLimitError, "rate_limit"),
    (VeraServerError, "server"),
    (VeraTimeoutError, "timeout"),
    (VeraNetworkError, "network"),
    (VeraValidationError, "validation"),
]


class TestHierarchy:
    @pytest.mark.parametrize("cls,_code", ALL_SUBCLASSES)
    def test_subclasses_inherit_from_vera_error(self, cls, _code):
        assert issubclass(cls, VeraError)
        assert issubclass(cls, Exception)

    @pytest.mark.parametrize("cls,_code", ALL_SUBCLASSES)
    def test_isinstance_resolves_to_base(self, cls, _code):
        err = cls("boom")
        assert isinstance(err, VeraError)
        assert isinstance(err, Exception)

    def test_base_class_can_be_raised_and_caught(self):
        with pytest.raises(VeraError):
            raise VeraError("base")

    @pytest.mark.parametrize("cls,_code", ALL_SUBCLASSES)
    def test_subclass_can_be_caught_as_base(self, cls, _code):
        with pytest.raises(VeraError):
            raise cls("boom")


class TestErrorMessage:
    def test_str_includes_doc_url_with_code(self):
        err = VeraAuthError("invalid api key")
        rendered = str(err)
        assert "invalid api key" in rendered
        assert f"{DOC_BASE}/auth" in rendered

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
        assert f"{DOC_BASE}/timeout" in rendered

    @pytest.mark.parametrize("cls,code", ALL_SUBCLASSES)
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
