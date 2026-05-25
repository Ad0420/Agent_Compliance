"""KMS key history table (Phase 3 Wave 3A.a).

Records every signing key that has ever issued a checkpoint (or
approval) signature for this Vera deployment, so an offline verifier
can validate a signature from a *retired* key by looking up the
historical public key + algorithm rather than relying on whatever key
is currently active.

HMAC vs asymmetric
------------------

The history table is meaningful for **asymmetric KMS only** (e.g.
``kms-rsa-pss-2048`` where the public key is safe to publish and an
outside auditor can verify against it). The default ``LocalKMS`` is
HMAC-SHA256: the *symmetric* secret is required to verify. We still
register HMAC keys in the table so the audit trail can prove "this
``key_id`` existed and was active at time T", but ``public_key_pem``
is NULL and an offline verifier cannot independently validate the
signature without the shared secret.

Recommend asymmetric KMS for any org that wants real rotation safety
(an auditor with only the public key history can verify checkpoints
signed by any key in the chain, including retired ones).
"""

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class KmsKey(Base):
    """A KMS signing key that has been observed in this deployment.

    Rows are upserted on first ``sign()`` for a given ``key_id``
    (see :func:`app.services.kms._ensure_key_registered`). The
    ``created_at`` reflects the first observation, not the underlying
    KMS key's creation date — Vera doesn't get told about a key until
    it's used.

    Columns
    -------
    key_id
        Provider-supplied identifier for the key. For ``LocalKMS``
        this is a SHA-256 fingerprint of the HMAC secret (16 hex
        chars); for ``AWSKMS`` it's the KMS key id / ARN.
    algorithm
        Signing algorithm. ``hmac-sha256`` for ``LocalKMS``,
        ``kms-hmac-sha256`` for AWS KMS HMAC, and (future)
        ``kms-rsa-pss-2048`` etc. for asymmetric KMS.
    public_key_pem
        PEM-encoded public key. NULL for HMAC (no public key exists).
        Populated for asymmetric KMS so an offline verifier can
        validate signatures from this key without contacting Vera.
    created_at
        First observation of this key_id (auto-set on insert).
    retired_at
        When the key was retired (manual rotation). ``NULL`` while
        the key is still in service. Setting this is the trigger
        for ``is_active`` flipping to ``False``.
    is_active
        Operational flag. ``True`` on insert; flipped to ``False``
        when ``retired_at`` is set. Kept as a column (rather than a
        computed field) so the route can index on it for the common
        "active keys only" query.
    """

    __tablename__ = "kms_keys"

    key_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key_pem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    retired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.true()
    )
