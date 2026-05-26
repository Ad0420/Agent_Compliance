"""add resource_count to staff_audit_log (Wave 3B.3 — IAM enforcement sweep)

Revision ID: u2r5s6t7u8v9
Revises: t1q4r5s6t7u8
Create Date: 2026-05-25

Wave 3B.3 sharpens the staff audit-log shape so list reads record the
NUMBER of records returned rather than emitting one row per record.

Per-request audit is the right shape:
  * A single staff GET ``/v1/actions?limit=200`` previously caused 200
    audit rows to land in ``staff_audit_log`` even though the operator
    made one logical request. That's noise in the customer-visible
    "who-read-my-data" surface.
  * The customer's threat model is "did Vera staff look at my data?" —
    they care about distinct HTTP requests, not pagination granularity.
  * ``resource_id`` already encodes the single-record case (one row in,
    ``resource_id`` set) vs the list case (``resource_id`` NULL,
    ``resource_count`` = N). The two shapes round-trip cleanly.

Backwards compat: ``resource_count`` is nullable + defaults to NULL on
pre-existing rows. Existing call sites don't pass it; their rows just
have no count. New list-reading call sites populate it.

Idempotency: ALTER TABLE ADD COLUMN under a column-not-present guard so
re-runs are no-ops. Mirrors the pattern in
``s0p3q4r5s6t7_add_org_checkpoint_cadence.py``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "u2r5s6t7u8v9"
down_revision = "t1q4r5s6t7u8"
branch_labels = None
depends_on = None


_TABLE = "staff_audit_log"
_COLUMN = "resource_count"


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # Idempotency: the parent migration may not have run if the
        # downgrade path bounced us back here. Bail rather than ALTER a
        # nonexistent table.
        return

    if not _has_column(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
