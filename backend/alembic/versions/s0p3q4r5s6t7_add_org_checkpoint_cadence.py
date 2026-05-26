"""add Organization.checkpoint_cadence (Phase 3 Wave 3A.b)

Revision ID: s0p3q4r5s6t7
Revises: r8m0n1o2p3q4
Create Date: 2026-05-25

Phase 3 Wave 3A.b (Eng review finding 1D) ships per-org checkpoint
cadence configuration. The implicit "daily KMS-signed checkpoint" line
in [v1-implementation-plan.md §Phase 3](../../../v1-implementation-plan.md)
is too coarse for live AI traffic — the "less than 1 hour of unverified
actions" claim regulators expect requires an *hourly* cadence on orgs
running on ``al_live_*`` keys. Sandbox-only orgs stay daily.

One new column:

  - ``checkpoint_cadence``  VARCHAR(16)  NOT NULL  DEFAULT 'daily'
                             CHECK (checkpoint_cadence IN
                                    ('daily', 'hourly', 'disabled'))

Backfill happens in two layers:

  1. ``server_default='daily'`` covers existing rows + future inserts
     that omit the column. This is the "safe baseline" — any org we
     don't know about explicitly stays on the daily cadence.

  2. A data-migration step promotes any org with at least one active
     ``al_live_*`` API key to ``'hourly'``. Active = ``revoked_at IS
     NULL`` *or* ``revoked_at > now()`` (the latter handles
     scheduled-revocation rows that haven't actually fired yet).
     ``kind = 'live'`` is the production-tier marker per the
     ``n4h5i6j7k8l9`` migration.

Idempotency: every step (add_column, backfill, NOT NULL transition,
CHECK constraint) self-checks against the inspector. Re-running after
a partial failure picks up where it left off — same pattern as the
``n4h5i6j7k8l9`` API-key ``kind`` migration.

Portability: per the project's standing rule we use ``sa.text("'daily'")``
for the string default, never ``sa.text("0")`` for booleans (the
``r8m0n1o2p3q4`` rationale). No bool columns here.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "s0p3q4r5s6t7"
down_revision = "r8m0n1o2p3q4"
branch_labels = None
depends_on = None


_TABLE = "organizations"
_COLUMN = "checkpoint_cadence"
_CHECK_NAME = "ck_organizations_checkpoint_cadence"
_CHECK_SQL = "checkpoint_cadence IN ('daily', 'hourly', 'disabled')"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _is_column_nullable(inspector, table: str, column: str) -> bool:
    cols = {c["name"]: c for c in inspector.get_columns(table)}
    return cols.get(column, {}).get("nullable", True)


def _has_check_constraint(inspector, table: str, name: str) -> bool:
    """Return True if the CHECK constraint exists.

    SQLite reflection of CHECK constraints is dialect-supported but can
    be flaky under some pragmas; missing method → treat as "unknown,
    attempt to create and swallow errors". Mirrors ``n4h5i6j7k8l9``.
    """
    if not hasattr(inspector, "get_check_constraints"):
        return False
    try:
        return name in {
            c.get("name") for c in inspector.get_check_constraints(table)
        }
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _TABLE not in inspector.get_table_names():
        # Out-of-order run guard. The organizations table must already
        # exist via the initial schema migration.
        return

    # ── Step 1: add the column with server default 'daily' ─────────────
    # Nullable at first so the backfill UPDATE can pass through cleanly
    # on Postgres without a transient constraint violation.
    if not _has_column(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=16),
                nullable=True,
                server_default=sa.text("'daily'"),
            ),
        )

    # ── Step 2: server-default backfill for existing rows ─────────────
    # ``server_default`` only applies to new inserts on some dialects;
    # explicit UPDATE here makes the rule uniform for rows that existed
    # before this migration ran. Idempotent — once filled, the WHERE
    # clause picks up nothing.
    op.execute(
        "UPDATE organizations SET checkpoint_cadence = 'daily' "
        "WHERE checkpoint_cadence IS NULL"
    )

    # ── Step 3: live-key promotion data migration ──────────────────────
    # Any org with at least one active ``al_live_*`` API key gets
    # promoted to ``'hourly'`` so the "less than 1 hour of unverified
    # actions" claim holds for the regulator-relevant cohort. Idempotent
    # — running again finds the same rows already at 'hourly' and the
    # SET is a no-op.
    #
    # ``revoked_at IS NULL`` is the only "active" predicate we use:
    # ``api_keys.revoked_at`` is a naive ``DateTime`` column and the
    # runtime ``APIKey.is_active`` property treats any non-NULL
    # ``revoked_at`` as inactive (there is no future-scheduled-revocation
    # feature today). Comparing a naive timestamp to Postgres'
    # ``CURRENT_TIMESTAMP`` (which is ``timestamptz`` on Postgres) would
    # raise ``operator does not exist: timestamp without time zone >
    # timestamp with time zone`` at migration time. Sticking to the
    # ``IS NULL`` semantics matches both portability and the runtime
    # contract.
    op.execute(
        """
        UPDATE organizations
        SET checkpoint_cadence = 'hourly'
        WHERE id IN (
            SELECT DISTINCT org_id FROM api_keys
            WHERE kind = 'live' AND revoked_at IS NULL
        )
        """
    )

    # ── Step 4: enforce NOT NULL ──────────────────────────────────────
    inspector = sa.inspect(bind)
    if _is_column_nullable(inspector, _TABLE, _COLUMN):
        if dialect == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.alter_column(
                    _COLUMN,
                    existing_type=sa.String(length=16),
                    nullable=False,
                    server_default=sa.text("'daily'"),
                )
        else:
            op.alter_column(
                _TABLE,
                _COLUMN,
                existing_type=sa.String(length=16),
                nullable=False,
                server_default=sa.text("'daily'"),
            )

    # ── Step 5: CHECK constraint ──────────────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_check_constraint(inspector, _TABLE, _CHECK_NAME):
        if dialect == "sqlite":
            try:
                with op.batch_alter_table(_TABLE) as batch:
                    batch.create_check_constraint(_CHECK_NAME, _CHECK_SQL)
            except Exception:
                # Mirrors n4h5i6j7k8l9 — SQLite CHECK reflection can be
                # flaky. Swallow rather than crash the upgrade.
                pass
        else:
            try:
                op.create_check_constraint(
                    _CHECK_NAME, _TABLE, _CHECK_SQL
                )
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not _has_column(inspector, _TABLE, _COLUMN):
        return

    if dialect == "sqlite":
        with op.batch_alter_table(_TABLE) as batch:
            try:
                batch.drop_constraint(_CHECK_NAME, type_="check")
            except Exception:
                # CHECK reflection on SQLite is flaky; column drop will
                # take it with the rebuild.
                pass
            batch.drop_column(_COLUMN)
    else:
        try:
            op.drop_constraint(_CHECK_NAME, _TABLE, type_="check")
        except Exception:
            pass
        op.drop_column(_TABLE, _COLUMN)
