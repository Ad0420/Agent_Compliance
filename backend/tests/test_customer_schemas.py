"""Pydantic schema tests for Customer + APIKey (Phase 1 PR 1).

These guard the API boundary contracts in isolation from the model layer.
Pre-fix the PR only had model-level tests, so e.g. a regex regression in
``CustomerCreate.tenant_id`` would slip through CI silently.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import CustomerCreate, CustomerUpdate
from app.schemas.api_key import APIKeyCreate


# ── tenant_id format regex ─────────────────────────────────────


@pytest.mark.parametrize(
    "ok",
    ["a", "abc_123-XYZ", "a" * 64, "cleveland_clinic"],
)
def test_tenant_id_regex_accepts_valid(ok):
    assert CustomerCreate(tenant_id=ok).tenant_id == ok


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a" * 65,
        "foo.bar",
        "foo bar",
        "../etc",
        "résumé",
        "foo/bar",
        "foo;bar",
        "DROP TABLE",
    ],
)
def test_tenant_id_regex_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        CustomerCreate(tenant_id=bad)


# ── CustomerCreate defaults ────────────────────────────────────


def test_customer_create_minimal():
    c = CustomerCreate(tenant_id="cleveland_clinic")
    assert c.display_name is None
    assert c.contact_email is None
    assert c.jurisdictions is None


# ── CustomerUpdate: all-optional contract ──────────────────────


def test_customer_update_all_optional():
    # An empty update payload must be valid; the route layer decides
    # whether to no-op or 400.
    CustomerUpdate()


def test_customer_update_accepts_terminated_baa_status():
    """Phase 1 PR 1 spec: ``terminated`` is a valid BAA lifecycle state
    distinguishing a rescinded BAA from one that merely expired."""
    upd = CustomerUpdate(baa_status="terminated")
    assert upd.baa_status == "terminated"


def test_customer_update_rejects_invalid_baa_status():
    with pytest.raises(ValidationError):
        CustomerUpdate(baa_status="not_a_real_status")


# ── APIKeyCreate.kind: accepted on create path (Phase 1 PR 4) ────


def test_api_key_create_accepts_kind_field():
    """Phase 1 PR 4 (Stream C item C1) reintroduces ``kind`` on the
    create path. The route handler enforces the BAA gate for
    ``kind='live'``; the schema's job is to refuse typos before the
    route runs."""
    test_key = APIKeyCreate(name="k")
    assert test_key.kind == "test"

    live_key = APIKeyCreate(name="k", kind="live")
    assert live_key.kind == "live"


def test_api_key_create_rejects_invalid_kind():
    """A typo must 422 at the schema layer, not surface as a 500 from
    the SQL CHECK constraint."""
    import pytest

    with pytest.raises(ValueError):
        APIKeyCreate(name="k", kind="production")
