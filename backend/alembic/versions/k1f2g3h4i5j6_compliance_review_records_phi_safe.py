"""compliance_review_records: PHI-safe FK (membership_id SET NULL on delete)

Revision ID: k1f2g3h4i5j6
Revises: j0e1f2g3h4i5
Create Date: 2026-05-12

Post-merge audit fix for PR #172 (compliance RBAC + audit-of-audit). The
prior migration declared ``compliance_review_records.membership_id`` with
``ondelete=RESTRICT``. That mirrored the ``action_records.org_id`` bug
fixed in PR #164: when Clerk fires ``organization.deleted``, the webhook
hard-deletes all ``org_memberships`` rows for the org → if any compliance
review rows reference those memberships, the bulk DELETE raises a FK
violation → the webhook 500s → Clerk retries forever and the org never
gets soft-deleted.

The fix: make ``membership_id`` nullable + SET NULL on delete. The audit
row survives org deletion; reviewer identity is preserved via
``clerk_user_id`` (which is never NULLed). Compliance teams retain a
permanent audit-of-audit even after the operator removes a reviewer's
Clerk org membership.

Idempotent: skips the ALTER if the FK already points where we want.
"""
import sqlalchemy as sa
from alembic import op

revision = "k1f2g3h4i5j6"
down_revision = "j0e1f2g3h4i5"
branch_labels = None
depends_on = None


_TABLE = "compliance_review_records"
_FK = "compliance_review_records_membership_id_fkey"


def _fk_ondelete(inspector, table: str, fk_name: str) -> str | None:
    """Return the ``ondelete`` clause of a named FK, or ``None`` if it
    doesn't exist. Inspectors expose this under ``options`` for the
    Postgres dialect; SQLite's reflection is shape-y so we fall back to
    ``None`` rather than failing loudly.
    """
    for fk in inspector.get_foreign_keys(table):
        if fk.get("name") == fk_name:
            options = fk.get("options") or {}
            return options.get("ondelete")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    if dialect == "sqlite":
        # SQLite ALTER TABLE doesn't support changing FK actions or column
        # nullability in-place. We use batch_alter_table to do a
        # rebuild-and-copy. Inline FKs from the prior CREATE TABLE don't
        # have a stable name in SQLite, so we use ``naming_convention``
        # to assign one during the batch op, then drop+recreate. Safe at
        # the SQLite-in-tests scale; production is Postgres which takes
        # the fast path below.
        naming = {
            "fk": "%(table_name)s_%(column_0_name)s_fkey",
        }
        with op.batch_alter_table(
            _TABLE, naming_convention=naming
        ) as batch:
            batch.alter_column(
                "membership_id",
                existing_type=sa.String(),
                nullable=True,
            )
            batch.drop_constraint(_FK, type_="foreignkey")
            batch.create_foreign_key(
                _FK,
                "org_memberships",
                ["membership_id"],
                ["id"],
                ondelete="SET NULL",
            )
        return

    # Postgres path.
    current = _fk_ondelete(inspector, _TABLE, _FK)
    if current and current.upper() == "SET NULL":
        # Already in the right shape (idempotent re-run).
        return
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.alter_column(
        _TABLE,
        "membership_id",
        existing_type=sa.String(),
        nullable=True,
    )
    op.create_foreign_key(
        _FK,
        _TABLE,
        "org_memberships",
        ["membership_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return

    if dialect == "sqlite":
        naming = {
            "fk": "%(table_name)s_%(column_0_name)s_fkey",
        }
        with op.batch_alter_table(
            _TABLE, naming_convention=naming
        ) as batch:
            batch.drop_constraint(_FK, type_="foreignkey")
            batch.alter_column(
                "membership_id",
                existing_type=sa.String(),
                nullable=False,
            )
            batch.create_foreign_key(
                _FK,
                "org_memberships",
                ["membership_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        return

    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.alter_column(
        _TABLE,
        "membership_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.create_foreign_key(
        _FK,
        _TABLE,
        "org_memberships",
        ["membership_id"],
        ["id"],
        ondelete="RESTRICT",
    )
