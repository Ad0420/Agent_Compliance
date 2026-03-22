"""add FK cascade/restrict/set-null constraints

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22

Replaces the unnamed, no-action foreign keys created by the initial
migration with explicitly named keys that enforce:
  - agents, api_keys, chain_state, checkpoints → org  : CASCADE
  - action_records → org                               : RESTRICT
  - action_records → agent                             : SET NULL

SQLite (local dev) is skipped: FK enforcement in SQLite requires
PRAGMA foreign_keys=ON and the tables are rebuilt from models on
each fresh dev setup via setup_local.py, so the ondelete rules are
already correct there.
"""
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        return

    # ── Drop auto-named FK constraints created by initial migration ──
    op.execute("ALTER TABLE agents         DROP CONSTRAINT IF EXISTS agents_org_id_fkey")
    op.execute("ALTER TABLE api_keys       DROP CONSTRAINT IF EXISTS api_keys_org_id_fkey")
    op.execute("ALTER TABLE chain_state    DROP CONSTRAINT IF EXISTS chain_state_org_id_fkey")
    op.execute("ALTER TABLE checkpoints    DROP CONSTRAINT IF EXISTS checkpoints_org_id_fkey")
    op.execute("ALTER TABLE action_records DROP CONSTRAINT IF EXISTS action_records_org_id_fkey")
    op.execute("ALTER TABLE action_records DROP CONSTRAINT IF EXISTS action_records_agent_id_fkey")

    # ── Recreate with proper ondelete rules ──────────────────────────
    op.create_foreign_key(
        "fk_agents_org_id", "agents", "organizations", ["org_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_api_keys_org_id", "api_keys", "organizations", ["org_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_chain_state_org_id", "chain_state", "organizations", ["org_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_checkpoints_org_id", "checkpoints", "organizations", ["org_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_ar_org_id", "action_records", "organizations", ["org_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ar_agent_id", "action_records", "agents", ["agent_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        return

    op.drop_constraint("fk_agents_org_id",     "agents",         type_="foreignkey")
    op.drop_constraint("fk_api_keys_org_id",    "api_keys",       type_="foreignkey")
    op.drop_constraint("fk_chain_state_org_id", "chain_state",    type_="foreignkey")
    op.drop_constraint("fk_checkpoints_org_id", "checkpoints",    type_="foreignkey")
    op.drop_constraint("fk_ar_org_id",          "action_records", type_="foreignkey")
    op.drop_constraint("fk_ar_agent_id",        "action_records", type_="foreignkey")

    # Restore unnamed no-action FKs matching the original initial schema
    op.create_foreign_key(None, "agents",         "organizations", ["org_id"],    ["id"])
    op.create_foreign_key(None, "api_keys",       "organizations", ["org_id"],    ["id"])
    op.create_foreign_key(None, "chain_state",    "organizations", ["org_id"],    ["id"])
    op.create_foreign_key(None, "checkpoints",    "organizations", ["org_id"],    ["id"])
    op.create_foreign_key(None, "action_records", "organizations", ["org_id"],    ["id"])
    op.create_foreign_key(None, "action_records", "agents",        ["agent_id"],  ["id"])
