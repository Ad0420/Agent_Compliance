"""add generated_templates (Phase 5 PR A — counsel-attestation flow)

Revision ID: w5b8c9d0e1f2
Revises: w4a7b8c9d0e1
Create Date: 2026-05-27

Phase 5 Wave 1 ships the customer-facing templates + counsel-attestation
flow. The 5-question onboarding wizard (Phase 1 PR 14) persists answers
on ``Organization.wizard_answers``; this migration adds the table that
holds the generated Markdown bodies + attestation triple.

Per-key uniqueness
------------------
``(org_id, template_key)`` is unique. ``template_key`` is one of the
five values exported from ``app.services.templates.TEMPLATE_KEYS``;
the route layer rejects anything else with 422. The unique index
matches the only mutation pattern: ``UPSERT WHERE org_id = ? AND
template_key = ?``.

Atomic attestation
------------------
``attested_at``, ``attested_by_user_id``, ``attested_by_name``, and
``content_hash_at_attestation`` are written together by the
``POST /v1/templates/{key}/attest`` handler and cleared together by
``PUT /v1/templates/{key}``. The DB does not enforce the all-NULL-or-
all-set invariant via CHECK (we want flexibility to migrate the hash
format without a constraint dance); the application layer is the
single writer.

Idempotency
-----------
Every step is inspector-guarded so a partial-failure re-run is a no-op.
Mirrors ``w4a7b8c9d0e1`` (generated_audit_pdfs).

Portability
-----------
* ``sa.Text`` for ``markdown_body`` — Postgres + SQLite both treat
  Text as unbounded.
* Defaults via ``sa.func.now()`` — portable across Postgres + SQLite.
* No boolean defaults here, so no ``sa.true()`` / ``sa.false()``
  needed.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "w5b8c9d0e1f2"
down_revision = "w4a7b8c9d0e1"
branch_labels = None
depends_on = None


_TABLE = "generated_templates"
_UNIQUE_INDEX_ORG_KEY = "uq_generated_templates_org_key"
_INDEX_ORG = "idx_generated_templates_org"


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_unique_constraint(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    try:
        constraints = inspector.get_unique_constraints(table)
    except NotImplementedError:
        # Older SQLAlchemy SQLite dialect doesn't implement this; fall
        # back to scanning indexes (which captures the UNIQUE INDEX form
        # SQLite uses to back UniqueConstraint).
        return _has_index(inspector, table, name)
    return name in {c.get("name") for c in constraints}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column(
                "id", sa.String(length=36), primary_key=True, nullable=False
            ),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # One of the five template keys (hipaa_risk_analysis,
            # section_1557_ndp, ai_tool_inventory,
            # workforce_training_outline, ai_care_disclosure). Stored as
            # VARCHAR not ENUM so adding a sixth key is a one-line
            # service change, not a migration.
            sa.Column(
                "template_key", sa.String(length=64), nullable=False
            ),
            # The current editable Markdown body. Re-generation
            # overwrites this unless ``attested_at`` is set.
            sa.Column("markdown_body", sa.Text(), nullable=False),
            sa.Column(
                "generated_at",
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
            # ── Attestation triple — all four set/cleared together ──
            sa.Column("attested_at", sa.DateTime(), nullable=True),
            sa.Column(
                "attested_by_user_id",
                sa.String(length=128),
                nullable=True,
            ),
            sa.Column(
                "attested_by_name",
                sa.String(length=255),
                nullable=True,
            ),
            # SHA-256 hex (64 chars) of ``markdown_body`` at the moment
            # of attestation.
            sa.Column(
                "content_hash_at_attestation",
                sa.String(length=64),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "org_id", "template_key", name=_UNIQUE_INDEX_ORG_KEY
            ),
        )
        inspector = sa.inspect(bind)

    # List-by-org query ("show me all my templates"). Postgres can
    # cover the lookup with the unique index above, but the explicit
    # single-column index is cheap and keeps the EXPLAIN plan
    # legible.
    if not _has_index(inspector, _TABLE, _INDEX_ORG):
        op.create_index(
            _INDEX_ORG,
            _TABLE,
            ["org_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _INDEX_ORG):
        op.drop_index(_INDEX_ORG, table_name=_TABLE)
    # The unique constraint is dropped automatically with the table —
    # we don't need a separate drop_constraint call on SQLite (which
    # rewrites the table) and Postgres drops the backing index too.
    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)
