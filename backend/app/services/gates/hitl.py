"""Phase 2 Wave 2B — HITL approval materializer.

Creates the ``Approval`` row when a gate ruling resolves to
``REQUIRE_HITL`` and returns the ruling with ``review_id`` populated.

This is a *thin wrapper* over ``services.approvals.request_approval``
that keeps the evaluator free of approval-service / chain / webhook
coupling. The evaluator stays "decide which ruling wins"; this module
owns "if HITL, write the row".

Approval.context payload
------------------------
Gate metadata is stashed in ``Approval.context`` (JSON column) so the
A4 reviewer-completion path can read ``required_role`` / ``citation``
without joining a separate table. PR A5 already shipped the new
``Approval`` columns (``decided_at``, ``reviewed_below_threshold``, …)
but those are A4's to populate — A2 only writes context.

Keys placed in context (all snake_case, all flat):

* ``gate_name``       — winning gate identifier
* ``required_role``   — reviewer role to satisfy this gate
* ``citation``        — regulation cited
* ``reason``          — machine-readable ruling reason
* ``original_input_data`` — the agent's full input payload (so the
  reviewer has the chart-entry context to decide)
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.approval import ApprovalCreate
from ...schemas.gate import GateEvaluateRequest, Ruling, RulingEffect
from ..approvals import request_approval

logger = logging.getLogger("vera.gates.hitl")

# Risk-tier and approvers default. Hardcoded in A2 — PR A5 will let
# packs configure these per gate.
_HITL_RISK_TIER = "high"
_HITL_APPROVERS_REQUIRED = 1


async def materialize_hitl_approval(
    session: AsyncSession,
    org_id: str,
    request: GateEvaluateRequest,
    ruling: Ruling,
) -> Ruling:
    """Create the ``Approval`` row for a ``REQUIRE_HITL`` ruling.

    Returns the input ruling with ``review_id`` populated. Idempotent
    on its inputs in the sense that calling twice produces two distinct
    approval rows — the evaluator is responsible for calling this
    exactly once per ``POST /v1/gates/evaluate``.

    The ``request_approval`` service writes a pending ``ActionRecord``
    to the chain, persists the ``Approval`` row, and dispatches the
    ``approval.requested`` webhook. PR A3 will layer a ``review.*``
    dual-emission on top of the same call site without needing changes
    here.
    """
    if ruling.effect is not RulingEffect.REQUIRE_HITL:
        raise ValueError(
            f"materialize_hitl_approval called with effect={ruling.effect!r}; "
            f"expected REQUIRE_HITL"
        )

    approval_create = ApprovalCreate(
        agent_name=request.agent_name,
        action_name=request.action_name,
        # The reviewer needs a human-readable summary of *what was
        # proposed*. Reusing ruling.reason_detail gives them the
        # regulatory framing too (e.g. "CMS requires an attending
        # physician to confirm new diagnoses ...").
        action_summary=ruling.reason_detail,
        data_subject_id=request.data_subject_id,
        context={
            "gate_name": ruling.gate_name,
            "required_role": ruling.required_role,
            "citation": ruling.citation,
            "reason": ruling.reason,
            # Stash the original payload so the reviewer can see exactly
            # what the agent wanted to do. This is intentionally NOT
            # echoed in the Ruling response — only the human reviewer
            # (who has appropriate access) ever reads it back.
            "original_input_data": request.input_data,
        },
        risk_tier=_HITL_RISK_TIER,
        approvers_required=_HITL_APPROVERS_REQUIRED,
    )

    approval = await request_approval(session, org_id, approval_create)

    logger.info(
        "gate.hitl.materialized",
        extra={
            "gate_name": ruling.gate_name,
            "approval_id": approval.id,
            "org_id": org_id,
            "required_role": ruling.required_role,
        },
    )

    # Return a NEW Ruling carrying the freshly-created approval.id.
    # ``model_copy`` preserves all other fields (citation, gate_name,
    # required_role, reason_detail) without mutating the input.
    return ruling.model_copy(update={"review_id": approval.id})


__all__ = ["materialize_hitl_approval"]
