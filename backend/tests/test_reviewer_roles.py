"""Phase 2 Wave 2C PR A4 — reviewer-role hierarchy unit tests.

The hierarchy is a pure function — no DB, no fixtures. The
fail-closed-on-unknown property is load-bearing per the plan: a typo
or unrecognised role string must NEVER pass, even when the gate didn't
pin a specific requirement.
"""

from __future__ import annotations

import pytest

from app.services.reviewer_roles import _ROLE_LEVELS, is_role_sufficient


class TestExactMatch:
    @pytest.mark.parametrize("role", sorted(_ROLE_LEVELS.keys()))
    def test_same_role_satisfies_itself(self, role: str) -> None:
        assert is_role_sufficient(role, role) is True


class TestHigherSatisfiesLower:
    def test_attending_satisfies_physician(self) -> None:
        assert is_role_sufficient("attending_physician", "physician") is True

    def test_dea_satisfies_attending(self) -> None:
        # DEA-authorized (40) outranks attending (30).
        assert is_role_sufficient("dea_authorized", "attending_physician") is True

    def test_compliance_officer_satisfies_dea(self) -> None:
        assert is_role_sufficient("compliance_officer", "dea_authorized") is True

    def test_medical_director_satisfies_anything_below(self) -> None:
        for required in ["nurse", "physician", "attending_physician", "dea_authorized"]:
            assert is_role_sufficient("medical_director", required) is True


class TestLowerInsufficient:
    def test_nurse_cannot_satisfy_physician(self) -> None:
        assert is_role_sufficient("nurse", "physician") is False

    def test_physician_cannot_satisfy_dea(self) -> None:
        assert is_role_sufficient("physician", "dea_authorized") is False

    def test_attending_cannot_satisfy_medical_director(self) -> None:
        assert is_role_sufficient("attending_physician", "medical_director") is False


class TestAliases:
    def test_rn_is_alias_of_nurse(self) -> None:
        assert is_role_sufficient("rn", "nurse") is True
        assert is_role_sufficient("nurse", "rn") is True

    def test_rn_cannot_satisfy_physician(self) -> None:
        assert is_role_sufficient("rn", "physician") is False


class TestNoneRequired:
    def test_none_required_passes_for_recognised_role(self) -> None:
        """``required_role=None`` (gate didn't pin a role) accepts any known role."""
        assert is_role_sufficient("nurse", None) is True
        assert is_role_sufficient("any_human", None) is True
        assert is_role_sufficient("compliance_officer", None) is True

    def test_none_required_still_rejects_unknown_reviewer(self) -> None:
        """Fail-closed even when nothing is required — typos never pass."""
        assert is_role_sufficient("attendng_physician", None) is False
        assert is_role_sufficient("", None) is False
        assert is_role_sufficient("ADMIN", None) is False  # case-sensitive


class TestUnknownRoles:
    """The plan calls these out explicitly: unknown reviewer roles MUST
    fail-closed. The default-level-0 alternative would silently approve
    typos and made-up roles."""

    def test_typo_reviewer_role_fails(self) -> None:
        assert is_role_sufficient("attendng_physician", "physician") is False

    def test_made_up_reviewer_role_fails(self) -> None:
        assert is_role_sufficient("super_user", "nurse") is False

    def test_empty_string_reviewer_role_fails(self) -> None:
        assert is_role_sufficient("", "nurse") is False

    def test_unknown_required_role_fails_closed(self) -> None:
        """If a gate pins a role this table doesn't know, refuse to
        guess — fail-closed protects against drift between pack
        authors and this hierarchy."""
        assert is_role_sufficient("compliance_officer", "future_made_up_role") is False
        assert is_role_sufficient("medical_director", "icu_attending") is False

    def test_both_unknown_fails(self) -> None:
        assert is_role_sufficient("typo", "also_typo") is False
