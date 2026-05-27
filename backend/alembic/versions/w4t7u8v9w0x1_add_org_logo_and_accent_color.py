"""add Organization.logo_bytes/logo_mime/accent_color_hex (Phase 4 W2 A3)

Revision ID: w4t7u8v9w0x1
Revises: t0o2p3q4r5s6
Create Date: 2026-05-26

Phase 4 Wave 2 PR A3 — white-label PDF cover. Customers upload a logo
(PNG or sanitised SVG) and pick an accent colour; the audit PDF cover
renderer then composes them onto the title page when the request
specifies ``branding=customer``. Three new columns on ``organizations``:

  * ``logo_bytes``       — BYTEA / BLOB. The uploaded image bytes. NULL
                            when the Customer hasn't uploaded a logo yet
                            (the renderer falls back to a neutral
                            wordmark of the Customer name).
  * ``logo_mime``        — VARCHAR(32). The MIME type of the bytes,
                            either ``image/png`` or ``image/svg+xml``.
                            Stored explicitly so the renderer can pick
                            the right ReportLab pathway (ImageReader vs
                            svglib) without re-sniffing the bytes.
  * ``accent_color_hex`` — VARCHAR(7). ``#RRGGBB`` colour the cover
                            renderer uses for the title underline.
                            NULL falls back to the project default
                            ``#1a1a1a``.

Storage decision
----------------
We pick the blob-column route over a separate S3 bucket because:

  * The existing S3 plumbing (``services/external_store.py``) is wired
    for *customer-owned* checkpoint mirrors (one bucket per Customer
    with Object Lock + AssumeRole). A Vera-internal asset bucket is a
    different shape with different IAM, and standing one up just for a
    handful of small images is over-engineering for v1.
  * Logos are small (≤1 MB, enforced at the upload endpoint); Postgres
    LOB handling at that size is well-trodden ground.
  * The PDF cover renderer needs the bytes synchronously at render
    time. A blob column means a single ``SELECT`` populates the
    PdfContext — no network round-trip in the hot render path.

Portability
-----------
``sa.LargeBinary()`` maps to ``BYTEA`` on Postgres and ``BLOB`` on
SQLite, with no per-dialect SQL needed. The column is nullable so the
backfill story is trivial (existing rows: ``NULL`` → renderer skips).
Per the project style guide we use ``sa.true()``/``sa.false()`` (not
``sa.text("0")``) anywhere a boolean default is required; here all
three columns are NULLable with no server default so the issue doesn't
arise. Idempotent column adds (each guarded by an inspector check) so a
partial re-run is safe.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "w4t7u8v9w0x1"
down_revision = "t0o2p3q4r5s6"
branch_labels = None
depends_on = None


_TABLE = "organizations"
_LOGO_BYTES = "logo_bytes"
_LOGO_MIME = "logo_mime"
_ACCENT_COLOR = "accent_color_hex"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ``logo_bytes`` — sa.LargeBinary maps to BYTEA on Postgres, BLOB on
    # SQLite. NULL until the Customer uploads. Capped to 1 MB by the
    # PUT /v1/organizations/me/branding endpoint (the DB has no inline
    # CHECK constraint for length because portable BYTEA-length checks
    # are dialect-fork-prone — the route-layer guard is the source of
    # truth).
    if not _has_column(inspector, _TABLE, _LOGO_BYTES):
        op.add_column(
            _TABLE,
            sa.Column(_LOGO_BYTES, sa.LargeBinary(), nullable=True),
        )

    # ``logo_mime`` — one of ``image/png`` or ``image/svg+xml``. The
    # column is nullable + un-constrained at the DB level because the
    # validating regex lives in the upload endpoint; making it a CHECK
    # constraint would couple a future MIME (e.g. WebP) addition to a
    # data migration.
    inspector = sa.inspect(bind)
    if not _has_column(inspector, _TABLE, _LOGO_MIME):
        op.add_column(
            _TABLE,
            sa.Column(_LOGO_MIME, sa.String(length=32), nullable=True),
        )

    # ``accent_color_hex`` — ``#RRGGBB`` literal. 7 chars is enough for
    # the leading ``#`` + 6 hex digits. Nullable: NULL means "use the
    # project default" so the renderer never has to special-case "no
    # accent colour configured" beyond a ``None`` check.
    inspector = sa.inspect(bind)
    if not _has_column(inspector, _TABLE, _ACCENT_COLOR):
        op.add_column(
            _TABLE,
            sa.Column(_ACCENT_COLOR, sa.String(length=7), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    for col in (_ACCENT_COLOR, _LOGO_MIME, _LOGO_BYTES):
        if _has_column(inspector, _TABLE, col):
            if dialect == "sqlite":
                # SQLite needs batch_alter_table to drop a column on
                # versions older than 3.35; the project's CI image
                # bundles a recent SQLite but the batch wrapper is
                # cheap insurance and matches the
                # ``v3s6t7u8v9w0_add_s3_export_arn_and_checkpoint_exports``
                # precedent.
                with op.batch_alter_table(_TABLE) as batch:
                    batch.drop_column(col)
            else:
                op.drop_column(_TABLE, col)
            inspector = sa.inspect(bind)
