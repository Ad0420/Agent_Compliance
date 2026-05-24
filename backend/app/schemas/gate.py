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

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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
