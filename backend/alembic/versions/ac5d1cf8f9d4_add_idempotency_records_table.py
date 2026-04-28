"""add idempotency_records table

Revision ID: ac5d1cf8f9d4
Revises: e5f6a7b8c9d0
Create Date: 2026-04-27 03:55:14.300081

Adds the ``idempotency_records`` table that caches (org_id, key) -> response_body
for 24h so duplicate POSTs to /v1/actions and /v1/actions/batch (e.g. the
SDK's retry loop after a network blip) replay the original response instead
of inserting a second action_records row.

Idempotent — safe to run against databases where SQLAlchemy's ``create_all``
already created the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac5d1cf8f9d4'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "idempotency_records" not in existing:
        op.create_table(
            "idempotency_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key", sa.String(64), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("response_body", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "key", name="uq_idem_org_key"),
        )
        op.create_index(
            "ix_idempotency_records_org_id",
            "idempotency_records",
            ["org_id"],
        )
        op.create_index(
            "ix_idempotency_records_expires_at",
            "idempotency_records",
            ["expires_at"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()
    if "idempotency_records" in existing:
        op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
        op.drop_index("ix_idempotency_records_org_id", table_name="idempotency_records")
        op.drop_table("idempotency_records")
