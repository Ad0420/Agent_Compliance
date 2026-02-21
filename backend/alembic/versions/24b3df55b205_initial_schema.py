"""initial schema

Revision ID: 24b3df55b205
Revises:
Create Date: 2026-02-16 15:46:42.188416

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24b3df55b205'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── Organizations ────────────────────────────────────────
    op.create_table('organizations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Agents ───────────────────────────────────────────────
    op.create_table('agents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_agent_org_name')
    )

    # ── API Keys ─────────────────────────────────────────────
    op.create_table('api_keys',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('key_hash', sa.String(), nullable=False),
        sa.Column('key_prefix', sa.String(), nullable=False),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash')
    )

    # ── Chain State ──────────────────────────────────────────
    op.create_table('chain_state',
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('latest_sequence', sa.BigInteger(), nullable=False),
        sa.Column('latest_hash', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('org_id')
    )

    # ── Checkpoints ──────────────────────────────────────────
    op.create_table('checkpoints',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('sequence_at_checkpoint', sa.BigInteger(), nullable=False),
        sa.Column('hash_at_checkpoint', sa.Text(), nullable=False),
        sa.Column('merkle_root', sa.Text(), nullable=True),
        sa.Column('key_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('signature', sa.Text(), nullable=False),
        sa.Column('external_receipt', sa.JSON(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Action Records ───────────────────────────────────────
    op.create_table('action_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('sequence_number', sa.BigInteger(), nullable=False),
        sa.Column('previous_hash', sa.Text(), nullable=False),
        sa.Column('record_hash', sa.Text(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('authorized_by', sa.Text(), nullable=False),
        sa.Column('authorization_scope', sa.Text(), nullable=True),
        sa.Column('delegation_chain', sa.JSON(), nullable=False),
        sa.Column('agent_id', sa.String(length=36), nullable=True),
        sa.Column('agent_name', sa.Text(), nullable=False),
        sa.Column('agent_version', sa.Text(), nullable=True),
        sa.Column('model_id', sa.Text(), nullable=True),
        sa.Column('model_version', sa.Text(), nullable=True),
        sa.Column('framework', sa.Text(), nullable=True),
        sa.Column('framework_version', sa.Text(), nullable=True),
        sa.Column('action_type', sa.Text(), nullable=False),
        sa.Column('action_name', sa.Text(), nullable=False),
        sa.Column('action_description', sa.Text(), nullable=True),
        sa.Column('action_timestamp', sa.DateTime(), nullable=False),
        sa.Column('target_system', sa.Text(), nullable=True),
        sa.Column('target_resource', sa.Text(), nullable=True),
        sa.Column('result', sa.String(length=20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=False),
        sa.Column('policies_applied', sa.JSON(), nullable=False),
        sa.Column('environment', sa.JSON(), nullable=False),
        sa.Column('reasoning', sa.JSON(), nullable=False),
        sa.Column('outcome', sa.JSON(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('signature', sa.Text(), nullable=True),
        sa.CheckConstraint("result IN ('success', 'failure', 'partial', 'pending')", name='ck_ar_result'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'sequence_number', name='uq_ar_org_sequence')
    )

    # ── Indexes (matching init.sql) ──────────────────────────
    op.create_index('idx_api_keys_org', 'api_keys', ['org_id'])
    op.create_index('idx_api_keys_hash', 'api_keys', ['key_hash'])
    op.create_index('idx_agents_org', 'agents', ['org_id'])
    op.create_index('idx_ar_org_seq', 'action_records', ['org_id', sa.text('sequence_number DESC')])
    op.create_index('idx_ar_org_time', 'action_records', ['org_id', sa.text('action_timestamp DESC')])
    op.create_index('idx_ar_recorded', 'action_records', ['org_id', sa.text('recorded_at DESC')])
    op.create_index('idx_ar_agent', 'action_records', ['org_id', 'agent_name'])
    op.create_index('idx_ar_action', 'action_records', ['org_id', 'action_type', 'action_name'])
    op.create_index('idx_ar_result', 'action_records', ['org_id', 'result'])
    op.create_index('idx_ar_authorized', 'action_records', ['org_id', 'authorized_by'])
    op.create_index('idx_ar_hash', 'action_records', ['record_hash'])

    # ── Append-only triggers (PostgreSQL only) ───────────────
    # These are the critical immutability enforcement triggers.
    # For SQLite, triggers are installed at app startup via install_sqlite_triggers().
    dialect = op.get_bind().dialect.name
    if dialect == 'postgresql':
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_append_only()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION
                    'action_records is an append-only ledger. UPDATE and DELETE are not permitted. '
                    'Record ID: %%, Sequence: %%', OLD.id, OLD.sequence_number;
                RETURN NULL;
            END;
            $$;
        """)
        op.execute("""
            CREATE TRIGGER no_update_action_records
                BEFORE UPDATE ON action_records
                FOR EACH ROW EXECUTE FUNCTION enforce_append_only();
        """)
        op.execute("""
            CREATE TRIGGER no_delete_action_records
                BEFORE DELETE ON action_records
                FOR EACH ROW EXECUTE FUNCTION enforce_append_only();
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_chain_state_monotonic()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.latest_sequence < OLD.latest_sequence THEN
                    RAISE EXCEPTION
                        'chain_state sequence can only increase. '
                        'Attempted to set %% from %%', NEW.latest_sequence, OLD.latest_sequence;
                END IF;
                RETURN NEW;
            END;
            $$;
        """)
        op.execute("""
            CREATE TRIGGER chain_state_monotonic
                BEFORE UPDATE ON chain_state
                FOR EACH ROW EXECUTE FUNCTION enforce_chain_state_monotonic();
        """)
        # Full-text search index (PostgreSQL only)
        op.execute("""
            CREATE INDEX idx_ar_fts ON action_records
                USING GIN (to_tsvector('english',
                    action_name || ' ' || coalesce(target_resource, '') || ' ' || coalesce(action_description, '')));
        """)
        # GIN indexes for JSONB queries (PostgreSQL only)
        op.execute("CREATE INDEX idx_ar_input_data ON action_records USING GIN (input_data);")
        op.execute("CREATE INDEX idx_ar_metadata ON action_records USING GIN (metadata);")


def downgrade() -> None:
    """Downgrade schema."""
    dialect = op.get_bind().dialect.name
    if dialect == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS no_update_action_records ON action_records;")
        op.execute("DROP TRIGGER IF EXISTS no_delete_action_records ON action_records;")
        op.execute("DROP TRIGGER IF EXISTS chain_state_monotonic ON chain_state;")
        op.execute("DROP FUNCTION IF EXISTS enforce_append_only();")
        op.execute("DROP FUNCTION IF EXISTS enforce_chain_state_monotonic();")

    op.drop_table('action_records')
    op.drop_table('checkpoints')
    op.drop_table('chain_state')
    op.drop_table('api_keys')
    op.drop_table('agents')
    op.drop_table('organizations')
