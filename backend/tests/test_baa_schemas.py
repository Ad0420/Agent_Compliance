"""Pydantic schema tests for BAAAgreement + BAAScope (Phase 1 PR 1).

API-boundary guards in isolation from the model layer. The model-level
checks are in test_baa_model.py; this file pins the contract that the
HTTP route exposes (status enum, scope list non-emptiness, defaults).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import BAAAgreementCreate, BAAScopeCreate


# ── BAAAgreementCreate ─────────────────────────────────────────


def test_baa_agreement_create_default_status():
    b = BAAAgreementCreate(customer_id="c1")
    assert b.status == "draft"


def test_baa_agreement_invalid_status_rejected():
    with pytest.raises(ValidationError):
        BAAAgreementCreate(customer_id="c1", status="unsigned")


# ── BAAScopeCreate ─────────────────────────────────────────────


def test_baa_scope_create_requires_non_empty_lists():
    with pytest.raises(ValidationError):
        BAAScopeCreate(
            baa_agreement_id="b1",
            covered_services=[],
            covered_agent_types=["x"],
            granted_at=datetime.now(),
        )
    with pytest.raises(ValidationError):
        BAAScopeCreate(
            baa_agreement_id="b1",
            covered_services=["s"],
            covered_agent_types=[],
            granted_at=datetime.now(),
        )


def test_baa_scope_create_valid():
    s = BAAScopeCreate(
        baa_agreement_id="b1",
        covered_services=["chart_entry"],
        covered_agent_types=["scribe"],
        granted_at=datetime.now(),
    )
    assert s.covered_services == ["chart_entry"]
    assert s.covered_agent_types == ["scribe"]


def test_baa_scope_create_is_unrestricted_default_false():
    """The wildcard flag added in this PR defaults to False so legacy
    BAAs (with explicit lists) keep their semantics. PR 4/5 backfills
    truly-unrestricted historical BAAs to True."""
    s = BAAScopeCreate(
        baa_agreement_id="b1",
        covered_services=["x"],
        covered_agent_types=["y"],
        granted_at=datetime.now(),
    )
    assert s.is_unrestricted is False


def test_baa_scope_create_is_unrestricted_accepts_true():
    s = BAAScopeCreate(
        baa_agreement_id="b1",
        covered_services=["x"],
        covered_agent_types=["y"],
        granted_at=datetime.now(),
        is_unrestricted=True,
    )
    assert s.is_unrestricted is True
