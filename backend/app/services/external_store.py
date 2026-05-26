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

Onboarding helpers (Wave 3A.d):
    validate_s3_arn_syntax(arn) — pure-regex check, no AWS call
    probe_s3_trust(arn, role_arn) — optional STS/HeadBucket probe
"""

import json
import logging
import os
import re
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


# ── S3 ARN onboarding validation (Wave 3A.d) ───────────────────────
#
# The v1-test-plan.md Phase 3 row "Customer S3 ARN mistyped" required
# that an invalid bucket gets rejected at onboarding time, not at first
# checkpoint write. Without this, the operator configures the off-Vera
# mirror in Settings → Compliance, leaves the page, then days later
# the first checkpoint silently fails because the ARN was a typo and
# nothing surfaced the issue.
#
# The validator splits into two stages:
#   1. ``validate_s3_arn_syntax`` — pure regex; never touches AWS. Cheap
#      enough to gate the "Save" button on the dashboard in real time.
#   2. ``probe_s3_trust`` — optional STS AssumeRole + HeadBucket probe
#      that the "Test write" button can call before the first real
#      checkpoint. Stubbed for v1 (returns ok=True) when boto3 is not
#      configured; real impl is an ops task wired up alongside customer
#      bucket creation tooling. Frontend Wave 3D C3.3 consumes both.


class S3ArnValidationError(ValueError):
    """Customer-facing onboarding error for malformed S3 ARN.

    Carries a stable ``code`` (consumed by the dashboard error toast +
    inline form validation) and an optional ``hint`` that maps directly
    to a "what does the customer need to fix" sentence — never a stack
    trace, never an AWS error message.
    """

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


# S3 bucket name rules (AWS docs):
#   - 3-63 characters
#   - lowercase letters, digits, hyphens, periods
#   - must start and end with a letter or digit
#   - no consecutive periods, no period adjacent to a hyphen
# We deliberately stay conservative: reject anything we can't prove is
# safe rather than guess. Customers with edge-case bucket names (dots,
# legacy uppercase grandfathered buckets) can open a support ticket.
_S3_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
# Prefix (the path after ``bucket/``) — S3 keys allow most printable
# ASCII; we restrict to the safe subset to avoid customers pasting in a
# trailing newline or shell metacharacter that breaks the IAM policy.
_S3_PREFIX_RE = re.compile(r"^[a-zA-Z0-9!_.*'()/\-]{1,512}$")


def validate_s3_arn_syntax(arn: str) -> None:
    """Raise :class:`S3ArnValidationError` if ``arn`` is not a syntactically
    valid S3 bucket ARN (optionally followed by ``/<key-prefix>``).

    Pure regex / string check; never contacts AWS. Used by the
    ``POST /v1/organizations/me/off-vera-mirror/validate`` endpoint and
    available for SDK-side pre-validation.

    Accepted forms::

        arn:aws:s3:::bucket-name
        arn:aws:s3:::bucket-name/optional/key/prefix

    Rejected forms emit a stable :attr:`S3ArnValidationError.code`:

    - ``empty`` — empty or whitespace-only string
    - ``s3_arn_malformed`` — doesn't match the ``arn:aws:s3:::...`` shape
    - ``wrong_service`` — ARN names a non-S3 service (dynamodb, kms, …)
    - ``bucket_name_invalid`` — bucket portion fails AWS bucket-name rules
    - ``prefix_invalid`` — key prefix contains disallowed characters
    """
    if arn is None or not isinstance(arn, str) or not arn.strip():
        raise S3ArnValidationError(
            code="empty",
            message="S3 ARN is required.",
            hint=(
                "Paste the bucket ARN from the AWS console, e.g. "
                "arn:aws:s3:::my-vera-mirror"
            ),
        )

    raw = arn.strip()

    # The five canonical ARN segments are ``arn:partition:service:region:account-id:resource``.
    # For S3 bucket ARNs, region and account-id are EMPTY, so a split on
    # ``:`` with maxsplit=5 yields exactly 6 parts, the last of which is
    # the bucket (and optional /prefix).
    parts = raw.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn":
        raise S3ArnValidationError(
            code="s3_arn_malformed",
            message=f"Not a valid AWS ARN: {raw!r}",
            hint=(
                "Expected arn:aws:s3:::<bucket-name> "
                "(six colon-separated segments)."
            ),
        )

    partition, service, region, account = parts[1], parts[2], parts[3], parts[4]

    # AWS partitions we recognise. ``aws`` covers commercial; ``aws-us-gov``
    # and ``aws-cn`` exist but our v1 customer set doesn't include them,
    # so reject with a hint pointing to support rather than silently
    # accepting an ARN we won't write to.
    if partition != "aws":
        raise S3ArnValidationError(
            code="s3_arn_malformed",
            message=f"Unsupported AWS partition: {partition!r}",
            hint=(
                "Vera v1 supports the standard 'aws' partition only. "
                "Contact support for GovCloud / China-region buckets."
            ),
        )

    if service != "s3":
        raise S3ArnValidationError(
            code="wrong_service",
            message=f"ARN names service {service!r}, expected 's3'",
            hint=(
                "The off-Vera mirror must point at an S3 bucket. Other "
                "services (DynamoDB, KMS, …) are not valid mirror targets."
            ),
        )

    # S3 bucket ARNs have empty region + account fields. A non-empty
    # value usually means the customer pasted an EC2 / IAM ARN by
    # mistake — fail with a specific hint so they don't hunt for typos.
    if region != "" or account != "":
        raise S3ArnValidationError(
            code="s3_arn_malformed",
            message=(
                "S3 bucket ARNs must have empty region and account "
                f"segments; got region={region!r} account={account!r}"
            ),
            hint=(
                "Format is arn:aws:s3:::<bucket-name> — note the three "
                "consecutive colons before the bucket name."
            ),
        )

    # Resource portion is ``bucket`` or ``bucket/prefix``. Split on the
    # FIRST slash only so prefixes that contain slashes round-trip.
    resource = parts[5]
    if "/" in resource:
        bucket, prefix = resource.split("/", 1)
    else:
        bucket, prefix = resource, ""

    if not _S3_BUCKET_RE.fullmatch(bucket):
        raise S3ArnValidationError(
            code="bucket_name_invalid",
            message=f"S3 bucket name does not meet AWS rules: {bucket!r}",
            hint=(
                "Bucket names must be 3-63 characters, lowercase letters, "
                "digits, hyphens or periods, and start/end with a letter "
                "or digit."
            ),
        )

    # AWS forbids consecutive periods and period-hyphen adjacency. The
    # regex above doesn't catch these; a targeted check keeps the regex
    # readable instead of becoming an unreadable lookaround pile.
    if ".." in bucket or ".-" in bucket or "-." in bucket:
        raise S3ArnValidationError(
            code="bucket_name_invalid",
            message=(
                "S3 bucket names may not contain consecutive periods or "
                f"period-hyphen adjacency: {bucket!r}"
            ),
            hint=(
                "Use plain hyphens between words (e.g. my-vera-mirror) "
                "or remove the offending punctuation."
            ),
        )

    if prefix and not _S3_PREFIX_RE.fullmatch(prefix):
        raise S3ArnValidationError(
            code="prefix_invalid",
            message=f"S3 key prefix contains disallowed characters: {prefix!r}",
            hint=(
                "Stick to ASCII letters, digits, hyphens, underscores, "
                "periods and slashes in the key prefix."
            ),
        )


# IAM role ARN — same shape as S3 ARNs except service=iam and the
# account-id segment is REQUIRED (12 digits) and resource is
# ``role/<name>``. The off-Vera mirror flow takes an optional role ARN
# the customer wants Vera to AssumeRole into; if absent, Vera uses its
# own credentials (less locked-down — recommend the role flow in docs).
_IAM_ROLE_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@\-_/]{1,128}$")


def validate_iam_role_arn_syntax(role_arn: str) -> None:
    """Raise :class:`S3ArnValidationError` if ``role_arn`` is not a syntactically
    valid IAM role ARN. Kept here so the onboarding endpoint can do both
    checks in one place; importing from a second module would just add
    coupling for no benefit.
    """
    if role_arn is None or not isinstance(role_arn, str) or not role_arn.strip():
        raise S3ArnValidationError(
            code="role_arn_empty",
            message="IAM role ARN is required when provided.",
            hint="Format is arn:aws:iam::<12-digit-account>:role/<role-name>.",
        )
    if not _IAM_ROLE_RE.fullmatch(role_arn.strip()):
        raise S3ArnValidationError(
            code="role_arn_malformed",
            message=f"Not a valid IAM role ARN: {role_arn!r}",
            hint=(
                "Expected arn:aws:iam::<12-digit-account>:role/<role-name>; "
                "copy the role ARN from the IAM console."
            ),
        )


async def probe_s3_trust(arn: str, role_arn: str | None = None) -> dict:
    """Best-effort trust probe for the configured S3 mirror.

    Returns a dict shaped::

        {
            "ok": bool,
            "can_put": bool,
            "can_get": bool,
            "error_code"?: str,  # only when ok=False
        }

    For v1 this is intentionally a stub when boto3/AWS credentials
    aren't available — the dashboard "Test write" button needs to round-
    trip *something*, and we'd rather return ``ok=True`` with a clearly-
    flagged ``stub=True`` than 500 and block the operator. Real impl
    (boto3 + STS AssumeRole + HeadBucket + 1-byte PutObject) lives
    behind ``ACTIONLEDGER_S3_TRUST_PROBE_ENABLED=1`` for environments
    where ops has provisioned credentials.

    Syntax validation is the caller's job — call
    :func:`validate_s3_arn_syntax` first to keep this function focused
    on the actual AWS round-trip.
    """
    probe_enabled = os.environ.get(
        "ACTIONLEDGER_S3_TRUST_PROBE_ENABLED", ""
    ).lower() in {"1", "true", "yes"}

    if not probe_enabled:
        # Stub mode: assume the syntax check + the customer's own AWS
        # console testing is sufficient. The frontend renders this as
        # "Syntax OK — first real checkpoint will exercise write
        # access" so the operator knows we didn't truly probe.
        return {"ok": True, "can_put": True, "can_get": True, "stub": True}

    try:
        import boto3  # noqa: F401  (imported for side-effect of availability check)
    except ImportError:
        return {
            "ok": False,
            "can_put": False,
            "can_get": False,
            "error_code": "boto3_unavailable",
        }

    # Real impl placeholder: a focused ops PR will fill this in once
    # the deployment has STS credentials. Kept as a single return so
    # callers don't have to special-case "probe was on but not wired".
    return {
        "ok": False,
        "can_put": False,
        "can_get": False,
        "error_code": "trust_probe_not_implemented",
    }
