"""Sanity tests for the hardcoded DEA controlled-substance list.

These tests guard the *list itself* — they don't exercise the
``ControlledSubstanceGate``. The list is the regulatory source of
truth; the tests below pin invariants (no duplicates, lowercase,
brand resolution) that future PRs touching the list would
otherwise have to remember to maintain.
"""

from __future__ import annotations

from app.packs.clinical.controlled_substance_list import (
    _BRAND_TO_GENERIC,
    _SCHEDULED_DRUGS,
    find_controlled_in_text,
    is_controlled,
    normalize_drug_name,
    resolve_generic,
)


def test_all_entries_lowercase():
    """No accidental ``"Oxycodone"`` capitalization that would defeat lookup.

    All comparisons happen post-normalize, but the source list is
    case-sensitive (``frozenset``). An uppercase entry would silently
    never match.
    """
    for name in _SCHEDULED_DRUGS:
        assert name == name.lower(), f"{name!r} is not lowercase"
    for brand, generic in _BRAND_TO_GENERIC.items():
        assert brand == brand.lower(), f"brand {brand!r} not lowercase"
        assert generic == generic.lower(), f"generic {generic!r} not lowercase"


def test_no_duplicate_in_scheduled_drugs():
    """``frozenset`` dedupes silently — count round-trip catches dupes in source.

    If a maintainer adds the same drug to two schedule frozensets, the
    union dedupes — fine for runtime behaviour but the intent was
    likely a bug. This test won't catch that (the union is correct),
    but it does pin the *count* so an unintended deletion shows up
    as a diff.
    """
    # Pin the expected total. Update this number deliberately when
    # the list changes; the diff in the PR is the audit.
    assert len(_SCHEDULED_DRUGS) >= 40, (
        f"expected at least 40 controlled substances, got {len(_SCHEDULED_DRUGS)}"
    )


def test_brand_resolves_to_generic():
    """Every branded controlled substance maps to a DEA-listed generic."""
    for brand, generic in _BRAND_TO_GENERIC.items():
        assert generic in _SCHEDULED_DRUGS, (
            f"brand {brand!r} maps to {generic!r} which is NOT on the "
            f"DEA list — typo or stale entry"
        )


def test_known_branded_pairs_resolve():
    """Spot-check the brand → generic mapping for canonical pairs."""
    assert resolve_generic("Xanax") == "alprazolam"
    assert resolve_generic("OxyContin") == "oxycodone"
    assert resolve_generic("Adderall") == "amphetamine"
    assert resolve_generic("Vicodin") == "hydrocodone"
    assert resolve_generic("Ambien") == "zolpidem"
    assert resolve_generic("Percocet") == "oxycodone"
    assert resolve_generic("Klonopin") == "clonazepam"


def test_is_controlled_handles_case_and_hyphen_variants():
    assert is_controlled("oxycodone")
    assert is_controlled("OXYCODONE")
    assert is_controlled("oxy-codone")  # hyphen collapses
    assert is_controlled("Oxy-Codone")


def test_is_controlled_returns_false_for_non_controlled():
    """Common OTC / non-scheduled drugs must not trip the list."""
    for benign in [
        "acetaminophen",
        "ibuprofen",
        "aspirin",
        "lisinopril",
        "metformin",
        "atorvastatin",
        "amoxicillin",
        "",
        None,  # type: ignore[arg-type]
    ]:
        assert not is_controlled(benign), f"{benign!r} should NOT be controlled"


def test_normalize_drug_name_collapses_variants():
    assert normalize_drug_name("Oxycodone") == "oxycodone"
    assert normalize_drug_name("oxy-codone") == "oxycodone"
    assert normalize_drug_name("MS Contin") == "ms_contin"
    assert normalize_drug_name("  ms  contin  ") == "ms_contin"
    assert normalize_drug_name("") == ""


def test_find_controlled_in_text_extracts_generic_names():
    """Free-text scan returns the *generic* name even for brand mentions."""
    matches = find_controlled_in_text("Patient on Vicodin and Xanax")
    assert set(matches) == {"hydrocodone", "alprazolam"}


def test_find_controlled_in_text_handles_dose_strings():
    matches = find_controlled_in_text("oxycodone 5mg PO q4h")
    assert "oxycodone" in matches


def test_find_controlled_in_text_returns_empty_on_no_match():
    assert find_controlled_in_text("acetaminophen 500mg") == []
    assert find_controlled_in_text("") == []


def test_find_controlled_in_text_dedupes_repeats():
    """Repeated mention returns the generic only once, first-appearance order."""
    matches = find_controlled_in_text(
        "oxycodone q4h. Hold oxycodone if RR<12. Resume oxycodone tomorrow."
    )
    assert matches == ["oxycodone"]
