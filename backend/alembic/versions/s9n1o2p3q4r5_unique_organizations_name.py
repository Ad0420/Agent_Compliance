"""add UNIQUE constraint on organizations.name (W1.6 — two-scribemd-orgs)

Revision ID: s9n1o2p3q4r5
Revises: r8m0n1o2p3q4
Create Date: 2026-05-26

Phase 2 acceptance finding ``two-scribemd-orgs`` (Medium): the
bootstrap script previously called ``POST /v1/register`` (now 410
Gone), and the workaround at ``simulator/scripts/bootstrap_orgs_local.py``
relied on an org-name lookup to be idempotent. Without a database-level
``UNIQUE`` constraint on ``organizations.name`` a race or a manual
double-insert (which happened on Railway: ``scribemd`` was provisioned
twice with ids ``ef14c9e5…`` and ``cc02b53d…``) created two rows with
the same name, breaking the bootstrap's "fetch by name" idempotency.

Design notes
------------

1. **Pre-check, fail loud.** Postgres rejects ``ALTER TABLE … ADD
   CONSTRAINT UNIQUE`` if duplicate values already exist. Rather than
   crashing the migration with an opaque ``UniqueViolation``, we run a
   ``SELECT name, COUNT(*) … GROUP BY name HAVING COUNT(*) > 1`` first
   and raise a ``RuntimeError`` listing every offending name. The
   operator then runs the cleanup SQL documented below and re-applies
   the migration. We deliberately do NOT auto-merge or auto-rename —
   merging org rows is a multi-step operation (re-pointing
   action_records, api_keys, customers, baa_agreements, memberships,
   chain_state) that is too risky to do inside an Alembic upgrade
   transaction.

2. **Cleanup SQL** (for the operator, after they decide which row to
   keep — typically the one with API keys / action records). Replace
   ``KEEP_ID`` and ``DELETE_ID`` with the two org UUIDs::

       BEGIN;
       -- Re-point everything to the surviving org.
       UPDATE action_records   SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE api_keys         SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE customers        SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE baa_agreements   SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE policies         SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE policy_violations SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE approvals        SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE org_memberships  SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       UPDATE checkpoints      SET org_id='KEEP_ID' WHERE org_id='DELETE_ID';
       -- Drop chain_state for the deleted org (the surviving org keeps its own).
       DELETE FROM chain_state    WHERE org_id='DELETE_ID';
       DELETE FROM organizations  WHERE id='DELETE_ID';
       COMMIT;

   If unsure which row to keep, pick the one referenced by the most
   ``action_records`` (immutable audit trail), then move everything
   else to it.

3. **Name idempotency.** The constraint is named
   ``uq_organizations_name`` so a future downgrade or future migration
   can refer to it explicitly. The ``upgrade`` is guarded by an
   inspector check — re-running after a partial failure is a no-op.

4. **No backfill, no data mutation.** We never auto-delete or rename
   rows. If duplicates exist the migration aborts with a list of the
   conflicting names; the operator owns the cleanup.

5. **SQLite + Postgres parity.** ``op.create_unique_constraint`` is
   wrapped in ``batch_alter_table`` on SQLite (which would otherwise
   require a full table rebuild for the constraint add). Postgres runs
   the plain ``ALTER TABLE`` path.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "s9n1o2p3q4r5"
down_revision = "r8m0n1o2p3q4"
branch_labels = None
depends_on = None


_TABLE = "organizations"
_CONSTRAINT = "uq_organizations_name"


def _has_unique_constraint(inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {c["name"] for c in inspector.get_unique_constraints(table)}


def _find_duplicate_names(bind) -> list[tuple[str, int]]:
    """Return [(name, count), ...] for any org names appearing > 1 time."""
    rows = bind.execute(
        sa.text(
            "SELECT name, COUNT(*) AS c "
            f"FROM {_TABLE} "
            "GROUP BY name "
            "HAVING COUNT(*) > 1 "
            "ORDER BY name"
        )
    ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        # Defensive: organizations always exists by this point in the
        # revision graph, but a partial seed could miss it.
        return

    if _has_unique_constraint(inspector, _TABLE, _CONSTRAINT):
        return  # idempotent: already applied

    duplicates = _find_duplicate_names(bind)
    if duplicates:
        # Fail loud with operator-actionable detail. The docstring of
        # this migration carries the cleanup SQL; we surface the list
        # of offending names plus the count so the operator knows where
        # to start.
        formatted = ", ".join(f"{name!r} (x{count})" for name, count in duplicates)
        raise RuntimeError(
            "Cannot add UNIQUE constraint on organizations.name: "
            f"{len(duplicates)} duplicate name(s) found in the database: "
            f"{formatted}. "
            "Clean up duplicates manually (see migration docstring for SQL) "
            "and re-run `alembic upgrade head`."
        )

    dialect = bind.dialect.name
    if dialect == "sqlite":
        # SQLite needs batch_alter_table to add a constraint (it does
        # a table rebuild under the hood).
        with op.batch_alter_table(_TABLE) as batch:
            batch.create_unique_constraint(_CONSTRAINT, ["name"])
    else:
        op.create_unique_constraint(_CONSTRAINT, _TABLE, ["name"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return
    if not _has_unique_constraint(inspector, _TABLE, _CONSTRAINT):
        return

    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_CONSTRAINT, type_="unique")
    else:
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
