import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# Max size for individual JSON fields (serialized)
_MAX_JSON_BYTES = 1_000_000  # 1 MB

# Valid result values a client may submit. "blocked" is engine-set only —
# the policy engine assigns it when a block-action policy fires; clients are
# not allowed to claim a record was blocked themselves.
_CLIENT_RESULT_VALUES = ("success", "failure", "partial", "pending")

# ``tenant_id`` format. Matches the regex on ``Customer.tenant_id`` and is
# tested in test_customer_schemas. Rejecting at the action boundary too
# means we never auto-discover a Customer with an unprintable / PHI-shaped
# tenant_id — the dashboard's display_name=tenant_id default would then
# leak that shape to operators.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _validate_json_size(v: dict | list, field_name: str) -> dict | list:
    """Reject JSON blobs larger than 1 MB when serialized."""
    if v and len(json.dumps(v, default=str)) > _MAX_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum size of {_MAX_JSON_BYTES} bytes")
    return v


class ActionRecordCreate(BaseModel):
    """Fields the SDK sends when recording an action."""
    model_config = {"protected_namespaces": ()}

    action_name: str = Field(..., min_length=1, max_length=500)
    action_type: str = Field(default="function_call", min_length=1, max_length=100)
    agent_name: str = Field(..., min_length=1, max_length=500)
    data_subject_id: Optional[str] = Field(default=None, max_length=500)
    agent_version: Optional[str] = Field(default=None, max_length=100)
    model_id: Optional[str] = Field(default=None, max_length=200)
    model_version: Optional[str] = Field(default=None, max_length=100)
    framework: Optional[str] = Field(default=None, max_length=100)
    framework_version: Optional[str] = Field(default=None, max_length=100)
    action_description: Optional[str] = Field(default=None, max_length=5000)
    action_timestamp: Optional[datetime] = None
    target_system: Optional[str] = Field(default=None, max_length=500)
    target_resource: Optional[str] = Field(default=None, max_length=2000)
    # ── Phase 1 PR 1: promoted from metadata blob ─────────
    # SDK callers may now set these directly. Format-validation
    # (tenant_id regex, PHI-shape heuristic on live keys) lands in
    # Phase 1 PRs 4 & 5; here we only widen the input shape so the
    # schema accepts the new fields.
    tenant_id: Optional[str] = Field(default=None, max_length=64)
    domain: Optional[str] = Field(default=None, max_length=32)
    action_class: Optional[str] = Field(default=None, max_length=64)
    authorized_by: str = Field(default="system", max_length=500)
    authorization_scope: Optional[str] = Field(default=None, max_length=1000)
    delegation_chain: list = Field(default_factory=list)
    result: str = Field(default="success", max_length=20)
    error_message: Optional[str] = Field(default=None, max_length=10000)
    duration_ms: Optional[int] = Field(default=None, ge=0)
    input_data: dict = Field(default_factory=dict)
    policies_applied: list = Field(default_factory=list)
    environment: dict = Field(default_factory=dict)
    reasoning: dict = Field(default_factory=dict)
    outcome: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @field_validator("tenant_id")
    @classmethod
    def check_tenant_id_format(cls, v: Optional[str]) -> Optional[str]:
        """Reject malformed tenant_id at the API boundary (Phase 1 PR 2 B4).

        Test plan: ``tenant_id="John Doe DOB 1972"`` → 422 (the regex
        rejects whitespace and the digits-with-spaces shape that screams
        "I'm a patient name"). ``tenant_id="cleveland_clinic"`` → 200.

        Falsy values pass through as ``None`` — the field is optional on
        the SDK side until Phase 1 PR 4 makes it required for live keys.
        """
        if v is None or v == "":
            return None
        if not _TENANT_ID_RE.match(v):
            raise ValueError(
                "tenant_id must match ^[a-zA-Z0-9_-]{1,64}$"
            )
        return v

    @field_validator("result")
    @classmethod
    def check_result_value(cls, v: str) -> str:
        """Reject engine-only result values from client submissions.

        ``blocked`` is reserved for the policy engine: when a policy with
        ``action="block"`` fires inside ``build_and_insert_record``, the
        engine overrides the client's ``result`` to ``"blocked"`` before
        the row is hashed. Allowing clients to send it directly would let
        callers self-attest a block without a policy actually firing.
        """
        if v not in _CLIENT_RESULT_VALUES:
            raise ValueError(
                f"result must be one of {_CLIENT_RESULT_VALUES}; "
                f"'{v}' is not a valid client-submitted value"
            )
        return v

    @field_validator("input_data", "environment", "reasoning", "outcome", "metadata")
    @classmethod
    def check_json_size(cls, v, info):
        return _validate_json_size(v, info.field_name)

    @field_validator("delegation_chain", "policies_applied")
    @classmethod
    def check_list_size(cls, v, info):
        return _validate_json_size(v, info.field_name)

    @field_validator("action_timestamp")
    @classmethod
    def check_timestamp_bounds(cls, v):
        if v is None:
            return v
        now = datetime.now(timezone.utc)
        min_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
        max_ts = now + timedelta(hours=24)
        # Compare in naive UTC to avoid tz-aware/naive mismatch
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v
        if v_naive < min_ts.replace(tzinfo=None):
            raise ValueError("action_timestamp cannot be before 2020-01-01")
        if v_naive > max_ts.replace(tzinfo=None):
            raise ValueError("action_timestamp cannot be more than 24 hours in the future")
        return v


class ActionRecordResponse(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    id: str
    org_id: str
    sequence_number: int
    previous_hash: str
    record_hash: str
    recorded_at: datetime
    agent_name: str
    agent_version: Optional[str] = None
    agent_id: Optional[str] = None
    data_subject_id: Optional[str] = None
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    framework: Optional[str] = None
    framework_version: Optional[str] = None
    action_type: str
    action_name: str
    action_description: Optional[str] = None
    action_timestamp: datetime
    target_system: Optional[str] = None
    target_resource: Optional[str] = None
    # Phase 1 PR 1: promoted columns surfaced in responses for
    # dashboard rendering and SDK round-trip parity.
    tenant_id: Optional[str] = None
    domain: Optional[str] = None
    action_class: Optional[str] = None
    authorized_by: str
    authorization_scope: Optional[str] = None
    delegation_chain: list = Field(default_factory=list)
    result: str
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    input_data: dict = Field(default_factory=dict)
    policies_applied: list = Field(default_factory=list)
    environment: dict = Field(default_factory=dict)
    outcome: dict = Field(default_factory=dict)
    reasoning: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class ActionRecordBatchCreate(BaseModel):
    records: list[ActionRecordCreate] = Field(..., min_length=1, max_length=100)


class ActionRecordQuery(BaseModel):
    agent_name: Optional[str] = None
    action_type: Optional[str] = None
    result: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    search: Optional[str] = Field(default=None, max_length=200)
    limit: int = Field(default=50, le=200)
    offset: int = 0


class ActionRecordListResponse(BaseModel):
    records: list[ActionRecordResponse]
    total: int
    limit: int
    offset: int
