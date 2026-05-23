"""add api_keys.kind (test/live) with test-default backfill (Phase 1 PR 1)

Revision ID: n4h5i6j7k8l9
Revises: m3g4h5i6j7k8
Create Date: 2026-05-23

Splits API keys into two cohorts:

  - ``kind='test'`` (``al_test_*`` prefix in Phase 1 PR 4) — sandbox / dev
    usage. PHI-shape heuristic warns but does not reject.
  - ``kind='live'`` (``al_live_*`` prefix) — production usage. PHI-shape
    heuristic rejects. Phase 1 PR 4 will additionally gate live keys
    behind a signed BAA upload (``require_permission`` check).

All existing keys backfill to ``kind='test'`` — the safest default per
the PR #188 description (all known pilots are dev-only). Production cutover
to live keys is an explicit upgrade step, not implicit promotion.

This PR (Phase 1 PR 1) only stands up the column + check constraint +
backfill. The ``require_permission`` BAA-gating logic lands in PR 4.

Idempotent: skipped if the column already exists.
"""
import sqlalchemy as sa
from alembic import op

revision = "n4h5i6j7k8l9"
down_revision = "m3g4h5i6j7k8"
branch_labels = None
depends_on = None


_TABLE = "api_keys"
_COLUMN = "kind"
_INDEX = "idx_api_keys_org_kind"
_CHECK_NAME = "ck_api_keys_kind"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector, table: str, index_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _TABLE not in inspector.get_table_names():
        return

    if _has_column(inspector, _TABLE, _COLUMN):
        return

    # Add nullable first so existing rows accept the default-of-record,
    # then backfill, then enforce NOT NULL via a fresh batch_alter (SQLite)
    # or alter_column (Postgres). The CHECK constraint is added as part of
    # the column on Postgres, and via batch_alter on SQLite.
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.String(length=8),
            nullable=True,
            server_default=sa.text("'test'"),
        ),
    )
    # Backfill all existing rows explicitly — the server_default covers new
    # INSERTs, but Postgres won't retroactively apply it to already-existing
    # rows on the same statement.
    op.execute("UPDATE api_keys SET kind = 'test' WHERE kind IS NULL")

    if dialect == "sqlite":
        # SQLite: rebuild-and-copy via batch_alter_table. We add the CHECK
        # constraint here and set NOT NULL in the same op.
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column(
                _COLUMN,
                existing_type=sa.String(length=8),
                nullable=False,
                server_default=sa.text("'test'"),
            )
            batch.create_check_constraint(
                _CHECK_NAME,
                "kind IN ('test', 'live')",
            )
    else:
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.String(length=8),
            nullable=False,
            server_default=sa.text("'test'"),
        )
        op.create_check_constraint(
            _CHECK_NAME,
            _TABLE,
            "kind IN ('test', 'live')",
        )

    # Composite index (org_id, kind) for "list my live keys" style queries
    # without paying for two single-column indexes.
    inspector = sa.inspect(bind)
    if not _has_index(inspector, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["org_id", "kind"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not _has_column(inspector, _TABLE, _COLUMN):
        return

    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)

    if dialect == "sqlite":
        with op.batch_alter_table(_TABLE) as batch:
            try:
                batch.drop_constraint(_CHECK_NAME, type_="check")
            except Exception:
                # CHECK constraint reflection on SQLite is flaky; the
                # column drop below will take it with the rebuild anyway.
                pass
            batch.drop_column(_COLUMN)
    else:
        try:
            op.drop_constraint(_CHECK_NAME, _TABLE, type_="check")
        except Exception:
            pass
        op.drop_column(_TABLE, _COLUMN)
