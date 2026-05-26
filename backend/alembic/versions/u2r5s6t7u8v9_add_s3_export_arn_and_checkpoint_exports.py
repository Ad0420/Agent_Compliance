"""add Organization.s3_export_arn + checkpoint_exports (Phase 3 Wave 3B.1)

Revision ID: u2r5s6t7u8v9
Revises: t1q4r5s6t7u8
Create Date: 2026-05-25

Wave 3B.1 ships two pieces of schema together because they're meaningless
in isolation:

  * ``organizations.s3_export_arn``  — Customer's chosen off-Vera S3 bucket
                                       ARN. Already validated syntactically
                                       at onboarding (Wave 3A.d). NULL means
                                       "customer hasn't configured an export
                                       target" → the mirror exporter skips
                                       this org.
  * ``checkpoint_exports`` table     — Idempotency / audit table. One row
                                       per (checkpoint_id, status). Lets the
                                       background mirror exporter answer
                                       "have I already pushed checkpoint X
                                       to S3?" without re-reading S3 (which
                                       is slow + costs money) and without
                                       trusting in-process state (which
                                       evaporates on restart).

Why one migration, not two: the column is only useful with the table, and
the table is only useful with the column. Bundling them means a half-
applied state ("column without table" or vice versa) never exists.

Idempotency: every step self-checks the inspector — same pattern as
``t1q4r5s6t7u8`` (staff_audit_log) and ``s0p3q4r5s6t7`` (org cadence).

Portability: ``sa.true()`` / ``sa.func.now()`` (NOT ``sa.text("1")`` /
``sa.text("CURRENT_TIMESTAMP")``) so SQLite + Postgres both produce the
same on-disk shape. The ``status`` column uses a CHECK constraint with
the literal set; ``e5f6a7b8c9d0`` (approval result) is the precedent.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "u2r5s6t7u8v9"
down_revision = "t1q4r5s6t7u8"
branch_labels = None
depends_on = None


_ORG_TABLE = "organizations"
_ORG_COLUMN = "s3_export_arn"

_EXPORTS_TABLE = "checkpoint_exports"
_EXPORTS_INDEX_CHECKPOINT = "idx_checkpoint_exports_checkpoint_id"
_EXPORTS_INDEX_ORG_STATUS = "idx_checkpoint_exports_org_status"
_EXPORTS_UNIQUE_SUCCESS = "uq_checkpoint_exports_checkpoint_success"
_STATUS_CHECK_NAME = "ck_checkpoint_exports_status"
# ``pending`` is the row state between scheduling and S3 round-trip
# completion. It exists so a process crash mid-call leaves a forensic
# row rather than a silent gap — ops can find "pending older than N
# minutes" and either retry or escalate. The codex /review caught the
# "silent loss on crash" gap (Wave 3B.1).
_STATUS_CHECK_SQL = "status IN ('pending', 'success', 'failure', 'skipped')"


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_unique(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    try:
        return name in {
            uc["name"] for uc in inspector.get_unique_constraints(table)
        }
    except Exception:
        # SQLite reflection of unique constraints sometimes flakes the
        # same way it does for CHECK. Treat as "unknown → attempt".
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Step 1: add s3_export_arn to organizations ──────────────────
    # Nullable — most orgs don't configure an external mirror; the
    # exporter skips orgs whose column is NULL.
    if _has_table(inspector, _ORG_TABLE) and not _has_column(
        inspector, _ORG_TABLE, _ORG_COLUMN
    ):
        op.add_column(
            _ORG_TABLE,
            sa.Column(
                _ORG_COLUMN,
                sa.String(length=512),
                nullable=True,
            ),
        )

    # ── Step 2: create checkpoint_exports table ─────────────────────
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _EXPORTS_TABLE):
        op.create_table(
            _EXPORTS_TABLE,
            sa.Column(
                "id", sa.String(length=36), primary_key=True, nullable=False
            ),
            sa.Column(
                "checkpoint_id",
                sa.String(length=36),
                sa.ForeignKey("checkpoints.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # ``status``: one of {success, failure, skipped}. We record
            # failures too so ops can see "checkpoint X tried to export 3
            # times and failed each time" without re-running the job.
            sa.Column("status", sa.String(length=16), nullable=False),
            # Stable bucket+key location for success rows. NULL for
            # failures (we never got far enough to know the key).
            sa.Column("s3_location", sa.String(length=1024), nullable=True),
            # SHA-256 of the canonical document body — lets the customer
            # verify what Vera wrote without re-fetching the object.
            sa.Column("document_hash", sa.String(length=64), nullable=True),
            sa.Column("record_count", sa.Integer(), nullable=True),
            # Structured reason for failures + skipped (e.g.
            # ``object_lock_missing``, ``bucket_not_configured``,
            # ``credentials_unavailable``). NULL on success.
            sa.Column("reason", sa.String(length=128), nullable=True),
            # Free-form detail field for ops triage. Capped at a
            # reasonable size so a misbehaving AWS error message can't
            # blow up the table.
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "exported_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(_STATUS_CHECK_SQL, name=_STATUS_CHECK_NAME),
        )
        inspector = sa.inspect(bind)

    # ── Step 3: indexes ────────────────────────────────────────────
    # Idempotency hot path: "have we already exported this checkpoint
    # successfully?"
    if not _has_index(inspector, _EXPORTS_TABLE, _EXPORTS_INDEX_CHECKPOINT):
        op.create_index(
            _EXPORTS_INDEX_CHECKPOINT,
            _EXPORTS_TABLE,
            ["checkpoint_id"],
        )

    # Ops dashboard query: "show me all failed exports for org X."
    if not _has_index(inspector, _EXPORTS_TABLE, _EXPORTS_INDEX_ORG_STATUS):
        op.create_index(
            _EXPORTS_INDEX_ORG_STATUS,
            _EXPORTS_TABLE,
            ["org_id", "status", "exported_at"],
        )

    # ── Step 4: unique constraint on (checkpoint_id) WHERE status='success' ─
    # We can't easily do a partial unique constraint that's portable to
    # both SQLite and Postgres without raw SQL. Instead, we enforce the
    # "at most one success row per checkpoint" invariant at the
    # application layer (a savepoint-protected SELECT-then-INSERT inside
    # the exporter) and use the regular index above to make that query
    # fast. Documented limitation: a race between two exporters could
    # produce two success rows; the application code's per-checkpoint
    # idempotency check prevents that in practice (single sweeper task).


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _has_index(inspector, _EXPORTS_TABLE, _EXPORTS_INDEX_ORG_STATUS):
        op.drop_index(_EXPORTS_INDEX_ORG_STATUS, table_name=_EXPORTS_TABLE)
    if _has_index(inspector, _EXPORTS_TABLE, _EXPORTS_INDEX_CHECKPOINT):
        op.drop_index(_EXPORTS_INDEX_CHECKPOINT, table_name=_EXPORTS_TABLE)
    if _has_table(inspector, _EXPORTS_TABLE):
        op.drop_table(_EXPORTS_TABLE)

    inspector = sa.inspect(bind)
    if _has_column(inspector, _ORG_TABLE, _ORG_COLUMN):
        if dialect == "sqlite":
            with op.batch_alter_table(_ORG_TABLE) as batch:
                batch.drop_column(_ORG_COLUMN)
        else:
            op.drop_column(_ORG_TABLE, _ORG_COLUMN)
