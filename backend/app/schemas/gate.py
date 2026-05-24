"""Phase 2 Wave 2A — Ruling contract for the gates surface.

This module defines the single source of truth for what a gate decided.
``Ruling`` is returned by ``POST /v1/gates/evaluate`` and consumed by the
SDK's ``@vera.gate`` decorator (Wave 2B PR B1), which routes on
``Ruling.effect``:

* ``ALLOW``        → proceed with the action
* ``REQUIRE_HITL`` → block until a human reviewer signs off (review queue)
* ``BLOCK``        → refuse outright (cite regulation)

The Phase 2 Wave 2A evaluator returns ``ALLOW`` for every input — see
``app/services/gates/evaluator.py``. Real gate logic (ClinicalScribePack:
new diagnosis, controlled-substance via RxNorm + DEA list, stale BAA)
ships in Wave 2B PR A2 and is intentionally out of scope here.

The future intent is **strictest-gate-wins reduction** across multiple
registered gates: ``BLOCK`` > ``REQUIRE_HITL`` > ``ALLOW``. That reduction
will live in the evaluator once more than one gate exists.
"""

import json
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# Mirrors the tenant_id regex enforced on ``ActionRecordCreate``. Phase 2
# gates evaluate the *proposed* action before the ledger sees it, so the
# shape contract has to match — otherwise a PHI-shaped tenant_id could
# pass the gate but be rejected by ``POST /v1/actions`` immediately after,
# leaving the SDK in an unrecoverable state.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Mirrors the per-field JSON size cap on ``ActionRecordCreate``. Same
# lockstep rationale as the tenant_id regex: a 10 MB ``input_data`` blob
# that passes the gate but is rejected by ``POST /v1/actions`` leaves the
# SDK with no recoverable path. Keep this constant in sync with
# ``app/schemas/action.py::_MAX_JSON_BYTES``.
_MAX_JSON_BYTES = 1_000_000  # 1 MB


class RulingEffect(str, Enum):
    """The three terminal outcomes a gate can hand back to the SDK."""

    ALLOW = "allow"
    REQUIRE_HITL = "require_hitl"
    BLOCK = "block"


class Ruling(BaseModel):
    """Single source of truth for what a gate decided.

    Returned by ``POST /v1/gates/evaluate``. Consumed by the SDK's
    ``@vera.gate`` decorator (Wave 2B PR B1), which routes on
    ``effect``. Optional fields are populated only when relevant
    (``review_id`` only for ``REQUIRE_HITL``, ``citation`` only when a
    gate cites a regulation, etc.).
    """

    effect: RulingEffect
    reason: str = Field(
        ...,
        description=(
            "Machine-readable reason code, e.g. "
            "'controlled_substance_detected'"
        ),
    )
    reason_detail: Optional[str] = Field(
        None,
        description=(
            "Human-readable explanation, safe to surface to end users (no PHI)"
        ),
    )
    citation: Optional[str] = Field(
        None,
        description=(
            "Regulatory citation if applicable, e.g. '45 CFR 164.502(b)'"
        ),
    )
    review_id: Optional[str] = Field(
        None,
        description=(
            "Set when effect=REQUIRE_HITL — UUID of the created ApprovalRecord"
        ),
    )
    fix_url: Optional[str] = Field(
        None,
        description=(
            "Dashboard URL the agent or human reviewer should visit"
        ),
    )
    required_role: Optional[str] = Field(
        None,
        description=(
            "When effect=REQUIRE_HITL, the reviewer role required "
            "(e.g. 'attending_physician', 'dea_authorized')"
        ),
    )
    gate_name: Optional[str] = Field(
        None,
        description=(
            "Identifier of the gate that produced this ruling "
            "(None for stub allow)"
        ),
    )


class GateEvaluateRequest(BaseModel):
    """Payload to ``POST /v1/gates/evaluate``.

    Mirrors ``ActionRecord`` fields the gates need. Intentionally a
    subset — gates evaluate the *proposed* action before it is recorded,
    so we don't require sequence/hash fields. Field constraints mirror
    ``ActionRecordCreate`` where applicable so downstream gates (Wave 2B)
    can rely on the same shape they see on the ledger.
    """

    agent_name: str = Field(..., min_length=1, max_length=500)
    agent_id: Optional[str] = Field(default=None, max_length=500)
    action_type: str = Field(..., min_length=1, max_length=100)
    action_name: str = Field(..., min_length=1, max_length=500)
    action_description: Optional[str] = Field(default=None, max_length=5000)
    tenant_id: Optional[str] = Field(default=None, max_length=64)
    data_subject_id: Optional[str] = Field(default=None, max_length=500)
    target_system: Optional[str] = Field(default=None, max_length=500)
    target_resource: Optional[str] = Field(default=None, max_length=2000)
    authorized_by: str = Field(..., min_length=1, max_length=500)
    input_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant_id_shape(cls, v: Optional[str]) -> Optional[str]:
        """Reject malformed tenant_id at the gate boundary.

        Mirrors the regex enforced on ``ActionRecordCreate.tenant_id``
        so a payload that would be rejected by ``POST /v1/actions``
        is also rejected by the gate — keeps the two boundaries in
        lock-step.
        """
        if v is None or v == "":
            return None
        if not _TENANT_ID_RE.match(v):
            raise ValueError(
                "tenant_id must match ^[a-zA-Z0-9_-]{1,64}$"
            )
        return v

    @field_validator("input_data", "metadata")
    @classmethod
    def _check_json_size(
        cls, v: dict[str, Any], info: Any
    ) -> dict[str, Any]:
        """Cap per-field JSON size at the gate boundary.

        Mirrors the 1 MB cap on ``ActionRecordCreate.input_data`` /
        ``metadata``. Without this mirror, a 10 MB blob would clear the
        gate, run real gate logic in Wave 2B (RxNorm lookups, DEA list
        scans), and then be rejected by ``POST /v1/actions`` — leaving
        the SDK with no recoverable path and wasting gate compute.
        Same lockstep rationale as the tenant_id regex above.
        """
        if v and len(json.dumps(v, default=str)) > _MAX_JSON_BYTES:
            raise ValueError(
                f"{info.field_name} exceeds maximum size of "
                f"{_MAX_JSON_BYTES} bytes"
            )
        return v
