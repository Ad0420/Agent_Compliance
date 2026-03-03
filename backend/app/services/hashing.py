import hashlib
import json
from datetime import datetime, timezone


def _normalize(obj):
    """Normalize values for consistent hashing across DB round-trips."""
    if isinstance(obj, datetime):
        # Convert to UTC first, THEN strip timezone info and truncate to
        # milliseconds. This ensures 12:00 UTC and 12:00 EST hash differently
        # (as they should — they're different instants in time).
        # SQLite doesn't preserve timezone, and microsecond precision varies
        # across serialization boundaries.
        if obj.tzinfo is not None:
            dt = obj.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            dt = obj
        dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
        return dt.isoformat(timespec="milliseconds")
    return str(obj)


def canonicalize(record_fields: dict) -> str:
    """Deterministic JSON serialization: sorted keys, no whitespace, no None values."""
    cleaned = {k: v for k, v in record_fields.items() if v is not None}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=_normalize)


def compute_record_hash(canonical: str, previous_hash: str) -> str:
    """SHA-256 of previous_hash + canonical content."""
    payload = previous_hash + canonical
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_record_hash(record) -> bool:
    """Recompute a record's hash and compare to stored value."""
    fields = extract_hashable_fields(record)
    canonical = canonicalize(fields)
    expected = compute_record_hash(canonical, record.previous_hash)
    return expected == record.record_hash


# ── Canonical list of fields that contribute to the record hash ──
# This is the SINGLE SOURCE OF TRUTH. Used by both chain building
# and verification. Adding a field here changes the hash contract.
HASHABLE_FIELDS = (
    "action_name",
    "action_type",
    "agent_name",
    "data_subject_id",
    "agent_version",
    "model_id",
    "model_version",
    "action_description",
    "action_timestamp",
    "target_system",
    "target_resource",
    "authorized_by",
    "authorization_scope",
    "delegation_chain",
    "result",
    "error_message",
    "duration_ms",
    "input_data",
    "policies_applied",
    "environment",
    "outcome",
    "reasoning",
    "metadata_",
    "org_id",
    "sequence_number",
    "framework",
    "framework_version",
)


def extract_hashable_fields(record) -> dict:
    """Extract the fields that contribute to the record hash.

    Uses HASHABLE_FIELDS as the single source of truth.
    Works with both ORM models and SimpleNamespace test objects.
    """
    return {f: getattr(record, f) for f in HASHABLE_FIELDS}
