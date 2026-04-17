"""add approvals table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-16

Adds `approvals` table for the Human-in-the-Loop approval workflow.
Idempotent — safe to run against databases where SQLAlchemy's create_all
already created the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "approvals" not in existing:
        op.create_table(
            "approvals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("request_record_id", sa.String(36), sa.ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolution_record_id", sa.String(36), sa.ForeignKey("action_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("requested_by_agent", sa.String(500), nullable=False),
            sa.Column("data_subject_id", sa.Text(), nullable=True),
            sa.Column("action_name", sa.String(500), nullable=False),
            sa.Column("action_summary", sa.Text(), nullable=True),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("risk_tier", sa.String(20), nullable=False, server_default="high"),
            sa.Column("approvers_required", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("decisions", sa.JSON(), nullable=False),
            sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "risk_tier IN ('low','medium','high','critical')",
                name="ck_approval_risk_tier",
            ),
            sa.CheckConstraint(
                "status IN ('pending','approved','rejected','expired','cancelled')",
                name="ck_approval_status",
            ),
            sa.CheckConstraint(
                "approvers_required >= 1",
                name="ck_approval_approvers_required",
            ),
        )
        op.create_index("idx_approvals_org", "approvals", ["org_id"])
        op.create_index("idx_approvals_org_status", "approvals", ["org_id", "status"])
        op.create_index("idx_approvals_data_subject", "approvals", ["data_subject_id"])


def downgrade() -> None:
    op.drop_table("approvals")
