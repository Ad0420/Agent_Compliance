"""add webhook_subscriptions table

Revision ID: f6a7b8c9d0e1
Revises: ac5d1cf8f9d4
Create Date: 2026-04-26

Adds the `webhook_subscriptions` table backing outbound webhook delivery
for compliance events (policy violations, approval lifecycle, etc.).
Idempotent — safe to run against databases where SQLAlchemy's create_all
already created the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "ac5d1cf8f9d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "webhook_subscriptions" not in existing:
        op.create_table(
            "webhook_subscriptions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("secret", sa.String(64), nullable=False),
            sa.Column("event_types", sa.JSON(), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
            sa.Column("last_delivery_status", sa.String(20), nullable=True),
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.CheckConstraint(
                "url LIKE 'http://%' OR url LIKE 'https://%'",
                name="ck_webhook_url_scheme",
            ),
        )
        op.create_index(
            "idx_webhook_subscriptions_org",
            "webhook_subscriptions",
            ["org_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()
    if "webhook_subscriptions" in existing:
        op.drop_index(
            "idx_webhook_subscriptions_org",
            table_name="webhook_subscriptions",
        )
        op.drop_table("webhook_subscriptions")
