"""add policy tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-12

Adds `policies` and `policy_violations` tables for the Policy Enforcement Engine.
Both are idempotent — safe to run against databases where SQLAlchemy's create_all
already created the tables.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "policies" not in existing:
        op.create_table(
            "policies",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("condition_type", sa.String(50), nullable=False),
            sa.Column("condition_params", sa.JSON(), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.CheckConstraint(
                "condition_type IN ('unknown_agent','missing_reasoning','failure_rate','high_failure_burst','consecutive_failures')",
                name="ck_policy_condition_type",
            ),
            sa.CheckConstraint("action IN ('flag','email')", name="ck_policy_action"),
            sa.CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_policy_severity"),
        )
        op.create_index("idx_policies_org", "policies", ["org_id"])
        op.create_index("idx_policies_org_active", "policies", ["org_id", "is_active"])

    if "policy_violations" not in existing:
        op.create_table(
            "policy_violations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("policy_id", sa.String(36), sa.ForeignKey("policies.id", ondelete="SET NULL"), nullable=True),
            sa.Column("record_id", sa.String(36), sa.ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("triggered_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", sa.Text(), nullable=True),
            sa.CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_violation_severity"),
        )
        op.create_index("idx_violations_org", "policy_violations", ["org_id"])
        op.create_index("idx_violations_org_time", "policy_violations", ["org_id", "triggered_at"])
        op.create_index("idx_violations_policy", "policy_violations", ["policy_id"])
        op.create_index("idx_violations_record", "policy_violations", ["record_id"])


def downgrade() -> None:
    op.drop_table("policy_violations")
    op.drop_table("policies")
