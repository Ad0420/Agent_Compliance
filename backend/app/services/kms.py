"""Key Management Service abstraction.

Signing keys MUST NOT live in app config. This module provides a pluggable
interface for key storage with two implementations:

- LocalKMS: HMAC key from environment variable (dev/testing)
- AWSKMS: Delegates signing to AWS KMS (production)

Usage:
    kms = get_kms()
    signature = kms.sign(b"data to sign")
    valid = kms.verify(b"data to sign", signature)
"""

import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger("actionledger.kms")


class KMSProvider(ABC):
    """Abstract base for key management providers."""

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


class LocalKMS(KMSProvider):
    """HMAC-SHA256 signing using a local key.

    Suitable for development and testing. For production, use AWSKMS.
    The key is read from the ACTIONLEDGER_SIGNING_KEY environment variable,
    falling back to the app secret_key (with a warning).
    """

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
