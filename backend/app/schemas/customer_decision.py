"""Customer Decisions feed schemas (PR C1.5 follow-up to Wave 2C PR C1).

Surfaces what each agent decision *meant* for the Customer detail page's
Decisions tab. C1 shipped the frontend tab with a client-side adapter
reading ``reasoning.gate_ruling`` / ``reasoning.webhook_delivery`` /
``reasoning.hitl_expires_at`` out of ``ActionRecord`` — but the backend
never writes those keys (the gate evaluator stashes its metadata on
``Approval.context`` instead, and webhook delivery state lives on the
``WebhookDelivery`` row). The result: every C1 row rendered as "No gate"
with no webhook dot.

This schema mirrors ``frontend/lib/api-types.ts::CustomerDecision`` /
``CustomerDecisionsResponse`` exactly so the frontend can drop its
client-side adapter and call the new endpoint directly. The string
literals (effects, statuses) match the frontend's discriminated unions
verbatim — keep them in lockstep when extending.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# Mirrors ``RulingEffect`` from frontend/lib/api-types.ts and
# ``schemas/gate.py::RulingEffect`` (whose enum values are the same
# lowercase strings). Kept as a Literal here so the response model
# doesn't pick up the gate schema's full Enum surface — the Decisions
# tab only needs to read the wire shape.
RulingEffect = Literal["allow", "require_hitl", "block"]


# Derived UI status (distinct from the canonical
# ``webhook_deliveries.status`` column). Mapping rules (encoded in
# ``services/decisions.py``):
#   backend ``succeeded``         -> ``delivered``
#   backend ``aborted``           -> ``aborted``
#   backend ``pending``  AND attempt_count > 1 AND next_retry_at not None
#                                  -> ``retrying``
#   backend ``pending`` / ``in_progress`` (otherwise) -> ``pending``
DecisionWebhookStatus = Literal["delivered", "pending", "retrying", "aborted"]


class CustomerDecisionRuling(BaseModel):
    """Per-decision gate Ruling.

    Phase 1 limitation: only HITL / BLOCK rulings are surfaced because
    those are the rulings that materialise an ``Approval`` row (whose
    ``context`` JSON carries the gate metadata). ALLOW rulings don't
    create approvals today, so they show as ``ruling=None`` in the feed.
    Wiring ALLOW rulings into the audit trail needs either SDK-side
    denormalisation onto ``ActionRecord`` or a new ``gate_evaluations``
    table — both deferred to a follow-up PR.
    """

    effect: RulingEffect
    reason: str
    reason_detail: Optional[str] = None
    citation: Optional[str] = None
    review_id: Optional[str] = None
    fix_url: Optional[str] = None
    required_role: Optional[str] = None
    gate_name: Optional[str] = None


class CustomerDecisionWebhookDelivery(BaseModel):
    """Per-decision webhook delivery summary.

    Reduced from the most recent ``WebhookDelivery`` row whose
    ``idempotency_key`` begins ``"{approval_id}:"`` — the producer-side
    convention used by ``services/webhooks._default_idempotency_key`` for
    ``review.*`` events. ``None`` when the approval never matched a
    subscription (or no approval exists for the action at all).
    """

    status: DecisionWebhookStatus
    attempt_count: int
    # Surfaced so the UI can render "Retry N/7" without hard-coding the
    # backend's MAX_ATTEMPTS. Sourced from ``services/webhook_retry.py``.
    max_attempts: int = Field(..., ge=1)
    next_retry_at: Optional[datetime] = None
    last_status_code: Optional[int] = None
    succeeded_at: Optional[datetime] = None
    aborted_at: Optional[datetime] = None


class CustomerDecisionResponse(BaseModel):
    """One row in the Customer detail Decisions tab feed.

    Composite shape: an ``ActionRecord`` left-joined to its (optional)
    ``Approval`` (via ``request_record_id``) and to the most recent
    ``WebhookDelivery`` whose idempotency key starts ``"{approval_id}:"``.
    """

    id: str
    sequence_number: int
    action_timestamp: datetime
    agent_name: str
    action_name: str
    action_type: str
    result: str
    # Present when a gate fired HITL/BLOCK on this action. ``None`` for
    # capture-only rows or actions that resolved ALLOW (see ALLOW
    # limitation above).
    ruling: Optional[CustomerDecisionRuling] = None
    # Present when the action's approval matched at least one webhook
    # subscription. ``None`` otherwise.
    webhook_delivery: Optional[CustomerDecisionWebhookDelivery] = None
    # Mirrors ``Approval.expires_at`` when the approval is still pending.
    # ``None`` for resolved / cancelled / expired approvals, and for
    # actions without an approval at all.
    hitl_expires_at: Optional[datetime] = None


class CustomerDecisionsListResponse(BaseModel):
    """Wrapper for ``GET /v1/customers/{tenant_id}/decisions``."""

    decisions: list[CustomerDecisionResponse]
    total: int
    limit: int
    offset: int
