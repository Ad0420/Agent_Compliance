"""add compliance review records (Phase 4a F3 — audit-of-the-audit-log)

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-05-12

Workstream F3: a write-only audit log that records every dashboard request
made by a Clerk user whose backend role is ``compliance_reviewer``. The
recording is done by the ``compliance_review_audit`` FastAPI dependency
in ``app/middleware/clerk_auth.py``; this migration only stands up the
table.

Idempotent: skips create if the table already exists (matches the pattern
used by the surrounding migrations so ``create_all`` paths in local dev
don't collide).
"""
import sqlalchemy as sa
from alembic import op

revision = "j0e1f2g3h4i5"
down_revision = "i9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "compliance_review_records" in existing_tables:
        return

    op.create_table(
        "compliance_review_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(),
            sa.ForeignKey("org_memberships.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("clerk_user_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("query_params", sa.JSON(), nullable=True),
        sa.Column("response_metadata", sa.JSON(), nullable=True),
        sa.Column("http_method", sa.String(), nullable=False),
        sa.Column("http_path", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )

    # Per-column indexes for spot lookups (mirrors ``index=True`` in the model).
    op.create_index(
        "ix_compliance_review_records_org_id",
        "compliance_review_records",
        ["org_id"],
    )
    op.create_index(
        "ix_compliance_review_records_membership_id",
        "compliance_review_records",
        ["membership_id"],
    )
    op.create_index(
        "ix_compliance_review_records_clerk_user_id",
        "compliance_review_records",
        ["clerk_user_id"],
    )
    op.create_index(
        "ix_compliance_review_records_request_id",
        "compliance_review_records",
        ["request_id"],
    )

    # Composite indexes for the two read patterns we care about: the
    # review-trail listing for an org (sorted by time desc) and the
    # per-user activity view.
    op.create_index(
        "ix_compliance_review_records_org_occurred",
        "compliance_review_records",
        ["org_id", "occurred_at"],
    )
    op.create_index(
        "ix_compliance_review_records_user_occurred",
        "compliance_review_records",
        ["clerk_user_id", "occurred_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "compliance_review_records" not in existing_tables:
        return

    for ix_name in (
        "ix_compliance_review_records_user_occurred",
        "ix_compliance_review_records_org_occurred",
        "ix_compliance_review_records_request_id",
        "ix_compliance_review_records_clerk_user_id",
        "ix_compliance_review_records_membership_id",
        "ix_compliance_review_records_org_id",
    ):
        try:
            op.drop_index(ix_name, table_name="compliance_review_records")
        except Exception:
            pass

    op.drop_table("compliance_review_records")
