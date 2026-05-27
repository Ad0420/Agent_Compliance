"""add generated_audit_pdfs (Phase 4 Wave 2 C4 — audit PDF history)

Revision ID: w4a7b8c9d0e1
Revises: w4t7u8v9w0x1
Create Date: 2026-05-26

Wave 2 C4 surfaces a "Generated audit PDFs" history table on the
Customer detail page. Every time the existing ``POST /v1/audits/{customer_id}``
route successfully renders a PDF, the route writes one row here so the
dashboard can list past renders and offer a Re-download action.

Storage decision (v1)
---------------------
We do NOT persist the rendered PDF bytes. Re-download regenerates from
scratch using the persisted ``(date_from, date_to, sections_json,
branding)`` tuple. Pros: zero storage cost, exact reproducibility
guaranteed (every download is sourced from current chain state).
Cons: re-download takes 5–30 s, same as initial.

The schema reserves ``pdf_storage_url`` (nullable VARCHAR(1024)) so a
future v1.x can flip to S3-mirroring without a second migration. NULL
for every v1 row.

Trigger to revisit: first pilot Customer complaint about re-download
latency.

Identity capture
----------------
``generated_by_user_id`` and ``generated_by_api_key_id`` are BOTH
nullable. Exactly one is populated per row at the application layer:

  * Clerk session → ``generated_by_user_id`` = Clerk ``sub`` claim.
  * API key path → ``generated_by_api_key_id`` = APIKey row id.

We don't add a CHECK constraint enforcing "exactly one" — the v1
write path is the only writer, and we want flexibility to add a
third path (e.g. a future system-renderer) without a migration.

Indexes
-------
Single composite index on ``(customer_id, generated_at)`` matches the
dashboard's only query shape:
``WHERE customer_id = ? ORDER BY generated_at DESC LIMIT N OFFSET M``.
Postgres scans this in DESC order without an explicit DESC clause.

Idempotency
-----------
Every step is inspector-guarded so a partial-failure re-run is a no-op.
Mirrors ``t1q4r5s6t7u8`` (staff_audit_log) and ``v3s6t7u8v9w0``
(checkpoint_exports).

Portability
-----------
* ``sa.JSON()`` — Postgres ``json``, SQLite ``TEXT`` (both round-trip
  Python lists via SQLAlchemy's type adapter).
* ``sa.BigInteger()`` — both backends support this; chosen because a
  PDF byte_size could plausibly exceed 2 GB (a 6-month evidence trail
  with every section).
* Defaults via ``sa.func.now()`` — portable across Postgres + SQLite.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "w4a7b8c9d0e1"
down_revision = "w4t7u8v9w0x1"
branch_labels = None
depends_on = None


_TABLE = "generated_audit_pdfs"
_INDEX_CUSTOMER_GENERATED = "idx_generated_audit_pdfs_customer_generated"
_INDEX_ORG_GENERATED = "idx_generated_audit_pdfs_org_generated"


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
            sa.Column(
                "generated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            # Clerk user id (sub claim) when the render was triggered by a
            # Clerk session. Nullable: an API-key render leaves this NULL
            # and populates ``generated_by_api_key_id`` instead.
            sa.Column(
                "generated_by_user_id",
                sa.String(length=128),
                nullable=True,
            ),
            # APIKey.id (UUID) when the render was triggered by a Bearer
            # api-key. Nullable: a Clerk render leaves this NULL.
            # No FK because api_keys rows are sometimes revoked + cleaned,
            # and we want the history row to outlive the key.
            sa.Column(
                "generated_by_api_key_id",
                sa.String(length=36),
                nullable=True,
            ),
            sa.Column("date_from", sa.Date(), nullable=False),
            sa.Column("date_to", sa.Date(), nullable=False),
            # JSON list of section keys included in the render. The keys
            # are the strings exported from
            # ``services.pdf.sections.SECTION_RENDERERS`` (e.g. "cover",
            # "audit_controls"). Stored as JSON for forward compatibility
            # with future section sets; reads round-trip to a Python list
            # via SQLAlchemy.
            sa.Column("sections_json", sa.JSON(), nullable=False),
            # "customer" or "vera-neutral". Stored as a VARCHAR rather
            # than an ENUM so adding a third branding option is a one-line
            # service change, not a migration.
            sa.Column("branding", sa.String(length=32), nullable=False),
            # Length of the rendered PDF in bytes. BigInteger so a
            # 6-month evidence trail with every section + an unusually
            # busy customer doesn't overflow Integer.
            sa.Column("byte_size", sa.BigInteger(), nullable=False),
            # NULL in v1 — we regenerate on re-download (see docstring).
            # Reserved so a future v1.x can switch to S3 mirroring
            # without a second migration. Sized at 1024 to fit S3 URLs.
            sa.Column(
                "pdf_storage_url",
                sa.String(length=1024),
                nullable=True,
            ),
        )
        inspector = sa.inspect(bind)

    # Dashboard query: "list this Customer's audit PDFs newest first."
    if not _has_index(inspector, _TABLE, _INDEX_CUSTOMER_GENERATED):
        op.create_index(
            _INDEX_CUSTOMER_GENERATED,
            _TABLE,
            ["customer_id", "generated_at"],
        )

    # Future ops query: "all audit PDFs generated for org X in the last
    # 30 days." Not used by the v1 dashboard but cheap to add now.
    if not _has_index(inspector, _TABLE, _INDEX_ORG_GENERATED):
        op.create_index(
            _INDEX_ORG_GENERATED,
            _TABLE,
            ["org_id", "generated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _INDEX_ORG_GENERATED):
        op.drop_index(_INDEX_ORG_GENERATED, table_name=_TABLE)
    if _has_index(inspector, _TABLE, _INDEX_CUSTOMER_GENERATED):
        op.drop_index(_INDEX_CUSTOMER_GENERATED, table_name=_TABLE)
    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)
