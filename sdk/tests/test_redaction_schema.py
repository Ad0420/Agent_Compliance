"""Tests for schema-driven redaction (A6 hardening).

The motivation for these tests is the dual-voice review's finding that
regex-only redaction is "false safety" — patient names and free-text
PHI leak through any regex pass. Schema-driven mode lets a customer
declare which fields are PHI and how each should be handled, with
deny-by-default for unmapped fields.

The headline test is :func:`test_synthetic_patient_encounter_zero_phi`,
which feeds a realistic patient encounter dict through the starter
schema and asserts no PHI substrings remain in the serialized output.
"""

from __future__ import annotations

import json
import logging

import pytest

from vera.redaction import (
    FieldPolicy,
    FieldRule,
    Redactor,
    Schema,
)


# ---------------------------------------------------------------------------
# Per-policy behavior
# ---------------------------------------------------------------------------

class TestSchemaPolicies:
    def test_schema_mode_passthrough(self):
        """PASSTHROUGH-tagged values pass through unchanged (modulo regex)."""
        schema = Schema(
            fields={"patient_id": FieldRule(FieldPolicy.PASSTHROUGH)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"patient_id": "PT-12345"})
        assert out["patient_id"] == "PT-12345"

    def test_schema_mode_redact(self):
        """REDACT replaces the value regardless of content."""
        schema = Schema(
            fields={"patient_name": FieldRule(FieldPolicy.REDACT)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"patient_name": "Jane Doe"})
        # Tagged with the field name so audit logs are greppable.
        assert out["patient_name"] == "[REDACTED:patient_name]"
        assert "Jane Doe" not in out["patient_name"]

    def test_schema_mode_pattern(self):
        """PATTERN applies the named regex; non-matching values pass through."""
        schema = Schema(
            fields={"mrn": FieldRule(FieldPolicy.PATTERN, pattern_name="mrn")},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"mrn": "MRN-12345678"})
        assert "MRN-12345678" not in out["mrn"]
        assert "mrn" in out["mrn"]  # tag visible

        # Non-matching value: should pass through unchanged (no pattern match,
        # and the default regex pass doesn't fire on a bare opaque string).
        out2 = r.serialize({"mrn": "not-an-mrn"})
        assert out2["mrn"] == "not-an-mrn"


# ---------------------------------------------------------------------------
# Unmapped-field handling
# ---------------------------------------------------------------------------

class TestUnmappedPolicy:
    def test_schema_unmapped_field_denied_by_default(self):
        """Unmapped fields are REDACTed by default (deny-by-default)."""
        schema = Schema(fields={"patient_id": FieldRule(FieldPolicy.PASSTHROUGH)})
        r = Redactor(schema=schema)
        out = r.serialize({"patient_id": "PT-1", "notes": "Patient John Q"})
        assert out["patient_id"] == "PT-1"
        # ``notes`` is not in the schema; default unmapped_policy=REDACT
        # replaces it wholesale.
        assert "John Q" not in out["notes"]
        assert "REDACTED" in out["notes"]

    def test_schema_unmapped_policy_passthrough(self):
        """unmapped_policy=PASSTHROUGH lets unmapped fields through."""
        schema = Schema(
            fields={"patient_name": FieldRule(FieldPolicy.REDACT)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"patient_name": "Jane", "extra": "anything-here"})
        assert out["patient_name"] == "[REDACTED:patient_name]"
        assert out["extra"] == "anything-here"


# ---------------------------------------------------------------------------
# Backwards compat
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    def test_schema_does_not_break_existing_no_schema_mode(self):
        """Redactor() with no schema must behave EXACTLY as before."""
        r = Redactor()
        # Pre-A6 behaviour: SSN is redacted via regex pass; nested dict is
        # walked; block_keys (e.g. password) replaces value.
        out = r.serialize(
            {
                "user": {"ssn": "123-45-6789", "name": "Alice"},
                "password": "hunter2",
            }
        )
        assert out["user"]["ssn"] == "[REDACTED]"  # block_keys hit
        assert out["user"]["name"] == "Alice"  # untouched
        assert out["password"] == "[REDACTED]"

    def test_existing_block_keys_still_work(self):
        """Sanity: block_keys behaviour unchanged with no schema."""
        r = Redactor()
        out = r.serialize_args((), {"api_key": "xyz", "name": "alice"})
        assert out["kwargs"]["api_key"] == "[REDACTED]"
        assert out["kwargs"]["name"] == "alice"


# ---------------------------------------------------------------------------
# Defense-in-depth: block_keys overrides schema
# ---------------------------------------------------------------------------

class TestDefenseInDepth:
    def test_block_keys_overrides_schema_passthrough(self):
        """A field in block_keys is redacted even if schema says PASSTHROUGH."""
        # ``api_key`` is in the default block_keys; even if a misguided
        # schema marks it PASSTHROUGH, block_keys must still win.
        schema = Schema(
            fields={"api_key": FieldRule(FieldPolicy.PASSTHROUGH)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"api_key": "sk-real-secret"})
        assert out["api_key"] == "[REDACTED]"

    def test_block_keys_overrides_in_serialize_args(self):
        """Same defense-in-depth rule applies to serialize_args kwargs."""
        schema = Schema(
            fields={"password": FieldRule(FieldPolicy.PASSTHROUGH)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize_args((), {"password": "hunter2"})
        assert out["kwargs"]["password"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Headline test: synthetic patient encounter, zero PHI
# ---------------------------------------------------------------------------

class TestSyntheticPatientEncounter:
    """Realistic patient encounter must round-trip with zero PHI leaks."""

    PATIENT_ENCOUNTER = {
        "patient_id": "PT-7842931",  # opaque ID — should pass through
        "patient_name": "Sarah Johnson",
        "dob": "03/14/1972",
        "mrn": "MRN-04823917",
        "icd10_code": "J45.909",
        "notes": (
            "Patient Sarah Johnson, MRN MRN-04823917, presented to ED on "
            "03/14/2026 with shortness of breath. PMH: asthma (J45.909). "
            "Spouse John Johnson called from 555-123-4567. Address 123 "
            "Main St, Springfield, MA. Email sarah.j@example.com."
        ),
        "ip_address": "192.168.1.42",
        "street_address": "123 Main St",
    }

    # PHI substrings that MUST NOT appear in the redacted output.
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

    def test_synthetic_patient_encounter_zero_phi(self):
        r = Redactor(schema=Redactor.medtech_starter_schema())
        out = r.serialize(self.PATIENT_ENCOUNTER)

        # Serialize to JSON for a complete substring sweep — catches PHI
        # leaks anywhere in the output regardless of nesting.
        blob = json.dumps(out)
        for phi in self.PHI_SUBSTRINGS:
            assert phi not in blob, f"PHI leaked: {phi!r} in {blob!r}"

        # patient_id is opaque — should still be visible (not PHI).
        assert "PT-7842931" in blob

    def test_free_text_pHI_in_notes_is_redacted(self):
        """Free-text PHI in ``notes`` must not leak — REDACTed wholesale."""
        r = Redactor(schema=Redactor.medtech_starter_schema())
        out = r.serialize(
            {
                "notes": (
                    "Patient Sarah Johnson presented with shortness of breath."
                ),
            }
        )
        assert "Sarah Johnson" not in out["notes"]
        # The whole field is REDACTed — surrounding context also gone.
        assert out["notes"] == "[REDACTED:notes]"


# ---------------------------------------------------------------------------
# serialize_args integration with schemas
# ---------------------------------------------------------------------------

class TestSerializeArgsWithSchema:
    def test_serialize_args_applies_schema_to_kwargs(self):
        """serialize_args routes kwargs through schema rules."""
        schema = Schema(
            fields={
                "patient_id": FieldRule(FieldPolicy.PASSTHROUGH),
                "notes": FieldRule(FieldPolicy.REDACT),
                "mrn": FieldRule(FieldPolicy.PATTERN, pattern_name="mrn"),
            },
            unmapped_policy=FieldPolicy.REDACT,
        )
        r = Redactor(schema=schema)

        out = r.serialize_args(
            (),
            {
                "patient_id": "PT-1",
                "notes": "Patient John presented with...",
                "mrn": "MRN-99887766",
                "extra": "anything",  # unmapped → REDACTed
            },
        )

        kw = out["kwargs"]
        assert kw["patient_id"] == "PT-1"
        # notes is REDACT — wholesale replacement, free text is gone.
        assert "John" not in kw["notes"]
        assert kw["notes"] == "[REDACTED:notes]"
        # mrn matches the named pattern — substring replaced.
        assert "MRN-99887766" not in kw["mrn"]
        # unmapped key is REDACTed.
        assert "anything" not in kw["extra"]


# ---------------------------------------------------------------------------
# Pattern-rule failure modes
# ---------------------------------------------------------------------------

class TestPatternRuleFailures:
    def test_pattern_lookup_unknown_name_fails_safely(self, caplog):
        """Unknown pattern_name → fail closed (REDACT) and log a WARN."""
        schema = Schema(
            fields={
                "field_x": FieldRule(
                    FieldPolicy.PATTERN, pattern_name="nope_does_not_exist"
                ),
            },
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)

        with caplog.at_level(logging.WARNING, logger="vera.redaction"):
            out = r.serialize({"field_x": "leaks-real-phi-here"})

        # The value must NOT leak — fail closed.
        assert "leaks-real-phi-here" not in out["field_x"]
        assert "REDACTED" in out["field_x"]
        # And we logged a WARN explaining why.
        assert any(
            "unknown pattern" in rec.message.lower() for rec in caplog.records
        ), f"expected WARN about unknown pattern, got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Starter schema shape
# ---------------------------------------------------------------------------

class TestMedtechStarterSchema:
    def test_medtech_starter_schema_shape(self):
        """The starter schema declares the canonical patient-encounter fields."""
        schema = Redactor.medtech_starter_schema()

        # Type sanity.
        assert isinstance(schema, Schema)
        assert schema.unmapped_policy == FieldPolicy.REDACT  # deny-by-default

        # Opaque IDs pass through.
        assert schema.fields["patient_id"].policy == FieldPolicy.PASSTHROUGH

        # Names cannot be safely scrubbed → REDACT.
        assert schema.fields["patient_name"].policy == FieldPolicy.REDACT

        # MRN → PATTERN with pattern_name="mrn".
        mrn_rule = schema.fields["mrn"]
        assert mrn_rule.policy == FieldPolicy.PATTERN
        assert mrn_rule.pattern_name == "mrn"

        # DOB → PATTERN with pattern_name="dob".
        dob_rule = schema.fields["dob"]
        assert dob_rule.policy == FieldPolicy.PATTERN
        assert dob_rule.pattern_name == "dob"

        # Free-text PHI → REDACT.
        assert schema.fields["notes"].policy == FieldPolicy.REDACT

        # Address → REDACT.
        assert schema.fields["street_address"].policy == FieldPolicy.REDACT

        # Every rule should carry a description for audit reviewers.
        for name, rule in schema.fields.items():
            assert rule.description, f"rule {name!r} has no description"


# ---------------------------------------------------------------------------
# Default pattern coverage for new medtech / network patterns
# ---------------------------------------------------------------------------

class TestNewDefaultPatterns:
    def test_default_pattern_pass_redacts_mrn(self):
        """MRN appears in the default pattern list — caught even without schema."""
        r = Redactor()
        out = r.serialize("Patient MRN-12345678 admitted")
        assert "MRN-12345678" not in out
        assert "mrn" in out

    def test_default_pattern_pass_redacts_dob(self):
        r = Redactor()
        out = r.serialize("DOB 03/14/1972 on file")
        assert "03/14/1972" not in out
        assert "dob" in out

    def test_default_pattern_pass_redacts_ipv4(self):
        r = Redactor()
        out = r.serialize("client ip 192.168.1.42 connected")
        assert "192.168.1.42" not in out
        assert "ipv4" in out

    def test_default_pattern_pass_redacts_ipv6(self):
        r = Redactor()
        out = r.serialize("client ip 2001:0db8:85a3:0000:0000:8a2e:0370:7334 connected")
        assert "2001:0db8:85a3:0000:0000:8a2e:0370:7334" not in out
        assert "ipv6" in out

    def test_icd10_NOT_in_default_pass(self):
        """ICD-10 is opt-in only — too noisy as a default."""
        r = Redactor()
        # "J45" matches the ICD-10 pattern but should not be redacted by
        # default — only via Schema with pattern_name="icd10".
        out = r.serialize("the J45 form arrived")
        assert "J45" in out, "icd10 should not run in the default regex pass"

    def test_icd10_available_via_schema_pattern(self):
        """ICD-10 IS available when a schema explicitly opts in."""
        schema = Schema(
            fields={
                "diagnosis": FieldRule(
                    FieldPolicy.PATTERN, pattern_name="icd10"
                ),
            },
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"diagnosis": "J45.909"})
        assert "J45.909" not in out["diagnosis"]


# ---------------------------------------------------------------------------
# Pattern + defense-in-depth interactions
# ---------------------------------------------------------------------------

class TestPatternDefenseInDepth:
    def test_pattern_field_still_runs_default_pass(self):
        """A PATTERN-tagged field still gets the default regex pass on top."""
        # Field is tagged PATTERN for ``mrn`` but the value also contains
        # a credit card. The default pass must still catch the CC.
        schema = Schema(
            fields={"data": FieldRule(FieldPolicy.PATTERN, pattern_name="mrn")},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize(
            {"data": "MRN-12345678 and card 4111-1111-1111-1111"}
        )
        assert "MRN-12345678" not in out["data"]
        assert "4111-1111-1111-1111" not in out["data"]
        assert "mrn" in out["data"]
        assert "credit_card" in out["data"]

    def test_passthrough_field_still_runs_default_pass(self):
        """PASSTHROUGH still runs the default regex pass — defense-in-depth."""
        schema = Schema(
            fields={"data": FieldRule(FieldPolicy.PASSTHROUGH)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema)
        out = r.serialize({"data": "ssn 123-45-6789 leaked"})
        # Schema says PASSTHROUGH but the SSN regex pass still fires.
        assert "123-45-6789" not in out["data"]
        assert "ssn" in out["data"]


# ---------------------------------------------------------------------------
# Schema rule_for fallback
# ---------------------------------------------------------------------------

class TestSchemaRuleFor:
    def test_rule_for_known_key_returns_declared_rule(self):
        rule = FieldRule(FieldPolicy.PASSTHROUGH, description="hi")
        schema = Schema(fields={"x": rule})
        assert schema.rule_for("x") is rule

    def test_rule_for_unknown_key_falls_back_to_unmapped_policy(self):
        schema = Schema(unmapped_policy=FieldPolicy.REDACT)
        rule = schema.rule_for("missing")
        assert rule.policy == FieldPolicy.REDACT
        assert "unmapped" in rule.description.lower()


# ---------------------------------------------------------------------------
# Quick smoke for a custom replacement with a schema
# ---------------------------------------------------------------------------

class TestCustomReplacementWithSchema:
    def test_custom_replacement_used_for_redact(self):
        """A non-bracketed custom replacement is used verbatim."""
        schema = Schema(
            fields={"x": FieldRule(FieldPolicy.REDACT)},
            unmapped_policy=FieldPolicy.PASSTHROUGH,
        )
        r = Redactor(schema=schema, replacement="<scrubbed>")
        out = r.serialize({"x": "secret"})
        # Non-bracketed replacement is used verbatim (no field-tag suffix).
        assert out["x"] == "<scrubbed>"
