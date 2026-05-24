"""Migration test for p6j7k8l9m0n1_add_wizard_answers_to_organizations
(Phase 1 PR 14, Stream F item F5).

Mirrors test_migration_customer_contact_fields. Verifies up/down/idempotent
behaviour on SQLite (cross-dialect safety is enforced by the migration's
own dialect switch).
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

REV_PREV = "o5i6j7k8l9m0"
REV_NEW = "p6j7k8l9m0n1"
EXPECTED_NEW_COLUMNS = {"wizard_answers", "wizard_completed_at"}


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


def test_upgrade_creates_wizard_columns(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert EXPECTED_NEW_COLUMNS.issubset(cols), cols
    engine.dispose()


def test_downgrade_removes_wizard_columns(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)
    command.downgrade(cfg, REV_PREV)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert not (EXPECTED_NEW_COLUMNS & cols), cols
    engine.dispose()


def test_upgrade_is_idempotent(temp_db_url):
    """Re-running the upgrade against a DB already on REV_NEW must be a no-op."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols_before = sorted(c["name"] for c in insp.get_columns("organizations"))
    engine.dispose()

    _rerun_upgrade(db_url, "p6j7k8l9m0n1_add_wizard_answers_to_organizations.py")

    engine, insp = _inspector(db_url)
    cols_after = sorted(c["name"] for c in insp.get_columns("organizations"))
    assert cols_before == cols_after
    assert not any(c.endswith("_1") for c in cols_after), cols_after
    engine.dispose()
