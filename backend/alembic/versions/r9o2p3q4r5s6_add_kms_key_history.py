"""add kms_keys history table (Phase 3 Wave 3A.a — eng review finding 1A)

Revision ID: r9o2p3q4r5s6
Revises: r8m0n1o2p3q4
Create Date: 2026-05-25

Records every signing key that has ever produced a checkpoint signature
for this deployment. Offline verifiers consult the history to validate
signatures from *retired* keys after a rotation — without it, the
moment you rotate KMS the chain becomes "regulator-ready" only for
checkpoints signed by the *current* key.

Schema
------

  * ``key_id``         primary key (String(128)). Provider-supplied:
                      a SHA-256 fingerprint for ``LocalKMS`` HMAC,
                      a KMS key id / ARN for AWS KMS.
  * ``algorithm``      ``'hmac-sha256'`` for ``LocalKMS``,
                      ``'kms-hmac-sha256'`` for AWS HMAC,
                      ``'kms-rsa-pss-2048'`` etc. for asymmetric.
  * ``public_key_pem`` PEM-encoded public key. **NULL for HMAC** (no
                      public key exists for a symmetric secret).
                      Populated for asymmetric KMS so an offline
                      verifier can validate signatures from a
                      retired key without contacting Vera.
  * ``created_at``     first observation of this ``key_id``.
  * ``retired_at``     manual retirement marker; NULL while active.
  * ``is_active``      flips to False when ``retired_at`` is set.

HMAC vs asymmetric trade-off
----------------------------

For ``LocalKMS`` / AWS KMS HMAC, the signing key is **symmetric**.
The history table proves *which* ``key_id`` existed at time T, but an
offline verifier still needs the shared secret to validate. Real
"verify a retired-key signature without Vera" requires asymmetric KMS
(e.g. RSA-PSS) where the public key is safe to publish. We document
this trade-off so customers don't expect HMAC orgs to get full
rotation safety. Recommend asymmetric KMS for any org that wants it.

Design notes
------------

1. **Bool server defaults use ``sa.true()`` / ``sa.false()``**, not
   ``sa.text("1")``. PostgreSQL's strict type checker rejects
   ``DEFAULT 0`` on a BOOLEAN column with
   ``DatatypeMismatch: column "..." is of type boolean but default
   expression is of type integer``. Lesson from Phase 2 PR A5
   (``q7k8l9m0n1o2``).

2. **No FK to organizations.** KMS keys are deployment-wide (Vera
   operates one signing infrastructure across all orgs). Per-org
   keys are out of scope for Wave 3A.a — would force a multi-tenant
   KMS design that doesn't exist in production yet. The audit
   "which org used which key at time T" question is answered by
   ``checkpoints.key_id`` (already exists), not by this table.

3. **Idempotency guards.** ``create_table`` / ``create_index`` are
   guarded by an inspector existence check so a re-run after a
   partial failure is a no-op. Matches the pattern from
   ``q7k8l9m0n1o2`` / ``r8m0n1o2p3q4``.

4. **Indexes.** One supporting index on ``(is_active, created_at)``
   for the common "active keys, newest first" query. The PK on
   ``key_id`` already supports the single-key lookup path.

5. **No backfill.** Empty table on first migration. The
   ``_ensure_key_registered()`` upsert in ``services.kms`` populates
   rows lazily on the next ``sign()`` call after deploy. Existing
   ``checkpoints.key_id`` rows remain consistent — they reference
   ``key_id`` values that will appear in this table on the next
   sign by that key.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "r9o2p3q4r5s6"
down_revision = "r8m0n1o2p3q4"
branch_labels = None
depends_on = None


_TABLE = "kms_keys"
_ACTIVE_INDEX = "ix_kms_keys_is_active_created_at"


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
            sa.Column("key_id", sa.String(length=128), primary_key=True, nullable=False),
            sa.Column("algorithm", sa.String(length=32), nullable=False),
            sa.Column("public_key_pem", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, _TABLE, _ACTIVE_INDEX):
        op.create_index(
            _ACTIVE_INDEX,
            _TABLE,
            ["is_active", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _ACTIVE_INDEX):
        op.drop_index(_ACTIVE_INDEX, table_name=_TABLE)
    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)
