"""add alert_email to organizations

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-08

Adds the alert_email column to the organizations table.
When set, Vera sends a tamper-alert email to this address
if chain or checkpoint verification returns is_valid=False.
"""
import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard against the column already existing (e.g. if SQLAlchemy's create_all
    # ran before alembic was initialized and created the table with the new model).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("organizations")]
    if "alert_email" not in existing:
        op.add_column(
            "organizations",
            sa.Column("alert_email", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("organizations", "alert_email")
