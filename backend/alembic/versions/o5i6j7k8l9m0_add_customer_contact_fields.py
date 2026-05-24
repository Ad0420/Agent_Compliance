"""add Customer.contact_name, first_seen_at, last_seen_at (Phase 1 PR 2)

Revision ID: o5i6j7k8l9m0
Revises: n4h5i6j7k8l9
Create Date: 2026-05-23

Phase 1 PR 2 adds three nullable columns on ``customers`` that the
PR-1 migration didn't ship:

  - ``contact_name``   — operator-supplied human contact at the customer
                          (paired with ``contact_email``). Edited via
                          ``PATCH /v1/customers/{tenant_id}``.
  - ``first_seen_at``  — when the customer was auto-discovered or first
                          declared. ``NOT NULL`` semantically, but kept
                          nullable on the column for forward-compat with
                          rows created before this migration. Auto-
                          discovery (Phase 1 PR 2) backfills it on
                          INSERT, never on UPDATE.
  - ``last_seen_at``   — touched on every action_record write whose
                          tenant_id matches this Customer. Drives the
                          AI Coverage Matrix "stale customer" column.

All three columns are NULLable so this migration is a pure ADD COLUMN
and needs no backfill — existing rows simply have NULL values until
operators edit / SDK traffic updates them.

Idempotency: every ``add_column`` is guarded by an existence check
against the inspector. Re-running the migration after a partial
failure picks up where it left off rather than erroring on duplicate
column.
"""
import sqlalchemy as sa
from alembic import op

revision = "o5i6j7k8l9m0"
down_revision = "n4h5i6j7k8l9"
branch_labels = None
depends_on = None


_TABLE = "customers"
_NEW_COLUMNS = (
    ("contact_name", sa.String(length=255)),
    ("first_seen_at", sa.DateTime()),
    ("last_seen_at", sa.DateTime()),
)


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # Guards against an out-of-order run. The Customer table should
        # already exist via m3g4h5i6j7k8.
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
        # SQLite DROP COLUMN needs batch_alter_table for the rebuild-and-copy
        # dance; modern SQLite (≥3.35) supports inline DROP COLUMN but
        # SQLAlchemy still routes through batch_alter for portability.
        with op.batch_alter_table(_TABLE) as batch:
            for col_name, _ in _NEW_COLUMNS:
                if _has_column(inspector, _TABLE, col_name):
                    batch.drop_column(col_name)
    else:
        for col_name, _ in _NEW_COLUMNS:
            if _has_column(inspector, _TABLE, col_name):
                op.drop_column(_TABLE, col_name)
