"""create customers, customer_agents, baa_agreements, baa_scopes (Phase 1 PR 1)

Revision ID: m3g4h5i6j7k8
Revises: l2f3g4h5i6j7
Create Date: 2026-05-23

Phase 1 introduces the Customer concept: the *customer-of-the-customer*
(e.g. a hospital that the AI vendor — Vera's actual customer — serves).
Customers, their agents, and BAA agreements live in dedicated tables so
the AI Coverage Matrix and BAA scope enforcement can operate without
scanning the action_records hot table.

Tables created:

  customers
    The hospital / bank / employer that the operator org serves. Identified
    by a free-form ``tenant_id`` string the SDK passes via vera.tenant().
    UNIQUE (org_id, tenant_id) so the same tenant string is scoped per-org.
    ``baa_status`` CHECK includes ``'terminated'`` so a Customer whose BAA
    was rescinded is distinguishable from one that simply expired.

  customer_agents
    The historical record of which agent_types have ever served a customer.
    ``agent_type`` is stamped HISTORICALLY at first observation (Codex E1):
    changing Agent metadata later must NOT rewrite past compliance coverage,
    so ``agent_type`` lives on this row, not on the ``agents`` row.
    ``agent_id`` is nullable + SET NULL on delete because auto-discovery may
    create a CustomerAgent row before any Agent row exists (in which case
    agent_id is NULL until the next agent registration backfills it), and
    deleting an Agent later must not delete the historical coverage record.

  baa_agreements
    One row per BAA between the operator org and a customer. Most lifecycle
    fields are nullable on draft — they fill in as the BAA flows through
    upload → effective → expiry. ``document_uri`` is populated by the BAA
    upload endpoint (Phase 1 PR 10), not by this PR. A temporal CHECK
    constraint (``ck_baa_temporal_order``) refuses ``effective_at >
    expires_at`` when both are present — a data-shape guard for ops typos.

  baa_scopes
    The (covered_services, covered_agent_types) scope of a BAA. Required
    by Codex E2 so Phase 2/3 gate checks can be scope-aware. ``is_unrestricted``
    is the explicit wildcard flag: when True, the two list columns are
    advisory only and the BAA covers everything. Existing / backfilled
    BAAs use a broad scope (there are no real BAAs today; this is a
    forward-looking design).

All FKs use the same cascade conventions as existing models:
  - org_id → organizations: CASCADE (already the convention for per-org rows)
  - customer_id → customers: CASCADE (agents and BAAs follow the customer)
  - agent_id → agents: SET NULL (historical coverage outlives the agent row)
  - baa_agreement_id → baa_agreements: CASCADE (scopes follow the BAA)

Idempotency: every CREATE TABLE and every CREATE INDEX is guarded by an
independent existence check. The previous structure nested index creation
inside the ``if 'table' not in existing_tables`` block — if the table was
pre-created by ``Base.metadata.create_all`` (test paths) or by a partial-
apply recovery, the indexes were never created. Each step now self-checks.
"""
import sqlalchemy as sa
from alembic import op

revision = "m3g4h5i6j7k8"
down_revision = "l2f3g4h5i6j7"
branch_labels = None
depends_on = None


def _has_index(inspector, table: str, index_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── customers ────────────────────────────────────────────
    if "customers" not in existing_tables:
        op.create_table(
            "customers",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending_setup'"),
            ),
            sa.Column(
                "baa_status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'missing'"),
            ),
            sa.Column("contact_email", sa.String(length=255), nullable=True),
            sa.Column("jurisdictions", sa.JSON(), nullable=True),
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
            sa.UniqueConstraint(
                "org_id", "tenant_id", name="uq_customer_org_tenant"
            ),
            sa.CheckConstraint(
                "status IN ('pending_setup', 'active', 'suspended', 'archived')",
                name="ck_customer_status",
            ),
            sa.CheckConstraint(
                "baa_status IN ('missing', 'pending', 'active', 'expired', 'terminated')",
                name="ck_customer_baa_status",
            ),
        )

    # Indexes for customers live OUTSIDE the create_table guard so they
    # still apply if the table was pre-created via Base.metadata.create_all
    # in test paths or by a partial-apply recovery.
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "customers", "idx_customer_org_status"):
        op.create_index(
            "idx_customer_org_status", "customers", ["org_id", "status"]
        )
    if not _has_index(inspector, "customers", "idx_customer_tenant"):
        op.create_index("idx_customer_tenant", "customers", ["tenant_id"])

    # ── customer_agents ──────────────────────────────────────
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "customer_agents" not in existing_tables:
        op.create_table(
            "customer_agents",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "customer_id",
                sa.String(length=36),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "agent_id",
                sa.String(length=36),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("agent_type", sa.String(length=64), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'auto_discovered'"),
            ),
            sa.Column(
                "confidence",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'high'"),
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "customer_id", "agent_type", name="uq_customer_agent_type"
            ),
            sa.CheckConstraint(
                "source IN ('auto_discovered', 'declared', 'csv_import')",
                name="ck_customer_agent_source",
            ),
            sa.CheckConstraint(
                "confidence IN ('low', 'medium', 'high')",
                name="ck_customer_agent_confidence",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'retired')",
                name="ck_customer_agent_status",
            ),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "customer_agents", "idx_ca_customer"):
        op.create_index(
            "idx_ca_customer", "customer_agents", ["customer_id"]
        )

    # ── baa_agreements ───────────────────────────────────────
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "baa_agreements" not in existing_tables:
        op.create_table(
            "baa_agreements",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "customer_id",
                sa.String(length=36),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("document_uri", sa.String(length=512), nullable=True),
            sa.Column("effective_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("signed_at", sa.DateTime(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'draft'"),
            ),
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
            sa.CheckConstraint(
                "status IN ('draft', 'active', 'expired', 'terminated')",
                name="ck_baa_status",
            ),
            sa.CheckConstraint(
                "effective_at IS NULL OR expires_at IS NULL OR effective_at <= expires_at",
                name="ck_baa_temporal_order",
            ),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "baa_agreements", "idx_baa_customer_status"):
        op.create_index(
            "idx_baa_customer_status",
            "baa_agreements",
            ["customer_id", "status"],
        )

    # ── baa_scopes ───────────────────────────────────────────
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "baa_scopes" not in existing_tables:
        op.create_table(
            "baa_scopes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "baa_agreement_id",
                sa.String(length=36),
                sa.ForeignKey("baa_agreements.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("covered_services", sa.JSON(), nullable=False),
            sa.Column("covered_agent_types", sa.JSON(), nullable=False),
            sa.Column(
                "is_unrestricted",
                sa.Boolean(),
                nullable=False,
                # ``sa.false()`` emits ``FALSE`` on Postgres and ``0`` on SQLite;
                # ``sa.text("0")`` raises ``DatatypeMismatch`` on Postgres BOOLEAN.
                server_default=sa.false(),
            ),
            sa.Column("granted_at", sa.DateTime(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "baa_scopes", "idx_scope_baa"):
        op.create_index(
            "idx_scope_baa", "baa_scopes", ["baa_agreement_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Drop in reverse FK order: scopes → agreements → customer_agents → customers
    if "baa_scopes" in existing_tables:
        try:
            op.drop_index("idx_scope_baa", table_name="baa_scopes")
        except Exception:
            pass
        op.drop_table("baa_scopes")

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "baa_agreements" in existing_tables:
        try:
            op.drop_index(
                "idx_baa_customer_status", table_name="baa_agreements"
            )
        except Exception:
            pass
        op.drop_table("baa_agreements")

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "customer_agents" in existing_tables:
        try:
            op.drop_index("idx_ca_customer", table_name="customer_agents")
        except Exception:
            pass
        op.drop_table("customer_agents")

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "customers" in existing_tables:
        for ix in ("idx_customer_tenant", "idx_customer_org_status"):
            try:
                op.drop_index(ix, table_name="customers")
            except Exception:
                pass
        op.drop_table("customers")
