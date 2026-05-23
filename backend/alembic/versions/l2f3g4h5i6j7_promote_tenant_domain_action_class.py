"""promote tenant_id, domain, action_class to indexed ActionRecord columns (Phase 1 PR 1)

Revision ID: l2f3g4h5i6j7
Revises: k1f2g3h4i5j6
Create Date: 2026-05-23

Phase 1 of the v1 implementation plan promotes three new fields from the
``metadata`` blob into first-class, indexed columns on ``action_records``:

  - ``tenant_id``  — the customer-of-the-customer identifier (e.g. Cleveland
                     Clinic). Distinct from ``data_subject_id``, which is the
                     patient / affected person under HIPAA Right of Access.
                     The two coexist; do NOT conflate.
  - ``domain``     — vertical bucket: ``clinical_decision``, ``lending``,
                     ``hiring``, etc. Drives per-domain pack selection.
  - ``action_class`` — coarse semantic category of the action
                     (``chart_entry``, ``controlled_substance_order``, etc.)
                     used by Phase 2 gate evaluation.

All three columns are NULLable for forward-compat with existing rows. The
HASHABLE_FIELDS canonicaliser excludes ``None`` values, so existing record
hashes remain stable across this migration (verified by
``test_hash_regression.py``).

Indexes:
  - ``idx_ar_tenant_id``        — per-customer history scans
  - ``idx_ar_org_tenant_seq``   — per-(org, customer) chain reads
  - ``idx_ar_action_class``     — gate-pack scoping queries

Idempotent: re-running upgrade is a no-op once columns exist. Downgrade
removes both columns and indexes. SQLite goes through ``batch_alter_table``
to honour its ALTER TABLE limitations; Postgres takes the fast inline path.
"""
import sqlalchemy as sa
from alembic import op

revision = "l2f3g4h5i6j7"
down_revision = "k1f2g3h4i5j6"
branch_labels = None
depends_on = None


_TABLE = "action_records"
_NEW_COLUMNS = ("tenant_id", "domain", "action_class")
_NEW_INDEXES = (
    ("idx_ar_tenant_id", ["tenant_id"]),
    ("idx_ar_org_tenant_seq", ["org_id", "tenant_id", "sequence_number"]),
    ("idx_ar_action_class", ["action_class"]),
)


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector, table: str, index_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Add the three promoted columns + their indexes.

    NOTE for future ops: at v1 scale (mostly-empty action_records pre-deploy)
    the inline CREATE INDEX is fine. At prod scale (>1M rows) Postgres
    locks ``action_records`` for the duration of each non-CONCURRENTLY
    CREATE INDEX, which can stall the write path on the hot ingest table.
    Future similar migrations should use
    ``op.execute('CREATE INDEX CONCURRENTLY ...')`` inside an
    ``op.get_context().autocommit_block()``. We do not retrofit that
    here because the rows-at-deploy assumption holds for v1.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # Should never happen in practice (action_records ships in initial
        # schema), but guard so an out-of-order run doesn't explode.
        return

    new_column_defs = [
        ("tenant_id", sa.String(length=64)),
        ("domain", sa.String(length=32)),
        ("action_class", sa.String(length=64)),
    ]

    dialect = bind.dialect.name

    # ── Add columns ──────────────────────────────────────────
    if dialect == "sqlite":
        # SQLite ALTER TABLE supports ADD COLUMN inline, so we still use the
        # plain add_column path; batch_alter is only needed for true ALTER /
        # FK-changing operations. ``add_column`` is sufficient and avoids the
        # rebuild-and-copy cost.
        for col_name, col_type in new_column_defs:
            if not _has_column(inspector, _TABLE, col_name):
                op.add_column(_TABLE, sa.Column(col_name, col_type, nullable=True))
                inspector = sa.inspect(bind)
    else:
        for col_name, col_type in new_column_defs:
            if not _has_column(inspector, _TABLE, col_name):
                op.add_column(_TABLE, sa.Column(col_name, col_type, nullable=True))
                inspector = sa.inspect(bind)

    # ── Backfill from metadata_ JSON blob ────────────────────
    # Dev / staging deployments may have stored these fields inside
    # ``metadata_`` pre-Phase-1. Copy them onto the new columns ONLY
    # where the new column is still NULL — COALESCE preserves any
    # explicit value already written. The ``metadata_`` blob itself is
    # untouched, so existing ``record_hash`` values remain valid (the
    # hash is computed over the blob's exact bytes).
    if dialect == "postgresql":
        # NOTE: ``metadata`` is ``JSON`` (not ``JSONB``), so the ``?``
        # key-existence operator is not available — it's JSONB-only. Use
        # ``->> 'key' IS NOT NULL`` instead, which works on JSON. Returns
        # NULL for JSON null literals too, which is the behaviour we want
        # (don't backfill from explicit JSON nulls).
        op.execute(
            """
            UPDATE action_records
            SET tenant_id = COALESCE(tenant_id, metadata->>'tenant_id'),
                domain = COALESCE(domain, metadata->>'domain'),
                action_class = COALESCE(action_class, metadata->>'action_class')
            WHERE metadata->>'tenant_id' IS NOT NULL
               OR metadata->>'domain' IS NOT NULL
               OR metadata->>'action_class' IS NOT NULL
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            UPDATE action_records
            SET tenant_id = COALESCE(tenant_id, json_extract(metadata, '$.tenant_id')),
                domain = COALESCE(domain, json_extract(metadata, '$.domain')),
                action_class = COALESCE(action_class, json_extract(metadata, '$.action_class'))
            WHERE json_extract(metadata, '$.tenant_id') IS NOT NULL
               OR json_extract(metadata, '$.domain') IS NOT NULL
               OR json_extract(metadata, '$.action_class') IS NOT NULL
            """
        )

    # ── Add indexes ──────────────────────────────────────────
    inspector = sa.inspect(bind)
    for index_name, columns in _NEW_INDEXES:
        if not _has_index(inspector, _TABLE, index_name):
            op.create_index(index_name, _TABLE, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    # Drop indexes first (FK-style hygiene).
    for index_name, _ in _NEW_INDEXES:
        if _has_index(inspector, _TABLE, index_name):
            op.drop_index(index_name, table_name=_TABLE)

    # Drop columns. SQLite needs batch_alter_table for DROP COLUMN.
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if dialect == "sqlite":
        with op.batch_alter_table(_TABLE) as batch:
            for col_name in _NEW_COLUMNS:
                if _has_column(inspector, _TABLE, col_name):
                    batch.drop_column(col_name)
    else:
        for col_name in _NEW_COLUMNS:
            if _has_column(inspector, _TABLE, col_name):
                op.drop_column(_TABLE, col_name)
