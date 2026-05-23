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

NOTE for future ops: the ``UPDATE api_keys SET kind = 'test'`` is a
single-statement full-table update that locks ``api_keys`` for its
duration. At v1 scale this is fine; once api_keys grows beyond ~100k
rows a batched UPDATE in a CONCURRENTLY-style migration is the safer
pattern.

This PR (Phase 1 PR 1) only stands up the column + check constraint +
backfill. The ``require_permission`` BAA-gating logic lands in PR 4.

Idempotency: every step (add_column, backfill, NOT NULL, CHECK, index)
self-checks against the current schema state. If a previous upgrade
crashed between steps, re-running picks up where it left off rather
than short-circuiting on the presence of just the column.
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


def _is_column_nullable(inspector, table: str, column: str) -> bool:
    cols = {c["name"]: c for c in inspector.get_columns(table)}
    return cols.get(column, {}).get("nullable", True)


def _has_check_constraint(inspector, table: str, name: str) -> bool:
    """Return True if the CHECK constraint exists.

    SQLite reflection of CHECK constraints via ``get_check_constraints``
    is dialect-supported in modern SQLAlchemy but can be flaky; missing
    method → treat as "unknown, attempt to create and swallow errors".
    """
    if not hasattr(inspector, "get_check_constraints"):
        return False
    try:
        return name in {c.get("name") for c in inspector.get_check_constraints(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _TABLE not in inspector.get_table_names():
        return

    # ── Step 1: add the column (nullable initially) ─────────
    if not _has_column(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=8),
                nullable=True,
                server_default=sa.text("'test'"),
            ),
        )

    # ── Step 2: backfill NULLs — idempotent (no-op once all rows have a value) ─
    # Locks api_keys for the duration on Postgres. See module docstring.
    op.execute("UPDATE api_keys SET kind = 'test' WHERE kind IS NULL")

    # ── Step 3: enforce NOT NULL ────────────────────────────
    inspector = sa.inspect(bind)
    if _is_column_nullable(inspector, _TABLE, _COLUMN):
        if dialect == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.alter_column(
                    _COLUMN,
                    existing_type=sa.String(length=8),
                    nullable=False,
                    server_default=sa.text("'test'"),
                )
        else:
            op.alter_column(
                _TABLE,
                _COLUMN,
                existing_type=sa.String(length=8),
                nullable=False,
                server_default=sa.text("'test'"),
            )

    # ── Step 4: CHECK constraint ────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_check_constraint(inspector, _TABLE, _CHECK_NAME):
        if dialect == "sqlite":
            # SQLite reflection of CHECK constraints can be flaky — if the
            # constraint was added by a previous upgrade but isn't reported
            # by the inspector, this would attempt to add it again. Swallow.
            try:
                with op.batch_alter_table(_TABLE) as batch:
                    batch.create_check_constraint(
                        _CHECK_NAME,
                        "kind IN ('test', 'live')",
                    )
            except Exception:
                pass
        else:
            try:
                op.create_check_constraint(
                    _CHECK_NAME,
                    _TABLE,
                    "kind IN ('test', 'live')",
                )
            except Exception:
                pass

    # ── Step 5: composite index ─────────────────────────────
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
