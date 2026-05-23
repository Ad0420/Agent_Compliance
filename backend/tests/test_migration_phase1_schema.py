"""Phase 1 PR 1 — Alembic migration up/down/idempotency tests.

Covers the three migrations introduced in this PR:

  - ``l2f3g4h5i6j7`` — ActionRecord tenant_id/domain/action_class columns + indexes
  - ``m3g4h5i6j7k8`` — customers / customer_agents / baa_agreements / baa_scopes tables
  - ``n4h5i6j7k8l9`` — api_keys.kind enum + backfill + index

Uses a temp SQLite file (NOT the test :memory: engine) so the alembic
runner can connect via its own sync engine, which is the standard
production execution model for migrations.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

# Revision ids under test in this PR.
REV_PRE = "k1f2g3h4i5j6"
REV_AR_PROMOTE = "l2f3g4h5i6j7"
REV_CUSTOMER = "m3g4h5i6j7k8"
REV_API_KEY_KIND = "n4h5i6j7k8l9"

# Phase-1 expected schema artifacts (per migration).
EXPECTED_AR_COLUMNS = {"tenant_id", "domain", "action_class"}
EXPECTED_AR_INDEXES = {
    "idx_ar_tenant_id",
    "idx_ar_org_tenant_seq",
    "idx_ar_action_class",
}
EXPECTED_CUSTOMER_TABLES = {
    "customers",
    "customer_agents",
    "baa_agreements",
    "baa_scopes",
}
EXPECTED_API_KEY_COLUMN = "kind"


@pytest.fixture
def temp_db_url(monkeypatch):
    """A clean temp SQLite file URL + automatic cleanup.

    Sets ``DATABASE_URL`` for the test scope so ``alembic/env.py``
    (which reads ``DATABASE_URL`` rather than the cfg option) picks
    up our temp file.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url, path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _make_alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # env.py reads DATABASE_URL directly; set the cfg too as belt-and-braces.
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _upgrade(cfg: Config, revision: str) -> None:
    command.upgrade(cfg, revision)


def _downgrade(cfg: Config, revision: str) -> None:
    command.downgrade(cfg, revision)


def _inspector(db_url: str):
    engine = sa.create_engine(db_url)
    insp = sa.inspect(engine)
    return engine, insp


def _load_migration_module(filename: str):
    """Load a migration module by file path (alembic.versions isn't a
    real package — it's a directory of standalone scripts)."""
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rerun_upgrade(db_url: str, filename: str) -> None:
    """Re-execute a migration's upgrade() function against an existing DB.

    Used to assert idempotency — the migration must be a no-op when its
    target schema is already present (no exceptions, no duplicate
    columns/indexes added)."""
    mod = _load_migration_module(filename)
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                from alembic.runtime.migration import MigrationContext
                from alembic.operations import Operations
                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    mod.upgrade()
    finally:
        engine.dispose()


# ── Migration 1: ActionRecord promoted columns ───────────────


def test_ar_promote_upgrade_creates_columns_and_indexes(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)

    _upgrade(cfg, REV_AR_PROMOTE)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("action_records")}
    assert EXPECTED_AR_COLUMNS.issubset(cols), cols

    indexes = {ix["name"] for ix in insp.get_indexes("action_records")}
    assert EXPECTED_AR_INDEXES.issubset(indexes), indexes
    engine.dispose()


def test_ar_promote_downgrade_removes_columns_and_indexes(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_AR_PROMOTE)
    _downgrade(cfg, REV_PRE)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("action_records")}
    assert not (EXPECTED_AR_COLUMNS & cols), cols

    indexes = {ix["name"] for ix in insp.get_indexes("action_records")}
    assert not (EXPECTED_AR_INDEXES & indexes), indexes
    engine.dispose()


def test_ar_promote_idempotent_upgrade(temp_db_url):
    """Running the upgrade twice must not error."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_AR_PROMOTE)
    _rerun_upgrade(
        db_url, "l2f3g4h5i6j7_promote_tenant_domain_action_class.py"
    )


# ── Migration 2: Customer + BAA tables ────────────────────────


def test_customer_baa_upgrade_creates_tables(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_CUSTOMER)

    engine, insp = _inspector(db_url)
    tables = set(insp.get_table_names())
    assert EXPECTED_CUSTOMER_TABLES.issubset(tables), tables

    # Spot-check column shape on customers.
    customer_cols = {c["name"] for c in insp.get_columns("customers")}
    for expected in (
        "id",
        "org_id",
        "tenant_id",
        "display_name",
        "status",
        "baa_status",
        "contact_email",
        "jurisdictions",
        "created_at",
        "updated_at",
    ):
        assert expected in customer_cols, (expected, customer_cols)

    # Spot-check customer_agents includes historical-stamp column.
    ca_cols = {c["name"] for c in insp.get_columns("customer_agents")}
    assert "agent_type" in ca_cols
    assert "first_seen_at" in ca_cols
    assert "last_seen_at" in ca_cols

    # Spot-check baa_scopes has the Codex E2 fields.
    scope_cols = {c["name"] for c in insp.get_columns("baa_scopes")}
    assert "covered_services" in scope_cols
    assert "covered_agent_types" in scope_cols
    engine.dispose()


def test_customer_baa_downgrade_drops_tables(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_CUSTOMER)
    _downgrade(cfg, REV_AR_PROMOTE)

    engine, insp = _inspector(db_url)
    tables = set(insp.get_table_names())
    assert not (EXPECTED_CUSTOMER_TABLES & tables), tables
    engine.dispose()


def test_customer_baa_idempotent_upgrade(temp_db_url):
    """Re-running the customer/BAA migration over an existing schema must
    not crash — the migration uses table-existence guards."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_CUSTOMER)
    _rerun_upgrade(db_url, "m3g4h5i6j7k8_customer_and_baa_tables.py")


# ── Migration 3: api_keys.kind ────────────────────────────────


def test_api_key_kind_upgrade_adds_column_and_backfills(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)

    # Run all migrations up to the parent so we have an api_keys table
    # *without* the kind column. Insert a sample row to verify the backfill.
    _upgrade(cfg, REV_CUSTOMER)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        # Need an org to satisfy FK.
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES ('org-pre-kind', 'pre-kind', :ts)"
            ),
            {"ts": "2026-01-01"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO api_keys "
                "(id, org_id, name, key_hash, key_prefix, permissions, created_at) "
                "VALUES ('k1', 'org-pre-kind', 'legacy', 'h1', 'al_p_xx', '[]', :ts)"
            ),
            {"ts": "2026-01-01"},
        )
    engine.dispose()

    _upgrade(cfg, REV_API_KEY_KIND)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("api_keys")}
    assert EXPECTED_API_KEY_COLUMN in cols

    # Backfill verification: the legacy row must be 'test'.
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT kind FROM api_keys WHERE id = 'k1'")
        ).scalar_one()
    assert row == "test", row

    # Index check.
    indexes = {ix["name"] for ix in insp.get_indexes("api_keys")}
    assert "idx_api_keys_org_kind" in indexes
    engine.dispose()


def test_api_key_kind_downgrade_drops_column(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_API_KEY_KIND)
    _downgrade(cfg, REV_CUSTOMER)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("api_keys")}
    assert EXPECTED_API_KEY_COLUMN not in cols
    indexes = {ix["name"] for ix in insp.get_indexes("api_keys")}
    assert "idx_api_keys_org_kind" not in indexes
    engine.dispose()


def test_full_upgrade_then_full_downgrade_then_full_upgrade(temp_db_url):
    """End-to-end round-trip for the three new migrations: upgrade head,
    downgrade past them, re-upgrade head. Catches state-pollution bugs."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    _upgrade(cfg, REV_API_KEY_KIND)
    _downgrade(cfg, REV_PRE)
    _upgrade(cfg, REV_API_KEY_KIND)

    engine, insp = _inspector(db_url)
    tables = set(insp.get_table_names())
    assert EXPECTED_CUSTOMER_TABLES.issubset(tables)
    cols = {c["name"] for c in insp.get_columns("action_records")}
    assert EXPECTED_AR_COLUMNS.issubset(cols)
    api_cols = {c["name"] for c in insp.get_columns("api_keys")}
    assert EXPECTED_API_KEY_COLUMN in api_cols
    engine.dispose()
