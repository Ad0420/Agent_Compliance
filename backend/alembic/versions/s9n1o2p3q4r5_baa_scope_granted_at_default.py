"""baa_scope.granted_at default now()

Revision ID: s9n1o2p3q4r5
Revises: r8m0n1o2p3q4
Create Date: 2026-05-26 00:00:00.000000

Fix for the recurring production error:

    ERROR: null value in column "granted_at" of relation "baa_scopes"
    violates not-null constraint

The model column was declared ``nullable=False`` with no default. The
sibling ``created_at`` column on the same model uses
``server_default=func.now()``; this migration brings ``granted_at`` in
line with that pattern at the DB level, so any insert that does not
supply ``granted_at`` (or supplies ``NULL``) falls back to ``now()``
instead of failing the constraint.

Callers that explicitly pass ``granted_at`` (e.g. the BAA upload route
using the operator-supplied ``signed_at``) still take precedence — the
default only fires when the column is omitted from the INSERT or the
value is ``NULL``.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "s9n1o2p3q4r5"
# Re-parented from "r8m0n1o2p3q4" to "v3s6t7u8v9w0" (Phase 3 tip) during
# the develop→main release sync. Main shipped this migration as a hotfix
# (sibling of r8m0) while develop's Phase 3 chain was in flight; both
# branches need to land on a single linear head. The hotfix's content
# (BAAScope.granted_at default backfill) is data-migration-style — order
# of application across orgs doesn't affect correctness, so splicing it
# after the Phase 3 schema additions (s0p3 → t1q4 → u2r5 → v3s6) is safe.
down_revision: Union[str, None] = "v3s6t7u8v9w0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE baa_scopes ALTER COLUMN granted_at SET DEFAULT now()"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE baa_scopes ALTER COLUMN granted_at DROP DEFAULT"
    )
