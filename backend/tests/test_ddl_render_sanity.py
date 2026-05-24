"""Render-only sanity check that the Approval CREATE TABLE compiles
cleanly on PostgreSQL after the Wave 2B A5 columns land. Catches the
``DEFAULT 0 → BOOLEAN`` DatatypeMismatch that broke CI when we shipped
``server_default=text("0")`` instead of ``server_default=false()``.

Render-only — no DB connection required.
"""
from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Approval, WebhookDelivery, WebhookDeliveryAttempt


def test_approvals_create_table_postgres_renders_false_for_bool_default():
    ddl = str(CreateTable(Approval.__table__).compile(dialect=postgresql.dialect()))
    # The new boolean column must use a real boolean literal, not the
    # integer literal "0" (which Postgres rejects with DatatypeMismatch).
    bool_line = next(
        line for line in ddl.splitlines() if "reviewed_below_threshold" in line
    )
    assert "BOOLEAN" in bool_line, bool_line
    assert "DEFAULT false" in bool_line, bool_line
    assert "DEFAULT 0" not in bool_line, bool_line


# ── Wave 2B PR A3 — webhook delivery tables ────────────────────────────────


def test_webhook_deliveries_create_table_renders_on_postgres():
    """Plain render-only — no DB connection. Catches any column-default
    type mismatch (the same class of bug that broke A5's first push)
    before alembic touches Postgres in CI.
    """
    ddl = str(
        CreateTable(WebhookDelivery.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    # No accidental BOOLEAN columns sneaking in.
    assert "BOOLEAN" not in ddl, ddl
    # Composite unique index gets rendered with both columns.
    assert "subscription_id" in ddl
    assert "idempotency_key" in ddl


def test_webhook_delivery_attempts_create_table_renders_on_postgres():
    ddl = str(
        CreateTable(WebhookDeliveryAttempt.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "delivery_id" in ddl
    assert "attempt_number" in ddl
