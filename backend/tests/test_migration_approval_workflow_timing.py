"""Migration test for q7k8l9m0n1o2_add_approval_workflow_timing
(Phase 2 Wave 2B PR A5).

Mirrors test_migration_customer_contact_fields / test_migration_wizard_answers.
Verifies up/down/idempotent behaviour on SQLite (cross-dialect safety is
enforced by the migration's own dialect switch in downgrade()).
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

REV_PREV = "p6j7k8l9m0n1"
REV_NEW = "q7k8l9m0n1o2"
MIGRATION_FILENAME = "q7k8l9m0n1o2_add_approval_workflow_timing.py"

EXPECTED_TIMESTAMP_COLUMNS = {
    "client_review_started_at",
    "decided_at",
    "webhook_sent_at",
    "callback_received_at",
}
EXPECTED_FLAG_COLUMN = "reviewed_below_threshold"
EXPECTED_NEW_COLUMNS = EXPECTED_TIMESTAMP_COLUMNS | {EXPECTED_FLAG_COLUMN}
DECIDED_AT_INDEX = "ix_approvals_decided_at"


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


def test_upgrade_creates_workflow_timing_columns(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("approvals")}
    assert EXPECTED_NEW_COLUMNS.issubset(cols), cols
    engine.dispose()


def test_downgrade_removes_workflow_timing_columns(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)
    command.downgrade(cfg, REV_PREV)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("approvals")}
    assert not (EXPECTED_NEW_COLUMNS & cols), cols
    # Index gone too.
    indexes = {ix["name"] for ix in insp.get_indexes("approvals")}
    assert DECIDED_AT_INDEX not in indexes, indexes
    engine.dispose()


def test_upgrade_is_idempotent(temp_db_url):
    """Re-running the upgrade against a DB already on REV_NEW must be a no-op."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols_before = sorted(c["name"] for c in insp.get_columns("approvals"))
    indexes_before = sorted(ix["name"] for ix in insp.get_indexes("approvals"))
    engine.dispose()

    _rerun_upgrade(db_url, MIGRATION_FILENAME)

    engine, insp = _inspector(db_url)
    cols_after = sorted(c["name"] for c in insp.get_columns("approvals"))
    indexes_after = sorted(ix["name"] for ix in insp.get_indexes("approvals"))
    assert cols_before == cols_after
    assert indexes_before == indexes_after
    # Catch silent suffix-duplicates from a non-idempotent rerun.
    assert not any(c.endswith("_1") for c in cols_after), cols_after
    engine.dispose()


def test_decided_at_index_created(temp_db_url):
    """ix_approvals_decided_at must exist and cover [decided_at] after upgrade."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    indexes = {ix["name"]: ix for ix in insp.get_indexes("approvals")}
    assert DECIDED_AT_INDEX in indexes, sorted(indexes)
    assert indexes[DECIDED_AT_INDEX]["column_names"] == ["decided_at"]
    engine.dispose()


def test_reviewed_below_threshold_defaults_false_for_existing_rows(temp_db_url):
    """Pre-existing rows must backfill to FALSE via server_default, and the
    four timestamp columns must remain NULL."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)

    # Stop at REV_PREV, seed an approval row using only PRE-A5 columns,
    # then upgrade to REV_NEW and inspect the row.
    command.upgrade(cfg, REV_PREV)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        # Need a parent organization row (FK target) and the approval row.
        org_id = str(uuid.uuid4())
        approval_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (:id, :name, CURRENT_TIMESTAMP)"
            ),
            {"id": org_id, "name": "A5 Test Org"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO approvals "
                "(id, org_id, requested_by_agent, action_name, context, "
                " risk_tier, approvers_required, status, decisions) "
                "VALUES (:id, :org_id, :agent, :action, '{}', "
                " 'high', 1, 'pending', '[]')"
            ),
            {
                "id": approval_id,
                "org_id": org_id,
                "agent": "test-agent",
                "action": "test-action",
            },
        )
    engine.dispose()

    command.upgrade(cfg, REV_NEW)

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT reviewed_below_threshold, "
                "       client_review_started_at, decided_at, "
                "       webhook_sent_at, callback_received_at "
                "FROM approvals WHERE id = :id"
            ),
            {"id": approval_id},
        ).one()
    engine.dispose()

    # SQLite returns 0 for FALSE; Python truthiness covers both stores.
    assert not row.reviewed_below_threshold
    assert row.client_review_started_at is None
    assert row.decided_at is None
    assert row.webhook_sent_at is None
    assert row.callback_received_at is None
