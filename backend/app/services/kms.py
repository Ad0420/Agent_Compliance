"""Key Management Service abstraction.

Signing keys MUST NOT live in app config. This module provides a pluggable
interface for key storage with two implementations:

- LocalKMS: HMAC key from environment variable (dev/testing)
- AWSKMS: Delegates signing to AWS KMS (production)

Usage:
    kms = get_kms()
    signature = kms.sign(b"data to sign")
    valid = kms.verify(b"data to sign", signature)

Phase 3 Wave 3A.a — KMS key history
-----------------------------------

A separate ``kms_keys`` table records every key that has signed
anything in this deployment. The signing path is unchanged; callers
that want the history-table audit trail invoke
:func:`ensure_key_registered` (async) before / after the sync ``sign()``
call so the row is upserted exactly once per key. History-aware
verifiers (e.g. :func:`app.services.checkpoint.verify_checkpoint`) use
:func:`verify_with_history` to look up the key by ``key_id`` and
construct the right :class:`KMSProvider` for that algorithm.

**HMAC vs asymmetric.** The history table is meaningful for
asymmetric KMS only — for HMAC, the symmetric secret is required to
verify, so an offline verifier still depends on Vera-held material.
We document this trade-off here and in the migration; HMAC orgs are
recommended to upgrade to asymmetric KMS if they want true rotation
safety. See :mod:`app.models.kms_key` for the longer write-up.
"""

import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("actionledger.kms")


# Algorithm identifiers stored in the kms_keys.algorithm column.
ALGO_HMAC_SHA256 = "hmac-sha256"
ALGO_KMS_HMAC_SHA256 = "kms-hmac-sha256"


class KMSProvider(ABC):
    """Abstract base for key management providers."""

    # Subclasses set this to one of the ALGO_* constants above.
    # Used by :func:`ensure_key_registered` so the history row records
    # the actual algorithm rather than a hard-coded guess.
    algorithm: str = ""

    @abstractmethod
    def sign(self, message: bytes) -> str:
        """Sign a message. Returns hex-encoded signature."""
        ...

    @abstractmethod
    def verify(self, message: bytes, signature: str) -> bool:
        """Verify a signature against a message."""
        ...

    @abstractmethod
    def get_key_id(self) -> str:
        """Return an identifier for the signing key (for audit trails)."""
        ...

    def get_public_key_pem(self) -> Optional[str]:
        """Return the PEM-encoded public key, or None for HMAC providers.

        HMAC providers (LocalKMS, AWS KMS HMAC) return None because the
        signing material is symmetric — there is no public key. Asymmetric
        providers (e.g. RSA-PSS) override to return the PEM so an offline
        verifier can validate signatures from a retired key.
        """
        return None


class LocalKMS(KMSProvider):
    """HMAC-SHA256 signing using a local key.

    Suitable for development and testing. For production, use AWSKMS.
    The key is read from the ACTIONLEDGER_SIGNING_KEY environment variable,
    falling back to the app secret_key (with a warning).
    """

    algorithm = ALGO_HMAC_SHA256

    def __init__(self, key: str | None = None):
        if key:
            self._key = key.encode("utf-8")
        else:
            signing_key = os.environ.get("ACTIONLEDGER_SIGNING_KEY")
            if signing_key:
                self._key = signing_key.encode("utf-8")
            else:
                from ..config import settings
                if settings.environment != "development":
                    raise RuntimeError(
                        "ACTIONLEDGER_SIGNING_KEY must be set in non-development environments. "
                        "Using the app SECRET_KEY for cryptographic signing is not allowed in production."
                    )
                logger.warning(
                    "ACTIONLEDGER_SIGNING_KEY not set — falling back to app secret_key. "
                    "This is acceptable for development only. Set ACTIONLEDGER_SIGNING_KEY for production."
                )
                self._key = settings.secret_key.encode("utf-8")

    def sign(self, message: bytes) -> str:
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        expected = self.sign(message)
        return hmac.compare_digest(expected, signature)

    def get_key_id(self) -> str:
        # Return a fingerprint of the key (not the key itself)
        return hashlib.sha256(self._key).hexdigest()[:16]


class AWSKMS(KMSProvider):
    """AWS KMS signing — delegates to AWS for key storage and signing.

    Requires: pip install boto3
    Env vars: AWS_KMS_KEY_ID, AWS_REGION (or standard AWS credentials)
    """

    algorithm = ALGO_KMS_HMAC_SHA256

    def __init__(self, key_id: str | None = None, region: str | None = None):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for AWS KMS. Install with: pip install boto3"
            )

        self._key_id = key_id or os.environ.get("AWS_KMS_KEY_ID")
        if not self._key_id:
            raise ValueError("AWS KMS key ID is required. Set AWS_KMS_KEY_ID env var.")

        region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._client = boto3.client("kms", region_name=region)

    def sign(self, message: bytes) -> str:
        # KMS sign with HMAC_SHA_256
        response = self._client.generate_mac(
            KeyId=self._key_id,
            Message=message,
            MacAlgorithm="HMAC_SHA_256",
        )
        return response["Mac"].hex()

    def verify(self, message: bytes, signature: str) -> bool:
        try:
            self._client.verify_mac(
                KeyId=self._key_id,
                Message=message,
                MacAlgorithm="HMAC_SHA_256",
                Mac=bytes.fromhex(signature),
            )
            return True
        except Exception:
            return False

    def get_key_id(self) -> str:
        return self._key_id

    def get_public_key_pem(self) -> Optional[str]:
        """AWS KMS HMAC keys are symmetric, so no public PEM exists.

        For an asymmetric KMS key (RSA-PSS / ECDSA) the underlying AWS
        SDK exposes ``get_public_key`` which returns DER bytes that
        need PEM-wrapping. Wave 3A.a stubs this as None — adding real
        asymmetric KMS is ops work tracked separately (out-of-scope
        per the wave brief).
        """
        return None


# Singleton instance
_kms_instance: KMSProvider | None = None


def get_kms() -> KMSProvider:
    """Get the configured KMS provider. Caches the instance."""
    global _kms_instance
    if _kms_instance is not None:
        return _kms_instance

    provider = os.environ.get("ACTIONLEDGER_KMS_PROVIDER", "local").lower()

    if provider == "aws":
        _kms_instance = AWSKMS()
    else:
        _kms_instance = LocalKMS()

    logger.info(f"KMS provider initialized: {provider} (key_id={_kms_instance.get_key_id()})")
    return _kms_instance


def set_kms(kms: KMSProvider):
    """Override the KMS provider (for testing)."""
    global _kms_instance
    _kms_instance = kms


# ─────────────────────────────────────────────────────────────────────
# Phase 3 Wave 3A.a — KMS key history (eng review finding 1A)
# ─────────────────────────────────────────────────────────────────────


async def ensure_key_registered(
    session: AsyncSession, kms: Optional[KMSProvider] = None
) -> "KmsKey":
    """Upsert a ``kms_keys`` row for the given provider. Idempotent.

    Called before/after signing so the history table records every
    key that has ever produced a signature in this deployment.
    Returns the persisted :class:`app.models.kms_key.KmsKey` row.

    Idempotency: if a row with the same ``key_id`` already exists, the
    existing row is returned unchanged. Updates to ``algorithm`` /
    ``public_key_pem`` on subsequent calls are NOT applied — those
    fields are immutable once a key has been observed; rotating to a
    new key produces a *new* row with a new ``key_id``.
    """
    # Local import to avoid a circular at module-load time (models
    # eventually depend on Base which doesn't import services).
    from ..models.kms_key import KmsKey

    if kms is None:
        kms = get_kms()

    key_id = kms.get_key_id()
    existing = await session.get(KmsKey, key_id)
    if existing is not None:
        return existing

    row = KmsKey(
        key_id=key_id,
        algorithm=kms.algorithm or ALGO_HMAC_SHA256,
        public_key_pem=kms.get_public_key_pem(),
        is_active=True,
    )
    # Wrap the insert in a SAVEPOINT (``begin_nested()``) so a
    # concurrent-insert IntegrityError rolls back ONLY the savepoint —
    # the caller's outer transaction (e.g. the checkpoint write in
    # ``create_checkpoint``) stays intact. A bare ``session.rollback()``
    # here would discard the caller's in-session reads/writes, silently
    # corrupting concurrent checkpoint creation on the loser side.
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError:
        existing = await session.get(KmsKey, key_id)
        if existing is not None:
            return existing
        raise
    return row


async def get_key_history(
    session: AsyncSession, *, active_only: bool = False
) -> list["KmsKey"]:
    """Return KMS keys in created_at DESC order.

    Used by ``GET /v1/kms/keys`` and by Wave 3C ``vera verify --offline``
    to fetch the public-key history. Set ``active_only=True`` to filter
    to keys that have not been retired.
    """
    from ..models.kms_key import KmsKey

    stmt = select(KmsKey).order_by(KmsKey.created_at.desc())
    if active_only:
        stmt = stmt.where(KmsKey.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_key_by_id(
    session: AsyncSession, key_id: str
) -> Optional["KmsKey"]:
    """Single key lookup by ``key_id`` for the history-aware verifier."""
    from ..models.kms_key import KmsKey

    return await session.get(KmsKey, key_id)


async def verify_with_history(
    session: AsyncSession,
    *,
    key_id: str,
    message: bytes,
    signature: str,
) -> bool:
    """Verify a signature against the historical key identified by ``key_id``.

    Behaviour:
      - If ``key_id`` is **not** present in the history table, returns
        False. We do NOT fall through to "verify with the current KMS"
        because a missing history row means we cannot prove the key
        existed at signing time — silently allowing such a signature
        would defeat the purpose of the history table.
      - If the historical key matches the *current* KMS provider's
        ``key_id``, we use the current provider directly (preserves
        the HMAC-with-current-secret path).
      - If the historical key is an asymmetric KMS row with a stored
        ``public_key_pem``, we verify the signature against that PEM.
        The actual asymmetric-verify path is a stub in Wave 3A.a
        (returns False) — Wave 3C lands the real RSA-PSS / ECDSA
        verifier alongside ``vera verify --merkle-proof``.
      - For HMAC history rows whose key_id doesn't match the current
        KMS, we cannot verify (the symmetric secret is gone). Returns
        False and logs a clear warning so the operator knows the
        signature is from a retired HMAC key and *cannot* be
        independently verified offline.
    """
    history_row = await get_key_by_id(session, key_id)
    if history_row is None:
        logger.warning(
            "verify_with_history: key_id=%s NOT in history table — "
            "cannot verify (no silent allow). If this signature is "
            "legitimate, the kms_keys row was lost; re-register via "
            "ensure_key_registered() and retry.",
            key_id,
        )
        return False

    current = get_kms()
    if history_row.key_id == current.get_key_id():
        # Active key path — straightforward.
        return current.verify(message, signature)

    if history_row.public_key_pem is not None:
        # Asymmetric retired-key path. Real implementation lands in
        # Wave 3C with the offline verifier. Log clearly so we don't
        # silently pass.
        logger.info(
            "verify_with_history: asymmetric retired-key verify for "
            "key_id=%s — full RSA-PSS/ECDSA path lands in Wave 3C; "
            "Wave 3A.a returns False as a safe default.",
            key_id,
        )
        return False

    # HMAC retired-key path — symmetric secret no longer available.
    logger.warning(
        "verify_with_history: HMAC retired key (key_id=%s) cannot be "
        "verified independently. Recommend asymmetric KMS for "
        "rotation safety. Returning False.",
        key_id,
    )
    return False
