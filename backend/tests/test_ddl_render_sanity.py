"""Render-only sanity check that the Approval CREATE TABLE compiles
cleanly on PostgreSQL after the Wave 2B A5 columns land. Catches the
``DEFAULT 0 → BOOLEAN`` DatatypeMismatch that broke CI when we shipped
``server_default=text("0")`` instead of ``server_default=false()``.

Render-only — no DB connection required.
"""
from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Approval


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
