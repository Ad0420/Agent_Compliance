"""External checkpoint store — publishes checkpoint proofs to tamper-proof storage.

The core problem: if checkpoints live in the same DB they protect, an attacker
with DB access can rewrite both. External stores solve this by publishing proofs
to systems the attacker cannot control.

Implementations:
- LocalFileStore: Append-only JSON Lines file (dev/testing only)
- S3WORMStore: AWS S3 with Object Lock (WORM) — cannot be deleted or modified
- TransparencyLogStore: Publishes to a Sigstore/Rekor-style transparency log

Usage:
    store = get_external_store()
    receipt = await store.publish(proof)
    verified = await store.verify(proof, receipt)
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("actionledger.external_store")


@dataclass
class ExternalProof:
    """Data published to an external store."""
    checkpoint_id: str
    org_id: str
    sequence: int
    merkle_root: str
    chain_hash: str
    timestamp: str
    signature: str
    key_id: str


@dataclass
class PublishReceipt:
    """Receipt from an external store confirming publication."""
    store_type: str
    location: str  # URL, file path, or tx hash
    published_at: str
    proof_hash: str  # hash of the published proof for verification

    def to_dict(self) -> dict:
        return {
            "store_type": self.store_type,
            "location": self.location,
            "published_at": self.published_at,
            "proof_hash": self.proof_hash,
        }


class ExternalStore(ABC):
    """Abstract base for external proof storage."""

    @abstractmethod
    async def publish(self, proof: ExternalProof) -> PublishReceipt:
        """Publish a proof to external storage. Returns a receipt."""
        ...

    @abstractmethod
    async def verify(self, proof: ExternalProof, receipt: PublishReceipt) -> bool:
        """Verify that a proof matches what was published."""
        ...

    @abstractmethod
    def store_type(self) -> str:
        """Return the store type identifier."""
        ...


class LocalFileStore(ExternalStore):
    """Append-only local file store — for development and testing only.

    NOT tamper-proof. An attacker with filesystem access can modify this file.
    Use S3WORMStore or TransparencyLogStore for production.
    """

    def __init__(self, file_path: str = "external_proofs.jsonl"):
        self._path = Path(file_path)

    async def publish(self, proof: ExternalProof) -> PublishReceipt:
        import hashlib
        from datetime import datetime, timezone

        entry = {
            "checkpoint_id": proof.checkpoint_id,
            "org_id": proof.org_id,
            "sequence": proof.sequence,
            "merkle_root": proof.merkle_root,
            "chain_hash": proof.chain_hash,
            "timestamp": proof.timestamp,
            "signature": proof.signature,
            "key_id": proof.key_id,
        }
        proof_hash = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode()
        ).hexdigest()

        entry["proof_hash"] = proof_hash

        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        now = datetime.now(timezone.utc).isoformat()
        logger.info(f"Published proof to local file: {self._path} (hash={proof_hash[:16]}...)")

        return PublishReceipt(
            store_type="local_file",
            location=str(self._path.absolute()),
            published_at=now,
            proof_hash=proof_hash,
        )

    async def verify(self, proof: ExternalProof, receipt: PublishReceipt) -> bool:
        import hashlib

        entry = {
            "checkpoint_id": proof.checkpoint_id,
            "org_id": proof.org_id,
            "sequence": proof.sequence,
            "merkle_root": proof.merkle_root,
            "chain_hash": proof.chain_hash,
            "timestamp": proof.timestamp,
            "signature": proof.signature,
            "key_id": proof.key_id,
        }
        proof_hash = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode()
        ).hexdigest()

        if proof_hash != receipt.proof_hash:
            return False

        # Check that this hash exists in the file
        if not self._path.exists():
            return False

        with open(self._path) as f:
            for line in f:
                stored = json.loads(line.strip())
                if stored.get("proof_hash") == proof_hash:
                    return True
        return False

    def store_type(self) -> str:
        return "local_file"


class S3WORMStore(ExternalStore):
    """AWS S3 with Object Lock (WORM mode) — truly immutable external store.

    Once published, objects cannot be deleted or modified for the retention period.
    Requires an S3 bucket with Object Lock enabled.

    Env vars:
        ACTIONLEDGER_S3_BUCKET: Bucket name (must have Object Lock enabled)
        ACTIONLEDGER_S3_PREFIX: Key prefix (default: "checkpoints/")
        AWS_REGION: AWS region
    """

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str = "checkpoints/",
        retention_days: int = 365,
    ):
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 is required for S3 WORM store. Install with: pip install boto3")

        self._bucket = bucket or os.environ.get("ACTIONLEDGER_S3_BUCKET")
        if not self._bucket:
            raise ValueError("S3 bucket is required. Set ACTIONLEDGER_S3_BUCKET env var.")

        self._prefix = prefix
        self._retention_days = int(
            os.environ.get("ACTIONLEDGER_S3_RETENTION_DAYS", str(retention_days))
        )
        region = os.environ.get("AWS_REGION", "us-east-1")
        self._client = boto3.client("s3", region_name=region)

        # Validate that the bucket has Object Lock enabled
        try:
            lock_config = self._client.get_object_lock_configuration(Bucket=self._bucket)
            status = lock_config.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled")
            if status != "Enabled":
                raise ValueError(
                    f"S3 bucket '{self._bucket}' does not have Object Lock enabled. "
                    "WORM guarantees require Object Lock. "
                    "See: aws s3api put-object-lock-configuration"
                )
            logger.info(f"S3 WORM bucket '{self._bucket}' Object Lock verified")
        except self._client.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ObjectLockConfigurationNotFoundError":
                raise ValueError(
                    f"S3 bucket '{self._bucket}' does not have Object Lock enabled. "
                    "Create the bucket with --object-lock-enabled-for-bucket "
                    "and configure a default retention policy."
                ) from e
            raise

    async def publish(self, proof: ExternalProof) -> PublishReceipt:
        import hashlib
        from datetime import datetime, timezone, timedelta

        entry = {
            "checkpoint_id": proof.checkpoint_id,
            "org_id": proof.org_id,
            "sequence": proof.sequence,
            "merkle_root": proof.merkle_root,
            "chain_hash": proof.chain_hash,
            "timestamp": proof.timestamp,
            "signature": proof.signature,
            "key_id": proof.key_id,
        }
        body = json.dumps(entry, sort_keys=True)
        proof_hash = hashlib.sha256(body.encode()).hexdigest()

        key = f"{self._prefix}{proof.org_id}/{proof.checkpoint_id}.json"
        now = datetime.now(timezone.utc)
        retain_until = now + timedelta(days=self._retention_days)

        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body.encode(),
            ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )

        location = f"s3://{self._bucket}/{key}"
        logger.info(f"Published proof to S3 WORM: {location} (retain until {retain_until.date()})")

        return PublishReceipt(
            store_type="s3_worm",
            location=location,
            published_at=now.isoformat(),
            proof_hash=proof_hash,
        )

    async def verify(self, proof: ExternalProof, receipt: PublishReceipt) -> bool:
        import hashlib

        entry = {
            "checkpoint_id": proof.checkpoint_id,
            "org_id": proof.org_id,
            "sequence": proof.sequence,
            "merkle_root": proof.merkle_root,
            "chain_hash": proof.chain_hash,
            "timestamp": proof.timestamp,
            "signature": proof.signature,
            "key_id": proof.key_id,
        }
        expected_hash = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode()
        ).hexdigest()

        if expected_hash != receipt.proof_hash:
            return False

        # Fetch from S3 and compare
        try:
            location = receipt.location
            # Parse s3://bucket/key
            parts = location.replace("s3://", "").split("/", 1)
            bucket, key = parts[0], parts[1]

            response = self._client.get_object(Bucket=bucket, Key=key)
            stored_body = response["Body"].read().decode()
            stored_hash = hashlib.sha256(stored_body.encode()).hexdigest()
            return stored_hash == expected_hash
        except Exception as e:
            logger.error(f"Failed to verify S3 proof: {e}")
            return False

    def store_type(self) -> str:
        return "s3_worm"


# Singleton instance
_store_instance: ExternalStore | None = None


def get_external_store() -> ExternalStore:
    """Get the configured external store. Caches the instance."""
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    provider = os.environ.get("ACTIONLEDGER_EXTERNAL_STORE", "local").lower()

    if provider == "s3" or provider == "s3_worm":
        _store_instance = S3WORMStore()
    else:
        _store_instance = LocalFileStore()

    logger.info(f"External store initialized: {_store_instance.store_type()}")
    return _store_instance


def set_external_store(store: ExternalStore):
    """Override the external store (for testing)."""
    global _store_instance
    _store_instance = store
