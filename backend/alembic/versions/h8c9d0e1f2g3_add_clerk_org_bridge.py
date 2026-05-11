"""add clerk org bridge: clerk_org_id on organizations, org_memberships, processed_webhook_events

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-05-11

Workstream E3 (Clerk → backend org bridge).

This migration:
1. Adds a nullable, unique-when-set ``clerk_org_id`` column to ``organizations``.
   Nullable so legacy / API-only orgs continue to work; unique so a single
   Clerk org maps to at most one backend org row.
2. Creates ``org_memberships`` linking Clerk users (``clerk_user_id``) to
   backend ``organizations.id`` with a role (``admin`` / ``developer`` /
   ``compliance_reviewer``). Unique on ``(clerk_user_id, clerk_org_id)`` so
   replays of ``organizationMembership.created`` don't double-insert.
3. Creates ``processed_webhook_events`` keyed by Svix message ID to dedupe
   webhook deliveries that Clerk re-sends (Svix is at-least-once).

Idempotent on the SQL level — safe to run against databases where
``Base.metadata.create_all`` already brought the tables up (local dev path).
"""
import sqlalchemy as sa
from alembic import op

revision = "h8c9d0e1f2g3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ── organizations.clerk_org_id ────────────────────────────────────────
    if not _has_column(inspector, "organizations", "clerk_org_id"):
        op.add_column(
            "organizations",
            sa.Column("clerk_org_id", sa.String(), nullable=True),
        )
        # Refresh inspector after DDL so the next get_indexes call sees the
        # new column.
        inspector = sa.inspect(bind)

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("organizations")}
    if "ix_organizations_clerk_org_id" not in existing_indexes:
        # Single index that is also a unique constraint — Postgres handles
        # this fine; SQLite handles UNIQUE indexes natively too.
        op.create_index(
            "ix_organizations_clerk_org_id",
            "organizations",
            ["clerk_org_id"],
            unique=True,
        )

    existing_tables = set(inspector.get_table_names())

    # ── org_memberships ──────────────────────────────────────────────────
    if "org_memberships" not in existing_tables:
        op.create_table(
            "org_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("clerk_user_id", sa.String(), nullable=False),
            sa.Column("clerk_org_id", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "clerk_user_id", "clerk_org_id", name="uq_user_per_org"
            ),
            sa.CheckConstraint(
                "role IN ('admin', 'developer', 'compliance_reviewer')",
                name="ck_org_membership_role",
            ),
        )
        op.create_index(
            "ix_org_memberships_org_id", "org_memberships", ["org_id"]
        )
        op.create_index(
            "ix_org_memberships_clerk_user_id",
            "org_memberships",
            ["clerk_user_id"],
        )
        op.create_index(
            "ix_org_memberships_clerk_org_id",
            "org_memberships",
            ["clerk_org_id"],
        )

    # ── processed_webhook_events ─────────────────────────────────────────
    if "processed_webhook_events" not in existing_tables:
        op.create_table(
            "processed_webhook_events",
            sa.Column("svix_id", sa.String(64), primary_key=True),
            sa.Column("event_type", sa.String(128), nullable=False),
            sa.Column(
                "processed_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # Silence unused-variable lint for the dialect read above; we keep it
    # in scope so future branches can fork SQLite vs Postgres behaviour.
    _ = dialect


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "processed_webhook_events" in existing_tables:
        op.drop_table("processed_webhook_events")

    if "org_memberships" in existing_tables:
        for ix_name in (
            "ix_org_memberships_clerk_org_id",
            "ix_org_memberships_clerk_user_id",
            "ix_org_memberships_org_id",
        ):
            try:
                op.drop_index(ix_name, table_name="org_memberships")
            except Exception:
                # Index may not exist on older databases — best-effort drop.
                pass
        op.drop_table("org_memberships")

    if _has_column(inspector, "organizations", "clerk_org_id"):
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("organizations")}
        if "ix_organizations_clerk_org_id" in existing_indexes:
            op.drop_index(
                "ix_organizations_clerk_org_id", table_name="organizations"
            )
        # SQLite can't drop columns pre-3.35; production is Postgres so this
        # path is exercised there. Local dev wipes the SQLite file anyway.
        with op.batch_alter_table("organizations") as batch:
            batch.drop_column("clerk_org_id")
