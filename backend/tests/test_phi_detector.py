"""Unit tests for ``app.services.phi_detector`` (Phase 1 PR 5, Stream C item C3).

One block per pattern family with positive + negative cases. Lean
false-positive is the explicit brief — over-blocking is a 422 the
customer can rename out of, under-blocking is a PHI leak. The negative
cases are the legitimate-opaque-ID controls (``acme_corp_v3``,
``cleveland_clinic`` etc.) that pilot SDKs already send today.

Performance guards (no catastrophic backtracking) live at the bottom.
"""
from __future__ import annotations

import time

import pytest

from app.services.phi_detector import PHIDetection, detect_phi_shape


# ── SSN ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "123-45-6789",
        "123_45_6789",
        "123 45 6789",
        "ssn_123-45-6789",
        "id123456789",  # raw 9-digit run
        "patient_987654321_v1",
    ],
)
def test_ssn_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "ssn"
    assert d.severity == "high"


@pytest.mark.parametrize(
    "value",
    [
        "acme_us_east_2",  # short digit
        "acme_corp",
        "rev_12345678",  # 8 digits — NOT 9, NOT a date (see other tests)
        "ssn_1234",  # too short
    ],
)
def test_ssn_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        # If it matched some other family, that's fine — but it must NOT be ssn.
        assert d.pattern_name != "ssn", (
            f"unexpected ssn match for {value!r}: {d!r}"
        )


# ── Dates ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected_pattern",
    [
        # YYYYMMDD inside an underscored ID — matches via the 8-digit numeric path
        ("patient_19720314", "date_ymd"),
        ("event_20001231", "date_ymd"),
        # YYYY-MM-DD with separators
        ("patient_1972-03-14", "date_ymd"),
        ("patient_1972_03_14", "date_ymd"),
        ("patient_2024/01/15", "date_ymd"),
        # MM-DD-YYYY with separators
        ("patient_03-14-1972", "date_mdy"),
        ("patient_03_14_1972", "date_mdy"),
        # DD-MMM-YYYY
        ("15-Mar-1972", "date_dmmmy"),
        ("3-jul-2024", "date_dmmmy"),
    ],
)
def test_date_matches(value, expected_pattern):
    d = detect_phi_shape(value)
    assert d.matched is True, f"expected date match for {value!r}"
    assert d.pattern_name == expected_pattern, (
        f"expected {expected_pattern} for {value!r}, got {d.pattern_name}"
    )
    assert d.severity == "high"


@pytest.mark.parametrize(
    "value",
    [
        "customer_2024",  # 4-digit year alone — not a date
        "acme_2024_q4",  # year-ish but no full date
        "rev_99999999",  # 8 digits but month=99 — implausible
        "rev_12999999",  # year=1299 — out of range
        "15-Foo-1972",  # invalid month abbrev
    ],
)
def test_date_does_not_match(value):
    d = detect_phi_shape(value)
    assert d.matched is False, f"unexpected match for {value!r}: {d!r}"


def test_date_yyyymmdd_eight_digits_only_matches_when_plausible():
    # ``customer_99999999`` is 8 consecutive digits but month=99 — the
    # numeric path discards it. The spec flagged ``customer_99999999`` as
    # "false positive acceptable — over-block"; we land on the cleaner
    # "no match" because the numeric date plausibility check is cheap.
    assert detect_phi_shape("customer_99999999").matched is False


# ── Name pair ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "John_Doe",
        "Jane Smith",
        "Mary-Lou-Smith",
        "First Last Tenant",
    ],
)
def test_name_pair_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "name_pair"
    assert d.severity == "high"


@pytest.mark.parametrize(
    "value",
    [
        "acme_corp",  # lowercase
        "acme",  # single token
        "Acme",  # single capitalized token
        "JOHN_DOE",  # ALL CAPS — not the [A-Z][a-z]+ pattern
    ],
)
def test_name_pair_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name != "name_pair", (
            f"unexpected name_pair match for {value!r}: {d!r}"
        )


# ── Address ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected_severity",
    [
        ("123 Main St", "medium"),  # both numbered + suffix
        ("42_Baker_Road", "medium"),
        ("1234_Maple", "medium"),  # numbered only
        ("home_Boulevard", "medium"),  # suffix only
    ],
)
def test_address_matches(value, expected_severity):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "address"
    assert d.severity == expected_severity


@pytest.mark.parametrize(
    "value",
    [
        "customer_42",  # digit but no capitalised neighbour
        "Stuart",  # contains "St" but as a name fragment, NOT word-bounded
        "First",  # contains "rst" — must NOT trip suffix patterns
        "Avenge",  # contains "Ave" prefix — must NOT trip
    ],
)
def test_address_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name != "address", (
            f"unexpected address match for {value!r}: {d!r}"
        )


# ── Phone ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "555-867-5309",
        "555_867_5309",
        "555 867 5309",
        "5558675309",  # raw 10-digit — falls through phone, eventually matches NPI / phone
        "+1-555-867-5309",
        "phone_555-867-5309_ext",
    ],
)
def test_phone_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    # Raw 10-digit may be reported as ``phone`` (the bounded form catches it).
    assert d.pattern_name in {"phone", "npi"}, (
        f"expected phone/npi for {value!r}, got {d.pattern_name}"
    )


@pytest.mark.parametrize(
    "value",
    [
        "customer_5309",  # only 4 digits
        "rev_12345",  # 5 digits
        "team_867_5309",  # 3+4 with separator but no leading 3-digit area
    ],
)
def test_phone_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name not in {"phone", "npi"}, (
            f"unexpected phone/npi match for {value!r}: {d!r}"
        )


# ── Email ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "john@example.com",
        "user.name+tag@sub.example.co.uk",
        "tenant_foo@bar.com",
    ],
)
def test_email_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "email"
    assert d.severity == "high"


@pytest.mark.parametrize(
    "value",
    [
        "customer_42_v3",
        "foo.bar.baz",  # no @
        "@example.com",  # no local part
    ],
)
def test_email_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name != "email", (
            f"unexpected email match for {value!r}: {d!r}"
        )


# ── MRN ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "MRN1234567",
        "mrn-1234567",
        "1234567MRN",
        "MRN_98765432",
    ],
)
def test_mrn_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "mrn"
    assert d.severity == "high"


@pytest.mark.parametrize(
    "value",
    [
        "customer_mrn_team",  # mrn token but no adjacent digits
        "MRN12",  # too few digits
        "team_with_mrn",
    ],
)
def test_mrn_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name != "mrn", (
            f"unexpected mrn match for {value!r}: {d!r}"
        )


# ── High-entropy ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "Js5g8Lpq2bN9",  # 12 mixed
        "Ab1Cd2Ef3Gh4Ij5",  # 15 mixed, no 10-digit run
    ],
)
def test_high_entropy_mixed_matches(value):
    d = detect_phi_shape(value)
    assert d.matched is True
    assert d.pattern_name == "high_entropy"
    assert d.severity == "medium"


def test_high_entropy_pure_hex_matches():
    # 12-char hex-y identifier — the spec's example.
    d = detect_phi_shape("a1b2c3d4e5f6")
    assert d.matched is True
    assert d.pattern_name == "high_entropy"


@pytest.mark.parametrize(
    "value",
    [
        "acme_corp_v3",  # lowercase + digit but only 12 chars in total,
                         # broken by underscores → no 12-char alnum run
        "acme",
        "tenant_42",
        "cleveland_clinic",
    ],
)
def test_high_entropy_does_not_match(value):
    d = detect_phi_shape(value)
    if d.matched:
        assert d.pattern_name != "high_entropy", (
            f"unexpected high_entropy match for {value!r}: {d!r}"
        )


# ── Empty / None passthrough ───────────────────────────────────────────────


@pytest.mark.parametrize("value", ["", None])
def test_empty_returns_no_match(value):
    d = detect_phi_shape(value)
    assert d.matched is False
    assert d.pattern_name is None
    # severity "low" sentinel on no-match so callers can branch safely.
    assert d.severity == "low"


# ── Legitimate opaque IDs — the regression set ─────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        # Pilot-SDK identifiers the PR brief explicitly calls out.
        "acme_corp_us_east_2",
        "cleveland_clinic",
        "customer_42",
        "tenant_42",
        "rev_99999999",  # 8 digits but month=99 — implausible
        "abridge",
        "scribe-v1",
        "prior_auth",
    ],
)
def test_opaque_ids_pass_through(value):
    """The most important test in the file: opaque IDs that real pilots
    use today MUST NOT match. Over-blocking these breaks every customer
    that already wired their tenant_id correctly."""
    d = detect_phi_shape(value)
    assert d.matched is False, (
        f"opaque pilot ID flagged as PHI: {value!r} → {d!r}"
    )


# ── Performance guard ──────────────────────────────────────────────────────


def test_no_catastrophic_backtracking_on_pathological_input():
    """Pathological inputs (huge alphanumeric strings) should stay flat.

    If any regex had nested quantifier ambiguity, this would blow up.
    We give it a generous 1.0s budget — a real regression would take
    multiple seconds even on a fast machine.
    """
    # 1024 chars of alternating shape that could trip a naive regex.
    pathological = ("aB1" * 350)[:1024]
    start = time.monotonic()
    for _ in range(50):
        detect_phi_shape(pathological)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, (
        f"detect_phi_shape too slow on pathological input: {elapsed:.3f}s "
        f"for 50 iterations of 1024-char input — possible regex "
        f"catastrophic backtracking"
    )


def test_detector_returns_dataclass_instance():
    """The contract: detector returns a ``PHIDetection`` dataclass.

    Callers (route handlers, future dashboard analytics) destructure
    ``.matched``, ``.pattern_name``, ``.severity`` — those attribute
    names + types are the public surface."""
    d = detect_phi_shape("acme_corp")
    assert isinstance(d, PHIDetection)
    assert isinstance(d.matched, bool)
    assert d.pattern_name is None or isinstance(d.pattern_name, str)
    assert d.severity in {"high", "medium", "low"}
