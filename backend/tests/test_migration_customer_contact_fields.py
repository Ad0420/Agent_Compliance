"""Migration test for o5i6j7k8l9m0_add_customer_contact_fields (Phase 1 PR 2).

Verifies up/down/idempotent behaviour of the contact-fields migration.
Mirrors the patterns in test_migration_phase1_schema for consistency.
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

REV_PREV = "n4h5i6j7k8l9"
REV_NEW = "o5i6j7k8l9m0"
EXPECTED_NEW_COLUMNS = {"contact_name", "first_seen_at", "last_seen_at"}


@pytest.fixture
def temp_db_url(monkeypatch):
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
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _inspector(db_url: str):
    engine = sa.create_engine(db_url)
    return engine, sa.inspect(engine)


def _load_migration_module(filename: str):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rerun_upgrade(db_url: str, filename: str) -> None:
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


def test_upgrade_creates_contact_fields(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("customers")}
    assert EXPECTED_NEW_COLUMNS.issubset(cols), cols
    engine.dispose()


def test_downgrade_removes_contact_fields(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)
    command.downgrade(cfg, REV_PREV)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("customers")}
    assert not (EXPECTED_NEW_COLUMNS & cols), cols
    engine.dispose()


def test_upgrade_is_idempotent(temp_db_url):
    """Re-running the upgrade against a DB already on REV_NEW must be
    a no-op — no duplicate columns, no errors."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols_before = sorted(c["name"] for c in insp.get_columns("customers"))
    engine.dispose()

    _rerun_upgrade(db_url, "o5i6j7k8l9m0_add_customer_contact_fields.py")

    engine, insp = _inspector(db_url)
    cols_after = sorted(c["name"] for c in insp.get_columns("customers"))
    assert cols_before == cols_after
    # Catch silent suffix-duplicates.
    assert not any(c.endswith("_1") for c in cols_after), cols_after
    engine.dispose()
