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
down_revision: Union[str, None] = "r8m0n1o2p3q4"
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
