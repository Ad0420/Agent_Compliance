"""Schema-level verification of migration ``r8m0n1o2p3q4``.

Runs against the alembic upgrade path on a fresh SQLite DB to confirm:
  * Both tables exist with the expected columns.
  * The unique idempotency index is present and enforced.
  * The composite + per-FK indexes exist.
  * Downgrade drops both tables cleanly.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config()
    # alembic.ini in backend/. Walk up from this test file.
    here = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(here)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def fresh_db_url(monkeypatch):
    # ``alembic/env.py`` reads ``DATABASE_URL`` from the environment
    # (not the Config object) when resolving the migration target. Point
    # it at our throwaway tempdir DB and clean up on teardown.
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "migration_a3.db")
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    yield url


def test_upgrade_creates_both_tables_and_indexes(fresh_db_url):
    cfg = _alembic_cfg(fresh_db_url)
    command.upgrade(cfg, "r8m0n1o2p3q4")

    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "webhook_deliveries" in tables
    assert "webhook_delivery_attempts" in tables

    parent_cols = {c["name"] for c in insp.get_columns("webhook_deliveries")}
    for required in (
        "id",
        "subscription_id",
        "org_id",
        "event_type",
        "payload",
        "status",
        "attempt_count",
        "next_retry_at",
        "locked_until",
        "locked_by",
        "created_at",
        "succeeded_at",
        "aborted_at",
        "last_status_code",
        "idempotency_key",
    ):
        assert required in parent_cols, f"missing column {required}"

    child_cols = {
        c["name"] for c in insp.get_columns("webhook_delivery_attempts")
    }
    for required in (
        "id",
        "delivery_id",
        "attempt_number",
        "attempted_at",
        "status_code",
        "response_body_excerpt",
        "error_message",
        "duration_ms",
        "next_retry_at",
    ):
        assert required in child_cols, f"missing column {required}"

    idx_names = {ix["name"] for ix in insp.get_indexes("webhook_deliveries")}
    assert "idx_webhook_deliveries_next_retry_at" in idx_names
    assert "idx_webhook_deliveries_subscription" in idx_names
    assert "ix_webhook_deliveries_subscription_id" in idx_names
    assert "ix_webhook_deliveries_org_id" in idx_names


def test_idempotency_unique_constraint_enforced(fresh_db_url):
    cfg = _alembic_cfg(fresh_db_url)
    command.upgrade(cfg, "r8m0n1o2p3q4")

    engine = create_engine(fresh_db_url)
    # Seed parent FKs.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES ('org-1', 'o', CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO webhook_subscriptions "
                "(id, org_id, url, secret, event_types, is_active, consecutive_failures, created_at) "
                "VALUES ('sub-1', 'org-1', 'https://x.example.com', 'k', '[]', 1, 0, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO webhook_deliveries "
                "(id, subscription_id, org_id, event_type, payload, status, attempt_count, idempotency_key, created_at) "
                "VALUES ('d-1', 'sub-1', 'org-1', 'policy.violation', '{}', 'pending', 0, 'dup-key', CURRENT_TIMESTAMP)"
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO webhook_deliveries "
                    "(id, subscription_id, org_id, event_type, payload, status, attempt_count, idempotency_key, created_at) "
                    "VALUES ('d-2', 'sub-1', 'org-1', 'policy.violation', '{}', 'pending', 0, 'dup-key', CURRENT_TIMESTAMP)"
                )
            )


def test_downgrade_drops_tables(fresh_db_url):
    cfg = _alembic_cfg(fresh_db_url)
    command.upgrade(cfg, "r8m0n1o2p3q4")
    command.downgrade(cfg, "q7k8l9m0n1o2")

    engine = create_engine(fresh_db_url)
    tables = set(inspect(engine).get_table_names())
    assert "webhook_deliveries" not in tables
    assert "webhook_delivery_attempts" not in tables
