"""add Approval HITL workflow timing columns (Phase 2 Wave 2B PR A5)

Revision ID: q7k8l9m0n1o2
Revises: p6j7k8l9m0n1
Create Date: 2026-05-24

Phase 2 Wave 2B PR A5 ships **schema only** — no logic in this PR writes
to the new columns. Downstream PRs own the writes:

  - ``client_review_started_at``     — set by PR C2 (dashboard reviewer
                                        opens-page event).
  - ``decided_at``                   — set by PR A4 (reviewer completion
                                        endpoint).
  - ``webhook_sent_at``              — set by PR A3 (webhook dispatcher).
  - ``callback_received_at``         — set by PR A4
                                        (``POST /v1/reviews/{id}/complete``).
  - ``reviewed_below_threshold``     — set by PR A4 when the reviewer's
                                        role is lower than the gate's
                                        ``required_role``.

Design notes
------------

1. **``sa.DateTime()`` not TZ-aware.** Every other timestamp column in
   this project (``requested_at``, ``expires_at``, ``resolved_at``,
   ``action_records.action_timestamp``) uses naive ``sa.DateTime()`` and
   the service layer writes UTC-naive datetimes
   (``datetime.now(timezone.utc).replace(tzinfo=None)``; see
   ``app/services/approvals.py::_now``). Switching to TZ-aware here
   would break Postgres↔SQLite parity and the hash-canonicalization
   assumptions in ``app/services/hashing.py::_normalize``. The PR spec
   suggested ``TIMESTAMP WITH TIME ZONE``; we follow project convention
   instead. A project-wide TZ migration is out of scope for this PR.

2. **``reviewed_below_threshold`` server default.** ``server_default=
   sa.false()`` backfills existing rows to ``FALSE`` as part of the DDL
   itself, so no separate ``UPDATE`` is needed. We use the SQLAlchemy
   ``false()`` element (which renders as ``FALSE`` on PostgreSQL and
   ``0`` on SQLite) rather than ``sa.text("0")``: PostgreSQL's strict
   type checker rejects ``DEFAULT 0`` on a ``BOOLEAN`` column with
   ``DatatypeMismatch: column "..." is of type boolean but default
   expression is of type integer``.

3. **One new index: ``ix_approvals_decided_at``.** Supports the Phase 4
   audit-PDF query "decisions in the last N days" (SLA proof) and the
   dashboard recent-activity feed (C2/C6). Other new columns are not
   indexed; their query patterns either already overlap with the
   existing ``idx_approvals_org_status`` index or are diagnostic-only
   and deferred until the access pattern materializes.

4. **No hash-chain impact.** ``HASHABLE_FIELDS`` in
   ``app/services/hashing.py`` covers ``ActionRecord`` only; the
   ``approvals`` table is a queryable index over chain records, not a
   chain participant. Adding columns here cannot rehash any existing
   chain record.

5. **No backfill.** All four timestamp columns are nullable and remain
   NULL for historical rows. ``reviewed_below_threshold`` is set to
   ``FALSE`` by the column's ``server_default`` at creation time.

Idempotency: every ``add_column`` / ``create_index`` call is guarded by
an existence check against the live inspector so re-running after a
partial failure is a no-op. Mirrors the ``o5i6j7k8l9m0`` and
``p6j7k8l9m0n1`` patterns.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "q7k8l9m0n1o2"
down_revision = "p6j7k8l9m0n1"
branch_labels = None
depends_on = None


_TABLE = "approvals"

_NEW_TIMESTAMP_COLUMNS: tuple[str, ...] = (
    "client_review_started_at",
    "decided_at",
    "webhook_sent_at",
    "callback_received_at",
)

_NEW_FLAG_COLUMN = "reviewed_below_threshold"

_ALL_NEW_COLUMNS: tuple[str, ...] = (*_NEW_TIMESTAMP_COLUMNS, _NEW_FLAG_COLUMN)

_DECIDED_AT_INDEX = "ix_approvals_decided_at"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # Guards against an out-of-order run. The approvals table should
        # already exist via e5f6a7b8c9d0_add_approval_tables.
        return

    for col_name in _NEW_TIMESTAMP_COLUMNS:
        if not _has_column(inspector, _TABLE, col_name):
            op.add_column(_TABLE, sa.Column(col_name, sa.DateTime(), nullable=True))
            inspector = sa.inspect(bind)

    if not _has_column(inspector, _TABLE, _NEW_FLAG_COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _NEW_FLAG_COLUMN,
                sa.Boolean(),
                nullable=False,
                # sa.false() renders as FALSE on PostgreSQL and 0 on
                # SQLite. Using sa.text("0") fails on PostgreSQL with
                # DatatypeMismatch (BOOLEAN ≠ integer default).
                server_default=sa.false(),
            ),
        )
        inspector = sa.inspect(bind)

    existing_indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _DECIDED_AT_INDEX not in existing_indexes:
        op.create_index(
            _DECIDED_AT_INDEX,
            _TABLE,
            ["decided_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _TABLE not in inspector.get_table_names():
        return

    existing_indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _DECIDED_AT_INDEX in existing_indexes:
        op.drop_index(_DECIDED_AT_INDEX, table_name=_TABLE)

    if dialect == "sqlite":
        # SQLite DROP COLUMN routes through batch_alter_table for the
        # rebuild-and-copy dance; matches o5i6j7k8l9m0 / p6j7k8l9m0n1.
        with op.batch_alter_table(_TABLE) as batch:
            for col_name in _ALL_NEW_COLUMNS:
                if _has_column(inspector, _TABLE, col_name):
                    batch.drop_column(col_name)
    else:
        for col_name in _ALL_NEW_COLUMNS:
            if _has_column(inspector, _TABLE, col_name):
                op.drop_column(_TABLE, col_name)
