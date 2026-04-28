"""add BLOCK policy action and 'blocked' action_record result

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-26

PR-zeta: ships the BLOCK policy action — pre-action enforcement.

Two CHECK constraints widen:

* ``action_records.ck_ar_result`` — adds ``'blocked'`` to the allowed
  result values. The engine writes this when a block-action policy fires
  so the audit trail still captures the attempted action.
* ``policies.ck_policy_action`` — adds ``'block'`` to the allowed actions.

PostgreSQL supports ``ALTER TABLE ... DROP CONSTRAINT`` directly.
SQLite cannot ``ALTER`` a CHECK constraint — but local dev recreates
tables from models on each fresh setup via ``setup_local.py``, so the
SQLite branch is a no-op (the model already carries the widened
constraint and ``Base.metadata.create_all`` will pick it up on rebuild).
This matches the pattern used by ``b2c3d4e5f6a7_add_fk_cascade_constraints``.
"""
from alembic import op


revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        # SQLite local dev: tables get recreated from models via setup_local.py;
        # the widened CheckConstraint already lives in the model definitions.
        return

    # ── action_records.result: add 'blocked' ───────────────────────────
    op.execute("ALTER TABLE action_records DROP CONSTRAINT IF EXISTS ck_ar_result")
    op.create_check_constraint(
        "ck_ar_result",
        "action_records",
        "result IN ('success', 'failure', 'partial', 'pending', 'blocked')",
    )

    # ── policies.action: add 'block' ───────────────────────────────────
    op.execute("ALTER TABLE policies DROP CONSTRAINT IF EXISTS ck_policy_action")
    op.create_check_constraint(
        "ck_policy_action",
        "policies",
        "action IN ('flag','email','block')",
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        return

    # Restore the narrower constraints. Note: any existing rows with
    # result='blocked' or action='block' would fail this re-add — operators
    # downgrading must clean those rows first.
    op.execute("ALTER TABLE action_records DROP CONSTRAINT IF EXISTS ck_ar_result")
    op.create_check_constraint(
        "ck_ar_result",
        "action_records",
        "result IN ('success', 'failure', 'partial', 'pending')",
    )

    op.execute("ALTER TABLE policies DROP CONSTRAINT IF EXISTS ck_policy_action")
    op.create_check_constraint(
        "ck_policy_action",
        "policies",
        "action IN ('flag','email')",
    )
