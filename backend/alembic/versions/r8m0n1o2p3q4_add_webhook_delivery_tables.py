"""add webhook_deliveries + webhook_delivery_attempts (Wave 2B PR A3)

Revision ID: r8m0n1o2p3q4
Revises: q7k8l9m0n1o2
Create Date: 2026-05-24

Wave 2B PR A3 ships the durable retry + idempotency pipeline. Two new
tables:

  * ``webhook_deliveries``       — parent row, one per (subscription,
                                    event). Scheduling + dedupe anchor.
  * ``webhook_delivery_attempts``— append-only audit trail, one per HTTP try.

Design notes
------------

1. **Partial index on Postgres only.** The sweeper's hot query is
   ``WHERE status='pending' AND next_retry_at <= now()``. Postgres
   supports partial indexes (``CREATE INDEX … WHERE status='pending'``)
   which keep the index ~5× smaller than the composite. SQLite ignores
   the WHERE clause silently on partial-index syntax under some
   pragmas, but we hit it cleanly here by branching on dialect and
   building the plain composite for SQLite. Mirrors the
   ``q7k8l9m0n1o2`` dialect branch.

2. **No ``Boolean`` columns.** Avoids the
   ``DEFAULT 0 → BOOLEAN`` DatatypeMismatch that broke A5's first push
   (see ``q7k8l9m0n1o2`` notes). Status is a string column with a check
   constraint — same shape as ``approvals.status``.

3. **Idempotency anchor.** The unique index on
   ``(subscription_id, idempotency_key)`` is what makes producer-side
   double dispatch a no-op. ``dispatch_event`` reads back the existing
   row on ``IntegrityError`` rather than crashing.

4. **No backfill.** Empty tables on first migration. The sweeper picks
   up new rows once it starts.

5. **Idempotency guards.** Every ``create_table`` / ``create_index`` is
   guarded by an inspector check so re-running after a partial failure
   is a no-op. Same pattern as ``o5i6j7k8l9m0`` / ``p6j7k8l9m0n1`` /
   ``q7k8l9m0n1o2``.

6. **Downgrade.** Drops child first (FK), then parent. SQLite uses
   ``batch_alter_table`` for any column ops; here we only drop tables so
   the plain ``drop_table`` path is portable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "r8m0n1o2p3q4"
down_revision = "q7k8l9m0n1o2"
branch_labels = None
depends_on = None


_PARENT_TABLE = "webhook_deliveries"
_CHILD_TABLE = "webhook_delivery_attempts"

_PARENT_INDEXES_COMMON = (
    "idx_webhook_deliveries_subscription",
    "ix_webhook_deliveries_subscription_id",
    "ix_webhook_deliveries_org_id",
)
_PARENT_INDEX_PG_PARTIAL = "idx_webhook_deliveries_next_retry_at"
_CHILD_INDEX_DELIVERY = "ix_webhook_delivery_attempts_delivery_id"


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ── webhook_deliveries (parent) ───────────────────────────────
    if not _has_table(inspector, _PARENT_TABLE):
        op.create_table(
            _PARENT_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "subscription_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "webhook_subscriptions.id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("succeeded_at", sa.DateTime(), nullable=True),
            sa.Column("aborted_at", sa.DateTime(), nullable=True),
            sa.Column("last_status_code", sa.Integer(), nullable=True),
            sa.Column(
                "idempotency_key", sa.String(length=128), nullable=False
            ),
            sa.CheckConstraint(
                "status IN ('pending','in_progress','succeeded','aborted')",
                name="ck_webhook_delivery_status",
            ),
            sa.UniqueConstraint(
                "subscription_id",
                "idempotency_key",
                name="uq_webhook_deliveries_sub_idem",
            ),
        )
        inspector = sa.inspect(bind)

    # FK index for fast subscription joins (also used by routes for
    # listing deliveries on a subscription).
    if not _has_index(
        inspector, _PARENT_TABLE, "ix_webhook_deliveries_subscription_id"
    ):
        op.create_index(
            "ix_webhook_deliveries_subscription_id",
            _PARENT_TABLE,
            ["subscription_id"],
        )
    if not _has_index(inspector, _PARENT_TABLE, "ix_webhook_deliveries_org_id"):
        op.create_index(
            "ix_webhook_deliveries_org_id",
            _PARENT_TABLE,
            ["org_id"],
        )

    # Dashboard's "recent deliveries on a subscription" view.
    if not _has_index(
        inspector, _PARENT_TABLE, "idx_webhook_deliveries_subscription"
    ):
        op.create_index(
            "idx_webhook_deliveries_subscription",
            _PARENT_TABLE,
            ["subscription_id", "created_at"],
        )

    # Sweeper hot path — partial on Postgres, plain composite on SQLite.
    if not _has_index(
        inspector, _PARENT_TABLE, _PARENT_INDEX_PG_PARTIAL
    ):
        if dialect == "postgresql":
            op.create_index(
                _PARENT_INDEX_PG_PARTIAL,
                _PARENT_TABLE,
                ["next_retry_at"],
                postgresql_where=sa.text("status = 'pending'"),
            )
        else:
            op.create_index(
                _PARENT_INDEX_PG_PARTIAL,
                _PARENT_TABLE,
                ["status", "next_retry_at"],
            )

    # ── webhook_delivery_attempts (child) ─────────────────────────
    if not _has_table(inspector, _CHILD_TABLE):
        op.create_table(
            _CHILD_TABLE,
            sa.Column(
                "id", sa.String(length=36), primary_key=True, nullable=False
            ),
            sa.Column(
                "delivery_id",
                sa.String(length=36),
                sa.ForeignKey(
                    f"{_PARENT_TABLE}.id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column(
                "attempted_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column(
                "response_body_excerpt", sa.String(length=1024), nullable=True
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "delivery_id",
                "attempt_number",
                name="uq_webhook_delivery_attempts_delivery_attempt",
            ),
        )
        inspector = sa.inspect(bind)

    if not _has_index(
        inspector, _CHILD_TABLE, _CHILD_INDEX_DELIVERY
    ):
        op.create_index(
            _CHILD_INDEX_DELIVERY,
            _CHILD_TABLE,
            ["delivery_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _CHILD_TABLE):
        # Drop child indexes that we own (FKs are dropped with the table).
        if _has_index(inspector, _CHILD_TABLE, _CHILD_INDEX_DELIVERY):
            op.drop_index(_CHILD_INDEX_DELIVERY, table_name=_CHILD_TABLE)
        op.drop_table(_CHILD_TABLE)
        inspector = sa.inspect(bind)

    if _has_table(inspector, _PARENT_TABLE):
        for ix_name in (
            *_PARENT_INDEXES_COMMON,
            _PARENT_INDEX_PG_PARTIAL,
        ):
            if _has_index(inspector, _PARENT_TABLE, ix_name):
                op.drop_index(ix_name, table_name=_PARENT_TABLE)
        op.drop_table(_PARENT_TABLE)
