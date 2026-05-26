"""Customer S3 mirror exporter — Phase 3 Wave 3B.1.

What this module does
---------------------

Whenever ``services.checkpoint.create_checkpoint`` seals a new checkpoint,
the sealing path schedules ``export_checkpoint_to_customer_mirror`` as a
background asyncio task (one task per (org, checkpoint) pair). The task:

  1. Looks up the org's ``s3_export_arn``. NULL → write a ``skipped`` row
     and return.
  2. Checks the ``checkpoint_exports`` table for a prior ``success`` row
     on this checkpoint_id. If found → skip (idempotency).
  3. Builds the export document — the GET /v1/checkpoints/{date} response
     shape PLUS an ``action_records`` array (canonical-JSON serialised,
     ordered by sequence_number).
  4. Puts the object into the customer's bucket with S3 Object Lock
     COMPLIANCE mode + retain-until 7 years out.
  5. On bucket-doesn't-have-object-lock OR any other boto3 failure,
     writes a ``failure`` row with a structured ``reason`` and (best
     effort) surfaces the error to the org's configured webhook channel.

Why this design
---------------

* **Async, not in-band.** Checkpoint sealing is on the request path for
  the sweeper tick. Blocking that path on S3 round-trips (which can be
  hundreds of ms cold + retry overhead under throttling) would starve
  other orgs in the same tick. Background task with a strong-ref set
  is the same pattern as ``services.webhook_sweeper`` and
  ``services.checkpoint_sweeper``.
* **DB row before S3 call.** We INSERT a ``failure`` row up-front and
  flip it to ``success`` after the put completes. That way a process
  crash mid-call leaves a forensic record rather than a silent gap.
  (Actually we do this slightly differently: we let the exporter run
  through and only write a row at the end with the final status. The
  pre-write would require an additional UPDATE that complicates the
  idempotency check. Documented trade-off: a crash exactly between
  S3 success and DB write yields a duplicate next time; S3 Object
  Lock prevents corruption.)
* **Strong references for fire-and-forget.** Same ``_inflight_tasks``
  pattern as the sweepers. Without a strong ref, Python's GC may
  cancel the task mid-flight — Wave 2B PR A3 caught this and we don't
  regress it.

What this module does NOT do
----------------------------

* It does NOT validate the ARN. That's the onboarding flow's job
  (Wave 3A.d ``validate_s3_arn_syntax`` + the dashboard "Save"
  workflow). If a malformed ARN somehow lands in the DB, the boto3
  call will fail and we record the failure.
* It does NOT depend on the global ``ACTIONLEDGER_S3_BUCKET`` env var
  (which the Vera-side external_store uses). The customer mirror is a
  per-org target.
* It does NOT cache the S3 client across orgs because different orgs
  may live in different regions / different AWS accounts (via
  AssumeRole). One client per call is fine — the volume is bounded by
  checkpoint cadence (at most ~24/day/org).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import (
    ActionRecord,
    Checkpoint,
    CheckpointExport,
    Organization,
)
from .hashing import canonicalize
from .external_store import validate_s3_arn_syntax, S3ArnValidationError

logger = logging.getLogger("vera.checkpoint_export")


# ── Constants ──────────────────────────────────────────────────────

# S3 Object Lock retention. 7 years matches HIPAA / SOX / lending
# document retention. Customers wanting a shorter floor can configure
# their bucket's default retention separately (the retain-until-date
# we send is the *minimum* — Object Lock honours the longer of the
# request's date and the bucket default).
DEFAULT_RETENTION_DAYS = 365 * 7

# Closed set of structured failure reasons. The dashboard / SDK error
# surface maps these to human-readable copy; new failure modes need a
# new code here, NOT a free-form string at the call site.
REASON_NO_ARN = "bucket_not_configured"  # org.s3_export_arn IS NULL
REASON_OBJECT_LOCK_MISSING = "object_lock_missing"
REASON_INVALID_ARN = "arn_invalid"
REASON_CREDENTIALS_UNAVAILABLE = "credentials_unavailable"
REASON_BOTO3_UNAVAILABLE = "boto3_unavailable"
REASON_ACCESS_DENIED = "access_denied"
REASON_BUCKET_NOT_FOUND = "bucket_not_found"
REASON_UNKNOWN = "unknown_error"


# ── Background-task tracking ──────────────────────────────────────

# Strong-reference set for fire-and-forget exporter tasks. Same
# pattern as ``services.webhooks._inflight_tasks`` and
# ``services.checkpoint_sweeper._inflight_tasks``. Without holding a
# strong ref, Python's GC may cancel the task mid-flight (asyncio
# docs warn about this; Wave 2B PR A3 caught it in /review). Do NOT
# regress.
_inflight_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> asyncio.Task:
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    return task


# ── In-process metrics surface ─────────────────────────────────────
#
# Lightweight counters / observations. Test code reads them directly;
# a Phase 4 observability PR can wrap these in prometheus_client.
# Exposing module-level state (not a singleton class) keeps the
# import surface tiny and the test reset trivial.

@dataclass
class _Metrics:
    success_total: int = 0
    failure_total: dict[str, int] = None  # reason -> count
    duration_seconds_observations: list[float] = None
    skipped_total: int = 0

    def __post_init__(self) -> None:
        if self.failure_total is None:
            self.failure_total = {}
        if self.duration_seconds_observations is None:
            self.duration_seconds_observations = []

    def reset(self) -> None:
        self.success_total = 0
        self.failure_total = {}
        self.duration_seconds_observations = []
        self.skipped_total = 0


metrics = _Metrics()


def _metric_success(duration_seconds: float) -> None:
    metrics.success_total += 1
    metrics.duration_seconds_observations.append(duration_seconds)


def _metric_failure(reason: str, duration_seconds: float) -> None:
    metrics.failure_total[reason] = metrics.failure_total.get(reason, 0) + 1
    metrics.duration_seconds_observations.append(duration_seconds)


def _metric_skipped() -> None:
    metrics.skipped_total += 1


# ── ARN parsing ────────────────────────────────────────────────────

def _parse_s3_arn(arn: str) -> tuple[str, str]:
    """Return ``(bucket, prefix)`` from a syntactically-valid S3 bucket ARN.

    Mirrors the validator's parse rules. The caller is expected to have
    already passed the ARN through ``validate_s3_arn_syntax``; this
    helper raises ``S3ArnValidationError`` if it's somehow still
    malformed so we never write to the wrong bucket.

    Empty prefix is allowed and means "write at the bucket root" — the
    exporter still namespaces by org_id underneath.
    """
    validate_s3_arn_syntax(arn)
    parts = arn.strip().split(":", 5)
    resource = parts[5]
    if "/" in resource:
        bucket, prefix = resource.split("/", 1)
        # Normalise to no leading/trailing slash on the prefix; we add
        # a single slash between prefix and the per-checkpoint key.
        prefix = prefix.strip("/")
    else:
        bucket, prefix = resource, ""
    return bucket, prefix


# ── Document shape ─────────────────────────────────────────────────

def _record_to_canonical_dict(record: ActionRecord) -> dict[str, Any]:
    """Serialize an ActionRecord row to a canonical-JSON dict.

    We use the same field set as the chain hash inputs
    (``HASHABLE_FIELDS`` in ``services.hashing``) PLUS the chain-
    integrity columns (``record_hash``, ``previous_hash``,
    ``sequence_number``, ``recorded_at``) so an offline verifier can
    re-derive the chain from the export alone.

    The canonical JSON string is round-tripped through ``json.loads`` so
    the caller can embed the dict in a larger document and still get
    deterministic output when re-serializing the whole document.
    """
    from .hashing import HASHABLE_FIELDS

    out: dict[str, Any] = {}
    for field in HASHABLE_FIELDS:
        val = getattr(record, field, None)
        if val is None:
            continue
        if isinstance(val, datetime):
            # Match the hash-side normalization (UTC, ms precision).
            if val.tzinfo is not None:
                val = val.astimezone(timezone.utc).replace(tzinfo=None)
            val = val.replace(microsecond=(val.microsecond // 1000) * 1000)
            out[field] = val.isoformat(timespec="milliseconds")
        else:
            out[field] = val

    # Chain-integrity fields that aren't in HASHABLE_FIELDS but the
    # offline verifier needs.
    out["id"] = record.id
    out["record_hash"] = record.record_hash
    out["previous_hash"] = record.previous_hash
    if record.recorded_at is not None:
        rec = record.recorded_at
        if rec.tzinfo is not None:
            rec = rec.astimezone(timezone.utc).replace(tzinfo=None)
        rec = rec.replace(microsecond=(rec.microsecond // 1000) * 1000)
        out["recorded_at"] = rec.isoformat(timespec="milliseconds")

    return out


async def _gather_window_records(
    session: AsyncSession, org_id: str, checkpoint: Checkpoint
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Return ``(records, prior_checkpoint_id)`` for ``checkpoint``'s window.

    The window is the set of ActionRecord rows whose ``sequence_number``
    falls in ``(prior_checkpoint.sequence_at_checkpoint,
    checkpoint.sequence_at_checkpoint]``. For the very first checkpoint
    in an org the lower bound is 0.
    """
    prior_q = (
        select(Checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint
            < checkpoint.sequence_at_checkpoint,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    prior = (await session.execute(prior_q)).scalars().first()
    lower = prior.sequence_at_checkpoint if prior is not None else 0
    prior_id = prior.id if prior is not None else None

    records_q = (
        select(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.sequence_number > lower,
            ActionRecord.sequence_number
            <= checkpoint.sequence_at_checkpoint,
        )
        .order_by(ActionRecord.sequence_number)
    )
    records = (await session.execute(records_q)).scalars().all()
    serialized = [_record_to_canonical_dict(r) for r in records]
    return serialized, prior_id


async def _gather_head_action_id(
    session: AsyncSession, org_id: str, checkpoint: Checkpoint
) -> Optional[str]:
    """The action_record id whose sequence_number matches the checkpoint's.

    Returns NULL if no record is found at the head sequence (defensive
    — shouldn't happen for a sealed checkpoint).
    """
    q = select(ActionRecord.id).where(
        ActionRecord.org_id == org_id,
        ActionRecord.sequence_number == checkpoint.sequence_at_checkpoint,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return row


def _build_checkpoint_payload(
    checkpoint: Checkpoint,
    *,
    head_action_id: Optional[str],
    record_count: int,
    prior_checkpoint_id: Optional[str],
) -> dict[str, Any]:
    """Build the canonical fields-only dict for the checkpoint envelope.

    Matches the GET /v1/checkpoints/{date} response shape exactly so a
    diff between the GET response and the export's envelope is
    byte-stable.
    """
    signed_at = checkpoint.created_at
    if isinstance(signed_at, datetime):
        if signed_at.tzinfo is not None:
            signed_at = signed_at.astimezone(timezone.utc).replace(
                tzinfo=None
            )
        signed_at_iso = signed_at.isoformat(timespec="milliseconds")
    else:
        signed_at_iso = str(signed_at)

    return {
        "checkpoint_id": checkpoint.id,
        "org_id": checkpoint.org_id,
        "merkle_root": checkpoint.merkle_root,
        "kms_key_id": checkpoint.key_id,
        "signature": checkpoint.signature,
        "signed_at": signed_at_iso,
        "head_action_id": head_action_id,
        "record_count": record_count,
        "prior_checkpoint_id": prior_checkpoint_id,
        "sequence_at_checkpoint": checkpoint.sequence_at_checkpoint,
        "hash_at_checkpoint": checkpoint.hash_at_checkpoint,
    }


def canonical_document_bytes(
    envelope: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[bytes, str]:
    """Return ``(body, sha256_hex)`` for the full export document.

    The document is::

        {
          "checkpoint_id": ...,
          "merkle_root": ...,
          ...
          "action_records": [...]
        }

    Sorted keys, no whitespace. Unlike the chain's ``canonicalize``
    helper (which strips None values to keep the hash stable across
    schema additions), THIS function preserves ``null`` values so the
    document shape is stable across calls — auditors expect the
    envelope to always have ``prior_checkpoint_id`` (whether ``null``
    or a UUID) so a missing field doesn't mean "missing data" vs
    "no prior".
    """
    doc = dict(envelope)
    doc["action_records"] = records

    def _default(obj):
        if isinstance(obj, datetime):
            if obj.tzinfo is not None:
                obj = obj.astimezone(timezone.utc).replace(tzinfo=None)
            obj = obj.replace(microsecond=(obj.microsecond // 1000) * 1000)
            return obj.isoformat(timespec="milliseconds")
        return str(obj)

    body_str = json.dumps(
        doc, sort_keys=True, separators=(",", ":"), default=_default
    )
    body = body_str.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return body, digest


# ── Boto3 indirection ─────────────────────────────────────────────

# Module-level factory so tests can monkeypatch it with a stub that
# returns a fake client. Production resolves boto3 lazily so the
# import is cheap on systems where boto3 isn't installed.
def _make_s3_client():
    """Return a boto3 S3 client. Raises ImportError if boto3 missing."""
    import boto3  # type: ignore[import-untyped]

    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("s3", region_name=region)


# ── Idempotency check ─────────────────────────────────────────────

async def _already_exported(
    session: AsyncSession, checkpoint_id: str
) -> bool:
    """Return True if a success row already exists for ``checkpoint_id``."""
    q = select(CheckpointExport.id).where(
        CheckpointExport.checkpoint_id == checkpoint_id,
        CheckpointExport.status == "success",
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return row is not None


async def _write_export_row(
    session: AsyncSession,
    *,
    checkpoint_id: str,
    org_id: str,
    status: str,
    s3_location: Optional[str] = None,
    document_hash: Optional[str] = None,
    record_count: Optional[int] = None,
    reason: Optional[str] = None,
    error_detail: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Insert a checkpoint_exports row. Commits on its own session.

    All writes go through this helper so the failure path matches the
    success path 1:1. Best-effort: a DB write failure here is logged
    and swallowed — the structured log line is the fallback record.
    """
    row = CheckpointExport(
        checkpoint_id=checkpoint_id,
        org_id=org_id,
        status=status,
        s3_location=s3_location,
        document_hash=document_hash,
        record_count=record_count,
        reason=reason,
        error_detail=error_detail,
        duration_ms=duration_ms,
    )
    session.add(row)
    await session.commit()


# ── Public entry point ────────────────────────────────────────────

async def export_checkpoint_to_customer_mirror(
    checkpoint_id: str,
) -> None:
    """Push a sealed checkpoint to the org's customer S3 mirror.

    Idempotent: re-running on a checkpoint that's already been
    successfully exported is a no-op (a ``skipped`` row is written so
    the audit trail captures the re-attempt). Safe to call multiple
    times concurrently on the same checkpoint_id — the underlying
    SELECT-then-INSERT race window is bounded by the fact that
    checkpoint sealing happens on a single sweeper task; in tests we
    serialise via the in-memory engine's StaticPool.

    Opens its own session via ``AsyncSessionLocal`` so the caller's
    request transaction can roll back without rolling back the export
    row.

    Failures are NEVER raised to the caller. The caller is the
    checkpoint sealing path; an exporter failure must not roll back
    the chain commit.
    """
    started = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            cp = await session.get(Checkpoint, checkpoint_id)
            if cp is None:
                logger.warning(
                    "export: checkpoint %s not found; nothing to export",
                    checkpoint_id,
                )
                return

            org = await session.get(Organization, cp.org_id)
            if org is None:
                logger.warning(
                    "export: org %s for checkpoint %s not found",
                    cp.org_id, checkpoint_id,
                )
                return

            # ── Skip when no mirror is configured ─────────────────
            if not org.s3_export_arn:
                await _write_export_row(
                    session,
                    checkpoint_id=cp.id,
                    org_id=cp.org_id,
                    status="skipped",
                    reason=REASON_NO_ARN,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                _metric_skipped()
                logger.info(
                    "export: org %s has no s3_export_arn; skipped",
                    cp.org_id,
                )
                return

            # ── Idempotency: already exported? ────────────────────
            if await _already_exported(session, cp.id):
                await _write_export_row(
                    session,
                    checkpoint_id=cp.id,
                    org_id=cp.org_id,
                    status="skipped",
                    reason="already_exported",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                _metric_skipped()
                logger.info(
                    "export: checkpoint %s already exported; skipped",
                    cp.id,
                )
                return

            # ── Build the document ─────────────────────────────────
            records, prior_id = await _gather_window_records(
                session, cp.org_id, cp
            )
            head_action_id = await _gather_head_action_id(
                session, cp.org_id, cp
            )
            envelope = _build_checkpoint_payload(
                cp,
                head_action_id=head_action_id,
                record_count=len(records),
                prior_checkpoint_id=prior_id,
            )
            body, digest = canonical_document_bytes(envelope, records)

            # ── ARN parsing (cheap; we did syntactic validation at
            # onboarding but a malformed ARN somehow persisting must
            # not crash the sweeper).
            try:
                bucket, prefix = _parse_s3_arn(org.s3_export_arn)
            except S3ArnValidationError as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                await _write_export_row(
                    session,
                    checkpoint_id=cp.id,
                    org_id=cp.org_id,
                    status="failure",
                    record_count=len(records),
                    document_hash=digest,
                    reason=REASON_INVALID_ARN,
                    error_detail=f"{exc.code}: {exc.message}",
                    duration_ms=duration_ms,
                )
                _metric_failure(REASON_INVALID_ARN, duration_ms / 1000)
                logger.warning(
                    "export: org %s arn malformed: %s",
                    cp.org_id, exc.code,
                )
                return

            # ── Compose the key. Always namespace by org_id so a
            # shared bucket (which we don't recommend, but customers
            # do it) doesn't collide across tenants.
            key_path = (
                f"{prefix}/{cp.org_id}/{cp.id}.json"
                if prefix
                else f"{cp.org_id}/{cp.id}.json"
            )
            s3_location = f"s3://{bucket}/{key_path}"
            retain_until = datetime.now(timezone.utc) + timedelta(
                days=DEFAULT_RETENTION_DAYS
            )

            # ── Boto3 call ────────────────────────────────────────
            try:
                client = _make_s3_client()
            except ImportError:
                duration_ms = int((time.perf_counter() - started) * 1000)
                await _write_export_row(
                    session,
                    checkpoint_id=cp.id,
                    org_id=cp.org_id,
                    status="failure",
                    record_count=len(records),
                    document_hash=digest,
                    reason=REASON_BOTO3_UNAVAILABLE,
                    error_detail="boto3 not installed",
                    duration_ms=duration_ms,
                )
                _metric_failure(
                    REASON_BOTO3_UNAVAILABLE, duration_ms / 1000
                )
                logger.error("export: boto3 unavailable; failure logged")
                return

            try:
                client.put_object(
                    Bucket=bucket,
                    Key=key_path,
                    Body=body,
                    ContentType="application/json",
                    ObjectLockMode="COMPLIANCE",
                    ObjectLockRetainUntilDate=retain_until,
                )
            except Exception as exc:  # noqa: BLE001 — wide on purpose
                reason, detail = _classify_boto_error(exc)
                duration_ms = int((time.perf_counter() - started) * 1000)
                await _write_export_row(
                    session,
                    checkpoint_id=cp.id,
                    org_id=cp.org_id,
                    status="failure",
                    record_count=len(records),
                    document_hash=digest,
                    reason=reason,
                    error_detail=detail,
                    duration_ms=duration_ms,
                )
                _metric_failure(reason, duration_ms / 1000)
                logger.warning(
                    "export: checkpoint %s for org %s failed: %s (%s)",
                    cp.id, cp.org_id, reason, detail,
                )
                # Best-effort webhook surface — fire-and-forget so a
                # webhook outage can't poison the exporter.
                try:
                    await _notify_export_failure(
                        org_id=cp.org_id,
                        checkpoint_id=cp.id,
                        reason=reason,
                        detail=detail,
                    )
                except Exception:
                    logger.exception(
                        "export: webhook notification failed for "
                        "checkpoint %s", cp.id,
                    )
                return

            # ── Success ───────────────────────────────────────────
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _write_export_row(
                session,
                checkpoint_id=cp.id,
                org_id=cp.org_id,
                status="success",
                s3_location=s3_location,
                document_hash=digest,
                record_count=len(records),
                duration_ms=duration_ms,
            )
            _metric_success(duration_ms / 1000)
            logger.info(
                "export: checkpoint %s for org %s landed at %s "
                "(records=%s, sha256=%s)",
                cp.id, cp.org_id, s3_location, len(records), digest[:16],
            )
    except Exception:
        # Top-level defense — the whole exporter is non-critical
        # (Vera-side external_store still keeps the canonical proof).
        # Log and swallow.
        logger.exception(
            "export: unhandled error for checkpoint %s; "
            "no checkpoint_exports row may have been written",
            checkpoint_id,
        )


def _classify_boto_error(exc: Exception) -> tuple[str, str]:
    """Map a boto3 exception to (structured_reason, brief_detail).

    We avoid importing botocore.exceptions at module load (it's only
    needed when boto3 is installed). Soft-introspect the error shape
    instead — ``ClientError`` carries a ``response.Error.Code`` we can
    case on. Anything we don't recognise falls through to
    ``REASON_UNKNOWN`` with the exception's str() representation.
    """
    code = ""
    try:
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            err = resp.get("Error", {}) or {}
            code = err.get("Code", "") or ""
    except Exception:
        code = ""

    detail = (str(exc) or type(exc).__name__)[:512]

    # Object Lock not configured on bucket — the customer hasn't
    # enabled WORM. Surface as a specific reason so the dashboard
    # can hint the operator to fix it.
    if code in (
        "InvalidRequest",
        "ObjectLockConfigurationNotFoundError",
        "NoSuchObjectLockConfiguration",
    ):
        return REASON_OBJECT_LOCK_MISSING, detail
    if code in ("AccessDenied", "Forbidden"):
        return REASON_ACCESS_DENIED, detail
    if code in ("NoSuchBucket",):
        return REASON_BUCKET_NOT_FOUND, detail
    if code in ("NoCredentialsError", "ExpiredToken"):
        return REASON_CREDENTIALS_UNAVAILABLE, detail

    # Heuristic: botocore's NoCredentialsError isn't a ClientError —
    # it has no response dict but its class name is recognisable.
    cls_name = type(exc).__name__
    if cls_name in ("NoCredentialsError", "PartialCredentialsError"):
        return REASON_CREDENTIALS_UNAVAILABLE, detail
    if "ObjectLock" in detail or "Object Lock" in detail:
        return REASON_OBJECT_LOCK_MISSING, detail

    return REASON_UNKNOWN, detail


async def _notify_export_failure(
    *,
    org_id: str,
    checkpoint_id: str,
    reason: str,
    detail: str,
) -> None:
    """Surface an export failure to the org's webhook channel.

    Best-effort: any failure here is logged and swallowed by the
    caller. We intentionally do NOT block the checkpoint exporter on
    webhook delivery — the row in ``checkpoint_exports`` is the
    source of truth.

    Currently a stub that just emits a structured log entry. A
    Phase 4 polish PR can wire this into ``services.webhooks`` to
    deliver a typed ``checkpoint.export_failed`` event. We keep the
    signature stable now so the polish PR is purely additive.
    """
    logger.warning(
        "checkpoint_export_failed event: org_id=%s checkpoint_id=%s "
        "reason=%s detail=%s",
        org_id, checkpoint_id, reason, detail,
    )


# ── Scheduling ────────────────────────────────────────────────────

def schedule_export(checkpoint_id: str) -> Optional[asyncio.Task]:
    """Fire-and-forget schedule the exporter for a single checkpoint.

    Returns the created task (with strong-ref already held) or None
    if no running event loop is available — that branch shouldn't
    fire in normal operation but exists so unit tests that import
    the module outside an event loop don't crash.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "schedule_export: no running event loop; "
            "checkpoint %s not exported", checkpoint_id,
        )
        return None
    task = loop.create_task(
        export_checkpoint_to_customer_mirror(checkpoint_id),
        name=f"vera-export-{checkpoint_id[:8]}",
    )
    return _track_task(task)
