"""clerk org bridge follow-up: soft-delete on organizations, success+updated_at columns

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-05-12

Post-merge audit fixes for PR #164 (Clerk org bridge). See
``backend/app/routes/clerk_webhooks.py`` and ``backend/app/middleware/clerk_auth.py``
for the rationale.

Adds:
  - ``organizations.deleted_at``           — soft-delete marker (NULLable).
  - ``organizations.scrubbed_clerk_org_id``— stash for the old clerk_org_id
    when the org is soft-deleted (frees the unique constraint for reuse).
  - ``org_memberships.updated_at``         — gates the freshness re-check
    against Clerk's REST API; backfilled to ``created_at`` for existing rows.
  - ``processed_webhook_events.success``   — distinguishes deduped-success
    from a tombstoned-failure dedupe row.

Idempotent on the SQL level — safe to run against databases where
``Base.metadata.create_all`` already brought the columns up (local dev path).
"""
import sqlalchemy as sa
from alembic import op

revision = "i9d0e1f2g3h4"
down_revision = "h8c9d0e1f2g3"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── organizations.deleted_at + scrubbed_clerk_org_id ─────────────────
    if not _has_column(inspector, "organizations", "deleted_at"):
        op.add_column(
            "organizations",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        inspector = sa.inspect(bind)
        existing_indexes = {
            ix["name"] for ix in inspector.get_indexes("organizations")
        }
        if "ix_organizations_deleted_at" not in existing_indexes:
            op.create_index(
                "ix_organizations_deleted_at",
                "organizations",
                ["deleted_at"],
            )

    if not _has_column(inspector, "organizations", "scrubbed_clerk_org_id"):
        op.add_column(
            "organizations",
            sa.Column("scrubbed_clerk_org_id", sa.String(), nullable=True),
        )

    # ── org_memberships.updated_at ───────────────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "org_memberships", "updated_at"):
        # Add nullable first so existing rows can be backfilled, then
        # backfill from created_at, then make NOT NULL with a server default
        # so future inserts that omit the column don't fail.
        op.add_column(
            "org_memberships",
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.execute("UPDATE org_memberships SET updated_at = created_at")

        dialect = bind.dialect.name
        if dialect == "sqlite":
            # SQLite can't ALTER COLUMN SET NOT NULL in place; the column
            # already has values + a default in app code. Leave as-is for
            # test scaffolding; production runs Postgres which takes the
            # branch below.
            pass
        else:
            op.alter_column(
                "org_memberships",
                "updated_at",
                existing_type=sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            )

    # ── processed_webhook_events.success ─────────────────────────────────
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "processed_webhook_events", "success"):
        # Existing rows predate the success flag — they were inserted only
        # after a successful handler under the old flow, so backfill TRUE.
        op.add_column(
            "processed_webhook_events",
            sa.Column(
                "success",
                sa.Boolean(),
                nullable=True,
                server_default=sa.text("false"),
            ),
        )
        op.execute("UPDATE processed_webhook_events SET success = TRUE")
        dialect = bind.dialect.name
        if dialect == "sqlite":
            pass
        else:
            op.alter_column(
                "processed_webhook_events",
                "success",
                existing_type=sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "processed_webhook_events", "success"):
        with op.batch_alter_table("processed_webhook_events") as batch:
            batch.drop_column("success")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "org_memberships", "updated_at"):
        with op.batch_alter_table("org_memberships") as batch:
            batch.drop_column("updated_at")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "organizations", "scrubbed_clerk_org_id"):
        with op.batch_alter_table("organizations") as batch:
            batch.drop_column("scrubbed_clerk_org_id")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "organizations", "deleted_at"):
        existing_indexes = {
            ix["name"] for ix in inspector.get_indexes("organizations")
        }
        if "ix_organizations_deleted_at" in existing_indexes:
            op.drop_index(
                "ix_organizations_deleted_at", table_name="organizations"
            )
        with op.batch_alter_table("organizations") as batch:
            batch.drop_column("deleted_at")
