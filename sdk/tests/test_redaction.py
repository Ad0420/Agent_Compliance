"""Unit tests for vera.redaction.Redactor + decorator wiring."""

from __future__ import annotations

import re
import time

from unittest.mock import MagicMock

from vera import Redactor, get_default_redactor, set_default_redactor
from vera.decorator import audit, set_default_client


# ---------------------------------------------------------------------------
# Pattern coverage
# ---------------------------------------------------------------------------

class TestPatternCoverage:
    def setup_method(self):
        self.r = Redactor()

    def test_ssn_redacted(self):
        out = self.r.serialize("user ssn is 123-45-6789 here")
        assert "123-45-6789" not in out
        assert "ssn" in out  # named replacement

    def test_credit_card_with_valid_luhn_redacted(self):
        # 4111-1111-1111-1111 is the canonical Luhn-valid Visa test card.
        out = self.r.serialize("card 4111-1111-1111-1111 charged")
        assert "4111-1111-1111-1111" not in out
        assert "credit_card" in out

    def test_credit_card_without_valid_luhn_kept(self):
        # 1234-5678-9012-3456 fails Luhn.
        out = self.r.serialize("order 1234-5678-9012-3456 placed")
        # The credit_card pattern should NOT have fired. But other patterns
        # must not redact it either (these are pure digit blocks; no SSN
        # match because the segments are 4-4-4-4 not 3-2-4).
        assert "1234-5678-9012-3456" in out
        assert "credit_card" not in out

    def test_email_redacted(self):
        out = self.r.serialize("contact alice@example.com please")
        assert "alice@example.com" not in out
        assert "email" in out

    def test_phone_us_redacted(self):
        out = self.r.serialize("call +1 (415) 555-1234 today")
        assert "555-1234" not in out
        assert "phone_us" in out

    def test_aws_access_key_redacted(self):
        out = self.r.serialize("AKIAIOSFODNN7EXAMPLE leaked")
        assert "AKIAIOSFODNN7EXAMPLE" not in out
        assert "aws_access_key" in out

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36"
        out = self.r.serialize(f"token={jwt}")
        assert jwt not in out
        assert "jwt" in out

    def test_bearer_token_redacted(self):
        out = self.r.serialize("Authorization: Bearer abcdef0123456789ABCDEF")
        assert "abcdef0123456789ABCDEF" not in out
        assert "bearer_token" in out

    def test_hex_secret_redacted(self):
        # 32+ hex chars triggers it.
        secret = "a" * 40
        out = self.r.serialize(f"hash={secret}")
        assert secret not in out
        assert "hex_secret" in out


# ---------------------------------------------------------------------------
# Container & key handling
# ---------------------------------------------------------------------------

class TestContainerHandling:
    def setup_method(self):
        self.r = Redactor()

    def test_nested_dict_redacts_ssn_and_keeps_name(self):
        out = self.r.serialize({"user": {"ssn": "123-45-6789", "name": "Alice"}})
        assert isinstance(out, dict)
        # block_keys default contains "ssn" — so the value is replaced wholesale.
        assert out["user"]["ssn"] == "[REDACTED]"
        assert out["user"]["name"] == "Alice"

    def test_block_keys_case_insensitive(self):
        out = self.r.serialize({"Password": "hunter2"})
        assert out["Password"] == "[REDACTED]"

    def test_block_keys_in_kwargs(self):
        # serialize_args treats block_keys at the top level.
        result = self.r.serialize_args((), {"API_KEY": "xyz", "name": "alice"})
        assert result["kwargs"]["API_KEY"] == "[REDACTED]"
        assert result["kwargs"]["name"] == "alice"

    def test_list_of_mixed_types(self):
        out = self.r.serialize(
            ["plain", "ssn 123-45-6789", 42, {"email": "x@y.com"}]
        )
        assert isinstance(out, list)
        assert out[0] == "plain"
        assert "123-45-6789" not in out[1]
        assert out[2] == "42"
        # 'email' isn't in default block_keys but the value matches the email pattern.
        assert "x@y.com" not in out[3]["email"]

    def test_tuple_preserved(self):
        out = self.r.serialize(("a", "ssn 123-45-6789"))
        assert isinstance(out, tuple)
        assert out[0] == "a"
        assert "123-45-6789" not in out[1]

    def test_serialize_args_shape(self):
        result = self.r.serialize_args(("a", 1), {"k": "v"})
        assert set(result.keys()) == {"args", "kwargs"}
        assert result["args"] == ["a", "1"]
        assert result["kwargs"] == {"k": "v"}


# ---------------------------------------------------------------------------
# Truncation, custom serializer, defensive behaviour
# ---------------------------------------------------------------------------

class TestRedactorBehaviour:
    def test_max_length_truncates(self):
        r = Redactor(max_length=20)
        out = r.serialize("x" * 100)
        assert out.endswith("...[truncated]")
        assert len(out) == 20 + len("...[truncated]")

    def test_max_length_does_not_truncate_short_values(self):
        r = Redactor(max_length=20)
        assert r.serialize("short") == "short"

    def test_custom_serializer_short_circuits(self):
        def hook(value):
            if isinstance(value, dict) and "magic" in value:
                return "MAGIC"
            return None

        r = Redactor(custom_serializer=hook)
        # Dict with the magic key uses the hook.
        assert r.serialize({"magic": "anything"}) == "MAGIC"
        # Other values fall through to the default path.
        assert r.serialize("plain") == "plain"

    def test_custom_serializer_returning_none_falls_through(self):
        r = Redactor(custom_serializer=lambda v: None)
        assert r.serialize("plain") == "plain"

    def test_custom_serializer_exception_falls_through(self):
        def bad(_):
            raise RuntimeError("boom")

        r = Redactor(custom_serializer=bad)
        # Should still serialize without raising.
        assert r.serialize("ok") == "ok"

    def test_redaction_never_raises_on_pathological_input(self):
        r = Redactor()
        # A long, alternating string is the kind of input that can trigger
        # catastrophic backtracking on poorly-written regexes. Confirm we
        # complete in well under a second.
        evil = ("a1" * 5000) + "!"
        start = time.perf_counter()
        out = r.serialize(evil)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        assert isinstance(out, str)

    def test_unstringifiable_object_does_not_raise(self):
        class Bomb:
            def __repr__(self):
                raise RuntimeError("no repr")

            def __str__(self):
                raise RuntimeError("no str")

        r = Redactor()
        # Should fall back to the replacement string instead of crashing.
        assert r.serialize(Bomb()) == "[REDACTED]"

    def test_custom_replacement(self):
        r = Redactor(replacement="<scrubbed>")
        out = r.serialize({"password": "x"})
        assert out["password"] == "<scrubbed>"

    def test_custom_block_keys(self):
        r = Redactor(block_keys={"x"})
        out = r.serialize({"x": "secret", "y": "fine"})
        assert out["x"] == "[REDACTED]"
        assert out["y"] == "fine"

    def test_custom_patterns(self):
        # User-provided pattern only — disables defaults.
        r = Redactor(patterns=[("zip", re.compile(r"\b\d{5}\b"))])
        out = r.serialize("zip 94110")
        assert "94110" not in out
        assert "zip" in out

    def test_none_and_primitives(self):
        r = Redactor()
        assert r.serialize(None) == "None"
        assert r.serialize(42) == "42"
        assert r.serialize(True) == "True"


# ---------------------------------------------------------------------------
# Decorator integration
# ---------------------------------------------------------------------------

class TestDecoratorIntegration:
    def teardown_method(self):
        # Reset module-level state between tests.
        set_default_client(None)
        set_default_redactor(Redactor())

    def test_audit_uses_redactor_block_keys(self):
        mock_client = MagicMock()

        @audit(redactor=Redactor(block_keys={"x"}), client=mock_client)
        def f(x):
            return "ok"

        f(x="secret")

        call_kwargs = mock_client.enqueue_action.call_args[1]
        assert call_kwargs["input_data"]["kwargs"]["x"] == "[REDACTED]"

    def test_audit_default_redactor_redacts_ssn(self):
        mock_client = MagicMock()

        @audit(client=mock_client)
        def process(note):
            return "done"

        process("ssn 123-45-6789 noted")
        call_kwargs = mock_client.enqueue_action.call_args[1]
        # The arg becomes a string in input_data["args"].
        assert "123-45-6789" not in call_kwargs["input_data"]["args"][0]

    def test_audit_redacts_return_value(self):
        mock_client = MagicMock()

        @audit(client=mock_client)
        def returns_secret():
            return {"password": "hunter2", "ok": True}

        returns_secret()
        call_kwargs = mock_client.enqueue_action.call_args[1]
        rv = call_kwargs["outcome"]["return_value"]
        assert rv["password"] == "[REDACTED]"
        # 'ok' isn't a block key — its boolean value is preserved as a string.
        assert rv["ok"] == "True"

    def test_set_default_redactor_changes_behaviour(self):
        mock_client = MagicMock()
        set_default_redactor(Redactor(block_keys={"weird_key"}))

        @audit(client=mock_client)
        def f(weird_key=None, password=None):
            return None

        f(weird_key="boom", password="hunter2")
        kw = mock_client.enqueue_action.call_args[1]["input_data"]["kwargs"]
        assert kw["weird_key"] == "[REDACTED]"
        # Default block_keys were replaced; "password" no longer triggers a
        # block_key match. The value contains no pattern, so it stays as-is.
        assert kw["password"] == "hunter2"

    def test_get_default_redactor_returns_instance(self):
        assert isinstance(get_default_redactor(), Redactor)
