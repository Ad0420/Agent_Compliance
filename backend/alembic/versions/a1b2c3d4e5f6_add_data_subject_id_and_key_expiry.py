"""add data_subject_id and key expiry

Revision ID: a1b2c3d4e5f6
Revises: 24b3df55b205
Create Date: 2026-03-02

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "24b3df55b205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_records", sa.Column("data_subject_id", sa.Text(), nullable=True))
    op.create_index("ix_ar_data_subject_id", "action_records", ["data_subject_id"])
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_ar_data_subject_id", table_name="action_records")
    op.drop_column("action_records", "data_subject_id")
    op.drop_column("api_keys", "expires_at")
