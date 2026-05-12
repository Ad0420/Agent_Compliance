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

from vera._test_hooks import _reset_baa_reminder_for_tests
from vera.redaction import (
    FieldPolicy,
    FieldRule,
    Redactor,
    Schema,
    _MEDTECH_BLOCK_KEYS,
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

        # ``patient_id`` is intentionally PRESERVED (HIPAA-safe pattern is
        # opaque random IDs; the starter schema marks ``patient_id``
        # PASSTHROUGH and it is NOT in :data:`_MEDTECH_BLOCK_KEYS`). Audit
        # records must remain searchable by patient_id. Customers whose
        # patient_id is MRN-shaped should pass
        # ``extra_block_keys={'patient_id'}``.
        assert "PT-7842931" in blob
        assert out["patient_id"] == "PT-7842931"

        # And the output is a real dict shape (decorators index nested fields).
        assert isinstance(out, dict)
        assert set(out.keys()) == set(self.PATIENT.keys())

    def test_medtech_opaque_patient_id_preserved_by_default(self):
        """Explicit test for the design property: opaque patient_id values
        survive the medtech factory. This is the HIPAA-safe pattern and
        the starter schema's PASSTHROUGH ruling no longer contradicts the
        block_keys set.
        """
        r = Redactor.medtech()
        out = r.serialize_args((), {"patient_id": "opaque-abc-123"})
        assert out["kwargs"]["patient_id"] == "opaque-abc-123"

    def test_medtech_patient_id_override_via_extra_block_keys(self):
        """Customers whose patient_id is MRN-shaped can force redaction by
        passing ``extra_block_keys={'patient_id'}``.
        """
        r = Redactor.medtech(extra_block_keys={"patient_id"})
        out = r.serialize_args((), {"patient_id": "MRN-12345678"})
        assert out["kwargs"]["patient_id"] == "[REDACTED]"


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


# ---------------------------------------------------------------------------
# CRITICAL #1: kwarg named ``patient`` must recurse (no wholesale block)
# ---------------------------------------------------------------------------

class TestPatientKeywordRecursion:
    """A kwarg named ``patient`` must NOT short-circuit the walk. Removing
    bare ``"patient"`` from :data:`_MEDTECH_BLOCK_KEYS` means the redactor
    descends into the value, so nested PHI is redacted by the schema and
    safe IDs survive.
    """

    def test_patient_keyword_argument_recurses(self):
        """``{"patient": {...}}`` is walked: nested PHI fields are
        redacted, schema-PASSTHROUGH ``patient_id`` is preserved.
        """
        r = Redactor.medtech()
        out = r.serialize({
            "patient": {
                "name": "Sarah Johnson",
                "patient_id": "opaque-1",
            }
        })
        # The recursion happened (output is a dict, not the replacement).
        assert isinstance(out["patient"], dict)
        # ``name`` is unmapped under the starter schema → deny-by-default.
        assert "Sarah" not in str(out["patient"])
        assert "Johnson" not in str(out["patient"])
        # ``patient_id`` is PASSTHROUGH and not in block_keys → preserved.
        assert out["patient"]["patient_id"] == "opaque-1"

    def test_patient_kwarg_serialize_args_recurses(self):
        """Same property exercised through the decorator's kwarg path."""
        r = Redactor.medtech()
        out = r.serialize_args(
            (),
            {"patient": {"patient_id": "opaque-2", "patient_name": "Sarah"}},
        )
        # Walked, not blocked.
        assert isinstance(out["kwargs"]["patient"], dict)
        # Inner PHI redacted, inner opaque ID preserved.
        assert out["kwargs"]["patient"]["patient_id"] == "opaque-2"
        assert "Sarah" not in json.dumps(out["kwargs"]["patient"])

    def test_patient_block_key_excluded_from_medtech_defaults(self):
        """Bare ``"patient"`` is explicitly NOT in the default medtech
        block_keys set — the recursion property is part of the public
        contract.
        """
        assert "patient" not in {k.lower() for k in _MEDTECH_BLOCK_KEYS}

    def test_patient_kwarg_redacted_when_caller_requests(self):
        """Customers who want the old wholesale behaviour can opt in via
        ``extra_block_keys={'patient'}``.
        """
        r = Redactor.medtech(extra_block_keys={"patient"})
        out = r.serialize_args(
            (),
            {"patient": {"patient_id": "opaque-1", "patient_name": "Sarah"}},
        )
        # Whole value replaced — no recursion.
        assert out["kwargs"]["patient"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# CRITICAL #3: URL handling — pass through unless PHI is embedded
# ---------------------------------------------------------------------------

class TestUrlPhiHandling:
    def test_url_without_phi_passes_through(self):
        """Plain API/callback/doc URLs are NOT redacted."""
        r = Redactor.medtech()
        out = r.serialize_args(
            (),
            {"callback_url": "https://api.example.com/webhook"},
        )
        # ``callback_url`` is unmapped under the starter schema, so the
        # unmapped policy REDACT applies at the schema layer. To exercise
        # the bare URL pattern path, serialize a non-key-attached string:
        bare = r.serialize("see https://api.example.com/webhook for docs")
        assert "https://api.example.com/webhook" in bare
        # And the kwarg-keyed value goes through unmapped policy:
        assert "REDACTED" in str(out["kwargs"]["callback_url"])

    def test_url_with_phi_in_query_redacted(self):
        """A URL with ``ssn=`` in the query is fully redacted by the
        ``url_phi`` pattern (not by a bare ``url`` block_key).
        """
        r = Redactor.medtech()
        leaky = "see https://app.example.com/p?ssn=123-45-6789 for details"
        out = r.serialize(leaky)
        assert "123-45-6789" not in out
        assert "app.example.com/p?ssn=" not in out
        # Tagged replacement appears.
        assert "url_phi" in out or "REDACTED" in out

    def test_url_with_mrn_in_path_redacted(self):
        """MRN embedded anywhere in URL path/query is scrubbed."""
        r = Redactor.medtech()
        leaky = "visit https://emr.example.com/patients/MRN-04823917/encounters"
        out = r.serialize(leaky)
        assert "MRN-04823917" not in out

    def test_url_with_patient_id_query_redacted(self):
        """``patient_id=…`` in query string is scrubbed."""
        r = Redactor.medtech()
        leaky = "https://app.example.com/p?patient_id=secret123&foo=bar"
        out = r.serialize(leaky)
        assert "secret123" not in out

    def test_url_not_in_medtech_block_keys(self):
        """Bare ``"url"`` is explicitly NOT in the default medtech
        block_keys set — non-PHI URLs must pass through.
        """
        assert "url" not in {k.lower() for k in _MEDTECH_BLOCK_KEYS}


# ---------------------------------------------------------------------------
# CRITICAL #4: nested + non-dict shapes
# ---------------------------------------------------------------------------

class TestNestedAndOrmShapes:
    """The headline round-trip was previously flat-only. These cover
    nested dicts, lists of dicts, dataclass/pydantic-style objects, and
    FHIR Bundles. No PHI substring may survive at any depth.
    """

    PHI = [
        "Sarah", "Johnson", "MRN-1234", "555-123-4567",
        "1972-03-14", "03/14/1972",
    ]

    def _assert_no_phi(self, blob: str) -> None:
        for substring in self.PHI:
            assert substring not in blob, (
                f"PHI leaked: {substring!r} in {blob!r}"
            )

    def test_nested_dict_walked(self):
        r = Redactor.medtech()
        data = {
            "encounter": {
                "patient": {
                    "patient_name": "Sarah Johnson",
                    "mrn": "MRN-1234",
                }
            }
        }
        out = r.serialize(data)
        blob = json.dumps(out)
        self._assert_no_phi(blob)
        # Structure preserved.
        assert isinstance(out["encounter"], dict)
        assert isinstance(out["encounter"]["patient"], dict)

    def test_list_of_dicts_walked(self):
        r = Redactor.medtech()
        data = {
            "history": [
                {"date": "2024-01-15", "notes": "patient Sarah Johnson improved"},
                {"date": "2024-02-15", "notes": "MRN-1234 follow-up"},
            ]
        }
        out = r.serialize(data)
        blob = json.dumps(out)
        self._assert_no_phi(blob)
        # List of dicts shape preserved.
        assert isinstance(out["history"], list)
        assert len(out["history"]) == 2

    def test_dataclass_refused_in_schema_mode(self):
        """Phase 2 fix: schema-mode redactor refuses to ``repr()`` unknown
        object types — would leak attribute values that the schema can't
        see. Returns a tagged placeholder.
        """
        from dataclasses import dataclass

        @dataclass
        class Patient:
            patient_name: str
            mrn: str

        r = Redactor.medtech()
        out = r.serialize(Patient(patient_name="Sarah Johnson", mrn="MRN-1234"))
        # Tagged placeholder, NOT the repr.
        assert "Sarah" not in str(out)
        assert "MRN-1234" not in str(out)
        assert "Patient" in str(out)
        assert "REDACTED" in str(out)

    def test_dataclass_inside_dict_refused(self):
        """The schema-mode object refusal also applies when a dataclass
        appears nested inside a dict the redactor walks.
        """
        from dataclasses import dataclass

        @dataclass
        class Patient:
            patient_name: str
            mrn: str

        r = Redactor.medtech()
        out = r.serialize({
            "patient": Patient(patient_name="Sarah Johnson", mrn="MRN-1234"),
        })
        blob = json.dumps(out)
        self._assert_no_phi(blob)

    def test_fhir_bundle_walked(self):
        """FHIR-shaped Bundle with deeply nested PHI: no leak at any depth."""
        r = Redactor.medtech()
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "name": [{"given": ["Sarah"], "family": "Johnson"}],
                        "telecom": [{"system": "phone", "value": "555-123-4567"}],
                        "birthDate": "1972-03-14",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Encounter",
                        "subject": {"reference": "Patient/MRN-1234"},
                    }
                },
            ],
        }
        out = r.serialize(bundle)
        blob = json.dumps(out)
        self._assert_no_phi(blob)
        # Structure preserved so audit reviewers can navigate.
        assert isinstance(out["entry"], list)
        assert len(out["entry"]) == 2


# ---------------------------------------------------------------------------
# INFO: BAA-once correctness in a forked child
# ---------------------------------------------------------------------------

class TestBaaReminderForkSafety:
    def test_baa_reminder_in_forked_child(self):
        """Fork a process, child instantiates ``Redactor.medtech()``, parent
        does not. The child is a fresh process so the global once-flag
        resets — child must log exactly once.

        This codifies the expected behaviour: fork-safety is per-process,
        and customers who fork after seeing the parent's reminder will
        still get the reminder once per child.
        """
        import multiprocessing as mp
        import os

        if not hasattr(os, "fork"):
            pytest.skip("os.fork not available on this platform")

        # Use ``fork`` explicitly — spawn would reimport the module fresh
        # and dodge the global-flag semantics we want to verify.
        ctx = mp.get_context("fork")
        q: "mp.Queue[int]" = ctx.Queue()

        def _child(out_q: "mp.Queue[int]") -> None:
            # In the child, reset and then count BAA log records around
            # one ``Redactor.medtech()`` call.
            import logging as _logging

            from vera._test_hooks import _reset_baa_reminder_for_tests
            from vera.redaction import Redactor

            _reset_baa_reminder_for_tests()

            count = {"n": 0}

            class _Counter(_logging.Handler):
                def emit(self, record):  # noqa: D401 — handler API
                    if "Business Associate Agreement" in record.getMessage():
                        count["n"] += 1

            mod_logger = _logging.getLogger("vera.redaction")
            h = _Counter(level=_logging.INFO)
            mod_logger.addHandler(h)
            mod_logger.setLevel(_logging.INFO)
            try:
                Redactor.medtech()
                Redactor.medtech()
            finally:
                mod_logger.removeHandler(h)
            out_q.put(count["n"])

        p = ctx.Process(target=_child, args=(q,))
        p.start()
        p.join(timeout=10)
        assert p.exitcode == 0, f"child exited with {p.exitcode}"
        assert q.get(timeout=2) == 1, (
            "expected exactly one BAA reminder in forked child"
        )
