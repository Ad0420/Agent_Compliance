"""add staff_audit_log (Wave 3A.c — IAM hardening)

Revision ID: t1q4r5s6t7u8
Revises: r9o2p3q4r5s6
Create Date: 2026-05-25

Wave 3A.c implements the Phase 3 line-145 commitment ("Vera staff cannot
read customer PHI payloads; can read aggregate metrics, chain integrity,
gate metadata. Enforced and audited.") by:

  * Routing every Vera-staff response through ``services.iam.redact_*``
    so PHI fields collapse to ``{}`` / ``"[REDACTED]"``.
  * Logging every staff read in this table so a customer admin (and
    Vera's own SOC dashboard) can see who read what.

Design notes
------------

1. **Append-only at the application layer.** No route mutates rows; the
   only writer is ``services.iam.audit_staff_read``. We don't install a
   DB-level UPDATE/DELETE trigger today because the table lives under
   Vera operational ownership, not the customer chain. Follow-up if a
   customer requires hash-chained staff-read evidence.

2. **Indexes.** Two composite indexes match the two query shapes:
     * staff-activity:    ``(staff_id, read_at)``
     * customer-visible:  ``(org_id, read_at)``
   Postgres reads them in DESC order on the read_at side without an
   explicit DESC clause (the planner reverses the scan), so we keep the
   index definitions portable for SQLite.

3. **Idempotency guards.** Every ``create_table`` / ``create_index`` is
   guarded by an inspector check so re-running after a partial failure
   is a no-op. Same pattern as ``r8m0n1o2p3q4``.

4. **Boolean defaults.** ``redacted`` uses ``sa.true()`` literal (not the
   integer ``1``) to avoid the ``DEFAULT 0 → BOOLEAN`` DatatypeMismatch
   that broke A5's first push.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "t1q4r5s6t7u8"
down_revision = "r9o2p3q4r5s6"
branch_labels = None
depends_on = None


_TABLE = "staff_audit_log"
_INDEX_STAFF_READ = "idx_staff_audit_staff_read"
_INDEX_ORG_READ = "idx_staff_audit_org_read"


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column(
                "id", sa.String(length=36), primary_key=True, nullable=False
            ),
            sa.Column("staff_id", sa.String(length=128), nullable=False),
            sa.Column("endpoint", sa.String(length=256), nullable=False),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("resource_type", sa.String(length=64), nullable=False),
            sa.Column("resource_id", sa.String(length=64), nullable=True),
            sa.Column(
                "redacted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "read_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, _TABLE, _INDEX_STAFF_READ):
        op.create_index(
            _INDEX_STAFF_READ,
            _TABLE,
            ["staff_id", "read_at"],
        )

    if not _has_index(inspector, _TABLE, _INDEX_ORG_READ):
        op.create_index(
            _INDEX_ORG_READ,
            _TABLE,
            ["org_id", "read_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _INDEX_ORG_READ):
        op.drop_index(_INDEX_ORG_READ, table_name=_TABLE)
    if _has_index(inspector, _TABLE, _INDEX_STAFF_READ):
        op.drop_index(_INDEX_STAFF_READ, table_name=_TABLE)
    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)
