"""add Organization.wizard_answers + wizard_completed_at (Phase 1 PR 14)

Revision ID: p6j7k8l9m0n1
Revises: o5i6j7k8l9m0
Create Date: 2026-05-23

Phase 1 PR 14 (Stream F item F5) ships the 5-question onboarding wizard.
Answers persist on the Organization row as a JSON blob so the Phase 5
template-generation work can read them without a second schema churn.

Two nullable columns:

  - ``wizard_answers`` (JSON)            — partial or complete answer set.
                                            Shape validated server-side by
                                            ``app/schemas/wizard.py``.
  - ``wizard_completed_at`` (DateTime)   — stamped when the operator
                                            submits the final step with
                                            ``completed=true``. Used to
                                            distinguish "in-progress" from
                                            "done" without parsing the JSON.

Both columns are NULLable so this migration is a pure ADD COLUMN with no
backfill. Existing orgs simply have NULL values until an admin opens the
wizard.

``sa.JSON()`` (generic, dialect-portable) — NOT Postgres ``JSONB`` —
keeps SQLite happy in tests and uses the underlying JSONB on Postgres
automatically when supported.

Idempotency: every ``add_column`` is guarded by an existence check
against the inspector so re-running after partial failure is a no-op.
Mirrors the o5i6j7k8l9m0 customer-contact-fields pattern.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "p6j7k8l9m0n1"
down_revision = "o5i6j7k8l9m0"
branch_labels = None
depends_on = None


_TABLE = "organizations"
_NEW_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("wizard_answers", sa.JSON()),
    ("wizard_completed_at", sa.DateTime()),
)


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    for col_name, col_type in _NEW_COLUMNS:
        if not _has_column(inspector, _TABLE, col_name):
            op.add_column(_TABLE, sa.Column(col_name, col_type, nullable=True))
            inspector = sa.inspect(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _TABLE not in inspector.get_table_names():
        return

    if dialect == "sqlite":
        # SQLite DROP COLUMN goes through batch_alter_table for the
        # rebuild-and-copy dance. Matches o5i6j7k8l9m0.
        with op.batch_alter_table(_TABLE) as batch:
            for col_name, _ in _NEW_COLUMNS:
                if _has_column(inspector, _TABLE, col_name):
                    batch.drop_column(col_name)
    else:
        for col_name, _ in _NEW_COLUMNS:
            if _has_column(inspector, _TABLE, col_name):
                op.drop_column(_TABLE, col_name)
