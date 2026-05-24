"""add export_jobs for durable PDF exports

Revision ID: q6j7k8l9m0n1
Revises: p6j7k8l9m0n1
Create Date: 2026-05-24
"""
import sqlalchemy as sa
from alembic import op

revision = "q6j7k8l9m0n1"
down_revision = "p6j7k8l9m0n1"
branch_labels = None
depends_on = None


def _has_index(inspector, table: str, index_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "export_jobs" not in inspector.get_table_names():
        op.create_table(
            "export_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("format", sa.String(length=16), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
            sa.Column("filters", sa.JSON(), nullable=False),
            sa.Column("result_uri", sa.String(length=512), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("requested_by", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'succeeded', 'failed')",
                name="ck_export_jobs_status",
            ),
            sa.CheckConstraint(
                "format IN ('pdf')",
                name="ck_export_jobs_format",
            ),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "export_jobs", "ix_export_jobs_org_id"):
        op.create_index("ix_export_jobs_org_id", "export_jobs", ["org_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "export_jobs" in inspector.get_table_names():
        op.drop_table("export_jobs")
