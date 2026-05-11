"""Tests for Redactor.medtech() one-call factory and BAA reminder.

Workstream B1 + B3: ergonomic ``Redactor.medtech()`` shortcut that
preloads the medtech starter schema, augments block_keys with HIPAA
Safe Harbor identifiers, includes MRN/DOB/IP patterns, and emits a
one-shot INFO log reminding customers to sign a BAA.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from vera.redaction import (
    FieldPolicy,
    FieldRule,
    Redactor,
    Schema,
    _MEDTECH_BLOCK_KEYS,
    _reset_baa_reminder_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_baa_flag():
    """Ensure the once-per-process BAA flag is reset around every test
    in this module — keeps tests order-independent."""
    _reset_baa_reminder_for_tests()
    yield
    _reset_baa_reminder_for_tests()


# ---------------------------------------------------------------------------
# Factory shape
# ---------------------------------------------------------------------------

class TestMedtechFactoryShape:
    def test_medtech_factory_returns_redactor(self):
        """Returns a Redactor instance with the medtech schema wired up."""
        r = Redactor.medtech()
        assert isinstance(r, Redactor)
        assert r.schema is not None
        assert isinstance(r.schema, Schema)

    def test_medtech_uses_starter_schema_by_default(self):
        """The default schema is the medtech starter — sanity check fields."""
        r = Redactor.medtech()
        # A handful of canonical fields from medtech_starter_schema().
        for fname in ("patient_id", "patient_name", "mrn", "notes", "dob"):
            assert fname.lower() in r.schema._fields_lower, (
                f"expected starter schema to declare {fname!r}"
            )
        # Deny-by-default for unmapped fields — critical HIPAA property.
        assert r.schema.unmapped_policy == FieldPolicy.REDACT

    def test_medtech_block_keys_include_hipaa_identifiers(self):
        """HIPAA Safe Harbor identifiers must be in block_keys (lower-cased)."""
        r = Redactor.medtech()
        # block_keys is stored lower-cased; check several canonical names.
        for k in ("mrn", "dob", "patient_name", "ssn", "address", "phone",
                  "email", "ip_address", "medical_record_number", "icd10_code"):
            assert k in r.block_keys, f"expected {k!r} in block_keys"

    def test_medtech_patterns_include_mrn_dob_ip(self):
        """Default-pass patterns include the medtech extras."""
        r = Redactor.medtech()
        names = {name for name, _ in r.patterns}
        for needed in ("mrn", "dob", "ipv4", "ipv6"):
            assert needed in names, (
                f"expected pattern {needed!r} in default pass — got {sorted(names)}"
            )


# ---------------------------------------------------------------------------
# Customization
# ---------------------------------------------------------------------------

class TestMedtechCustomization:
    def test_medtech_with_custom_schema(self):
        """Caller-supplied schema overrides the starter."""
        custom = Schema(
            fields={"only_field": FieldRule(FieldPolicy.PASSTHROUGH)},
            unmapped_policy=FieldPolicy.REDACT,
        )
        r = Redactor.medtech(schema=custom)
        assert r.schema is custom
        # Starter-only fields should NOT be present in the custom schema.
        assert "patient_id" not in r.schema._fields_lower

    def test_medtech_extra_block_keys_merged(self):
        """extra_block_keys are merged with the HIPAA defaults."""
        r = Redactor.medtech(extra_block_keys={"custom_phi"})
        assert "custom_phi" in r.block_keys
        # Defaults still present.
        assert "mrn" in r.block_keys
        assert "password" in r.block_keys

        # And the custom block_key actually redacts a value.
        out = r.serialize_args((), {"custom_phi": "leaks"})
        assert out["kwargs"]["custom_phi"] == "[REDACTED]"
        assert "leaks" not in out["kwargs"]["custom_phi"]

    def test_medtech_extra_patterns_merged(self):
        """extra_patterns are appended to the default pass."""
        custom_pat = re.compile(r"\bCID-\d+\b")
        r = Redactor.medtech(extra_patterns=[("custom_id", custom_pat)])
        names = {name for name, _ in r.patterns}
        assert "custom_id" in names

        # And the pattern actually fires on a matching value. Pick a key the
        # starter schema does NOT recognize so it falls into unmapped→REDACT.
        # Instead, test the pattern directly through serialize() on a string.
        out = r.serialize("trace CID-12345 here")
        assert "CID-12345" not in out
        assert "custom_id" in out


# ---------------------------------------------------------------------------
# BAA reminder (B3)
# ---------------------------------------------------------------------------

class TestBaaReminder:
    def test_baa_reminder_logged_once(self, caplog):
        """Only one BAA reminder is emitted regardless of how many times
        Redactor.medtech() is called."""
        _reset_baa_reminder_for_tests()
        with caplog.at_level(logging.INFO, logger="vera.redaction"):
            Redactor.medtech()
            Redactor.medtech()
            Redactor.medtech()

        baa_records = [
            rec for rec in caplog.records
            if "Business Associate Agreement" in rec.message
        ]
        assert len(baa_records) == 1, (
            f"expected exactly one BAA reminder, got {len(baa_records)}: "
            f"{[r.message for r in baa_records]}"
        )

        # After reset, the next call logs again.
        caplog.clear()
        _reset_baa_reminder_for_tests()
        with caplog.at_level(logging.INFO, logger="vera.redaction"):
            Redactor.medtech()
        baa_records2 = [
            rec for rec in caplog.records
            if "Business Associate Agreement" in rec.message
        ]
        assert len(baa_records2) == 1

    def test_baa_reminder_uses_null_handler_by_default(self):
        """Library logging norm: module logger has a NullHandler so the
        message does not auto-print to stderr in customer prod logs unless
        they configure logging."""
        mod_logger = logging.getLogger("vera.redaction")
        assert any(
            isinstance(h, logging.NullHandler) for h in mod_logger.handlers
        ), (
            "expected NullHandler attached to vera.redaction logger; "
            f"got handlers={mod_logger.handlers!r}"
        )


# ---------------------------------------------------------------------------
# Defense-in-depth
# ---------------------------------------------------------------------------

class TestDefenseInDepth:
    def test_medtech_block_keys_override_passthrough_schema(self):
        """Even if a caller's schema marks ``patient_name`` PASSTHROUGH,
        the medtech block_keys override and redact the value.

        This is the documented Phase 2 precedence rule: block_keys > schema.
        """
        bad_schema = Schema(
            fields={
                "patient_name": FieldRule(FieldPolicy.PASSTHROUGH),
            },
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor.medtech(schema=bad_schema)
        out = r.serialize_args((), {"patient_name": "Sarah Johnson"})
        # Block_keys wins: PHI is replaced.
        assert "Sarah" not in json.dumps(out)
        assert "Johnson" not in json.dumps(out)
        assert out["kwargs"]["patient_name"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Headline: synthetic patient encounter round-trip
# ---------------------------------------------------------------------------

class TestSyntheticPatientRoundTrip:
    """Realistic patient encounter through ``Redactor.medtech()`` —
    zero PHI substrings must remain in the serialized output."""

    PATIENT = {
        "patient_id": "PT-7842931",  # opaque, not PHI
        "patient_name": "Sarah Johnson",
        "dob": "03/14/1972",
        "mrn": "MRN-04823917",
        "notes": (
            "Patient Sarah Johnson, MRN MRN-04823917, presented to ED on "
            "03/14/2026 with shortness of breath. Spouse John Johnson "
            "called from 555-123-4567."
        ),
        "address": "123 Main St, Springfield, MA 01103",
        "phone": "555-123-4567",
        "email": "sarah.j@example.com",
        "ip_address": "192.168.1.42",
    }

    PHI_SUBSTRINGS = [
        "Sarah Johnson",
        "John Johnson",
        "03/14/1972",
        "03/14/2026",
        "MRN-04823917",
        "555-123-4567",
        "sarah.j@example.com",
        "123 Main St",
        "Springfield",
        "192.168.1.42",
    ]

    def test_medtech_synthetic_patient_round_trip(self):
        r = Redactor.medtech()
        out = r.serialize(self.PATIENT)

        # JSON-serializable on the output side — the audit pipeline always
        # JSON-encodes the redacted shape.
        blob = json.dumps(out)
        for phi in self.PHI_SUBSTRINGS:
            assert phi not in blob, (
                f"PHI leaked: {phi!r} in serialized output {blob!r}"
            )

        # Defense-in-depth: ``patient_id`` is also in the medtech block_keys,
        # so even though the schema says PASSTHROUGH the opaque ID is
        # redacted. This is the conservative HIPAA-first default — customers
        # who need the opaque ID can pass a custom schema and exclude
        # ``patient_id`` from ``extra_block_keys`` (or build their own
        # Redactor).
        assert "PT-7842931" not in blob

        # And the output is a real dict shape (decorators index nested fields).
        assert isinstance(out, dict)
        assert set(out.keys()) == set(self.PATIENT.keys())


# ---------------------------------------------------------------------------
# Free-text PHI handling
# ---------------------------------------------------------------------------

class TestFreeTextPHI:
    def test_medtech_free_text_in_notes_redacted(self):
        """``notes`` is REDACT in the starter schema — wholesale replacement."""
        r = Redactor.medtech()
        out = r.serialize({
            "notes": "Patient Sarah Johnson presented with shortness of breath.",
        })
        assert "Sarah Johnson" not in out["notes"]
        # REDACT wholesale: the entire field is replaced with the tagged token.
        assert out["notes"] == "[REDACTED:notes]"

    def test_medtech_free_text_in_unmapped_field(self):
        """Unmapped key with deny-by-default → fully redacted (no PHI leak)."""
        r = Redactor.medtech()
        out = r.serialize({
            "random_observation": "patient name is Sarah Johnson",
        })
        # Unmapped → REDACT under unmapped_policy.
        assert "Sarah" not in out["random_observation"]
        assert "Johnson" not in out["random_observation"]
        assert "REDACTED" in out["random_observation"]
