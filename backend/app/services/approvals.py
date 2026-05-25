"""Human-in-the-Loop approval service.

Implements the approval lifecycle required by EU AI Act Article 14:
  - Agent requests approval (creates a pending ActionRecord in the chain)
  - Human reviewer decides (vote is signed by KMS and appended to the chain)
  - Terminal state (approved/rejected/expired) writes a final ActionRecord

Every state transition is a chain record — approvals inherit the same
tamper-evidence as everything else. The `approvals` table is a queryable
index over those records.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, ActionRecord
from ..schemas.action import ActionRecordCreate
from ..schemas.approval import ApprovalCreate, ApprovalDecision
from .chain import build_and_insert_record
from .kms import get_kms
from .webhooks import dispatch_event

logger = logging.getLogger("vera.approvals")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sign_decision_message(
    approval_id: str, decision: str, approver: str, decided_at: str
) -> bytes:
    """Canonical message bytes for signing an approval decision."""
    return f"{approval_id}:{decision}:{approver}:{decided_at}".encode("utf-8")


async def request_approval(
    session: AsyncSession, org_id: str, data: ApprovalCreate
) -> Approval:
    """Agent asks a human to approve a pending action.

    Creates:
      - A pending ActionRecord in the chain (result='pending',
        action_type='human_approval_requested')
      - An Approval row pointing to that record
    """
    now = _now()
    expires_at = None
    if data.expires_in_seconds is not None:
        expires_at = now + timedelta(seconds=data.expires_in_seconds)

    # Write the pending-request record to the chain. This is THE audit event.
    request_record_data = ActionRecordCreate(
        action_name=data.action_name,
        action_type="human_approval_requested",
        agent_name=data.agent_name,
        data_subject_id=data.data_subject_id,
        authorized_by="pending_human_review",
        authorization_scope=data.risk_tier,
        result="pending",
        input_data=data.context,
        reasoning={
            "risk_tier": data.risk_tier,
            "approvers_required": data.approvers_required,
            "action_summary": data.action_summary,
        },
    )
    request_record = await build_and_insert_record(session, org_id, request_record_data)

    approval = Approval(
        org_id=org_id,
        request_record_id=request_record.id,
        requested_by_agent=data.agent_name,
        data_subject_id=data.data_subject_id,
        action_name=data.action_name,
        action_summary=data.action_summary,
        context=data.context,
        risk_tier=data.risk_tier,
        approvers_required=data.approvers_required,
        status="pending",
        decisions=[],
        requested_at=now,
        expires_at=expires_at,
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)

    # ── Wave 2B PR A3 — dual emission (approval.* + review.*) ─────────
    # The customer-facing rename ships ``review.*`` alongside the legacy
    # ``approval.*`` names for one release; ``approval.*`` is marked
    # deprecated in ``services/webhooks.ALLOWED_EVENT_TYPES`` and will
    # be removed in Phase 4/5. Both events share idempotency keys
    # derived from ``approval_id`` so a producer-side retry never
    # double-emits (per ``webhook_retry.idempotency_key_for_review``).
    requested_at_iso = (
        approval.requested_at.isoformat() if approval.requested_at else None
    )
    expires_at_iso = (
        approval.expires_at.isoformat() if approval.expires_at else None
    )
    # Legacy event — same payload shape as pre-A3 so existing consumers
    # don't break.
    await dispatch_event(
        session,
        org_id,
        "approval.requested",
        {
            "approval_id": approval.id,
            "action_name": approval.action_name,
            "agent_name": approval.requested_by_agent,
            "risk_tier": approval.risk_tier,
            "data_subject_id": approval.data_subject_id,
            "requested_at": requested_at_iso,
        },
    )
    # New event — plan §7 payload. ``required_role`` is owned by PR A2
    # and arrives as None here until A2 lands the gate-config wiring.
    await dispatch_event(
        session,
        org_id,
        "review.requested",
        {
            "review_id": approval.id,
            "request_record_id": approval.request_record_id,
            "action_name": approval.action_name,
            "agent_name": approval.requested_by_agent,
            "risk_tier": approval.risk_tier,
            "data_subject_id": approval.data_subject_id,
            "required_role": None,  # PR A2 will populate
            "expires_at": expires_at_iso,
            "requested_at": requested_at_iso,
            "context_excerpt": approval.context,
        },
    )
    return approval


async def _resolve_and_record(
    session: AsyncSession,
    approval: Approval,
    final_status: str,
) -> Approval:
    """Mark the approval terminal and write the resolution record to the chain.

    final_status is one of: 'approved', 'rejected', 'expired'.
    Emits an ActionRecord with action_type='human_approval_resolved' and
    result='success' for approved, 'failure' for rejected/expired.
    """
    result = "success" if final_status == "approved" else "failure"

    resolution_record_data = ActionRecordCreate(
        action_name=approval.action_name,
        action_type="human_approval_resolved",
        agent_name=approval.requested_by_agent,
        data_subject_id=approval.data_subject_id,
        authorized_by="human_review",
        authorization_scope=approval.risk_tier,
        result=result,
        input_data={"approval_id": approval.id, "request_record_id": approval.request_record_id},
        reasoning={
            "final_status": final_status,
            "risk_tier": approval.risk_tier,
            "decisions": approval.decisions,
        },
    )
    resolution_record = await build_and_insert_record(
        session, approval.org_id, resolution_record_data
    )

    approval.status = final_status
    approval.resolved_at = _now()
    approval.resolution_record_id = resolution_record.id
    await session.commit()
    await session.refresh(approval)

    # ── Wave 2B PR A3 — dual emission ─────────────────────────────────
    # Legacy ``approval.resolved`` continues to fire with the pre-A3
    # payload. The new ``review.*`` event maps to either
    # ``review.completed`` (for approved/rejected) or ``review.expired``
    # (for the sweeper-driven expiry path) per plan §7. ``cancelled``
    # still rides ``approval.cancelled`` only — the customer-facing
    # ``review.*`` namespace treats cancellation as a completed review
    # with ``final_status='cancelled'`` per plan §7 mapping.
    resolved_at_iso = (
        approval.resolved_at.isoformat() if approval.resolved_at else None
    )
    await dispatch_event(
        session,
        approval.org_id,
        "approval.resolved",
        {
            "approval_id": approval.id,
            "action_name": approval.action_name,
            "final_status": final_status,
            "decisions": approval.decisions,
            "resolved_at": resolved_at_iso,
        },
    )
    if final_status == "expired":
        await dispatch_event(
            session,
            approval.org_id,
            "review.expired",
            {
                "review_id": approval.id,
                "final_status": "expired",
                "expired_at": resolved_at_iso,
                "requested_at": (
                    approval.requested_at.isoformat()
                    if approval.requested_at
                    else None
                ),
                "expires_at": (
                    approval.expires_at.isoformat()
                    if approval.expires_at
                    else None
                ),
                "resolution_record_id": approval.resolution_record_id,
            },
        )
    else:
        await dispatch_event(
            session,
            approval.org_id,
            "review.completed",
            {
                "review_id": approval.id,
                "final_status": final_status,
                "decisions": approval.decisions,
                "resolved_at": resolved_at_iso,
                "resolution_record_id": approval.resolution_record_id,
            },
        )
    return approval


async def decide_approval(
    session: AsyncSession,
    org_id: str,
    approval_id: str,
    decision: ApprovalDecision,
) -> Approval:
    """Record one reviewer's vote. Resolve if enough approvers have voted."""
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already {approval.status}",
        )

    # Lazy expiration check
    if approval.expires_at is not None and _now() > approval.expires_at:
        await _resolve_and_record(session, approval, "expired")
        raise HTTPException(status_code=410, detail="Approval has expired")

    # Dual-verification guard: same approver can't vote twice
    existing_approvers = {d.get("approver") for d in approval.decisions}
    if decision.approver in existing_approvers:
        raise HTTPException(
            status_code=409,
            detail="This approver has already voted on this approval",
        )

    now = _now()
    decided_at_iso = now.isoformat()

    # Sign the decision with KMS
    kms = get_kms()
    message = _sign_decision_message(
        approval.id, decision.decision, decision.approver, decided_at_iso
    )
    signature = kms.sign(message)

    vote = {
        "decision": decision.decision,
        "approver": decision.approver,
        "note": decision.note,
        "decided_at": decided_at_iso,
        "signature": signature,
        "key_id": kms.get_key_id(),
    }
    # Rebind so SQLAlchemy detects the change on JSON column
    approval.decisions = [*approval.decisions, vote]

    # Any rejection terminates immediately
    if decision.decision == "reject":
        await session.commit()
        await session.refresh(approval)
        return await _resolve_and_record(session, approval, "rejected")

    # Otherwise: count approvals, resolve if threshold met
    approve_count = sum(1 for d in approval.decisions if d.get("decision") == "approve")
    if approve_count >= approval.approvers_required:
        await session.commit()
        await session.refresh(approval)
        return await _resolve_and_record(session, approval, "approved")

    # Not enough approvers yet — stay pending
    await session.commit()
    await session.refresh(approval)
    return approval


async def cancel_approval(
    session: AsyncSession, org_id: str, approval_id: str, canceller: str
) -> Approval:
    """Admin or requesting agent cancels a pending approval."""
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"Approval is already {approval.status}"
        )

    approval.decisions = [
        *approval.decisions,
        {
            "decision": "cancel",
            "approver": canceller,
            "decided_at": _now().isoformat(),
        },
    ]
    approval.status = "cancelled"
    approval.resolved_at = _now()

    # Write a cancellation record to the chain
    resolution_record_data = ActionRecordCreate(
        action_name=approval.action_name,
        action_type="human_approval_resolved",
        agent_name=approval.requested_by_agent,
        data_subject_id=approval.data_subject_id,
        authorized_by=canceller,
        authorization_scope=approval.risk_tier,
        result="failure",
        input_data={"approval_id": approval.id, "request_record_id": approval.request_record_id},
        reasoning={"final_status": "cancelled", "cancelled_by": canceller},
    )
    resolution_record = await build_and_insert_record(
        session, org_id, resolution_record_data
    )
    approval.resolution_record_id = resolution_record.id

    await session.commit()
    await session.refresh(approval)

    resolved_at_iso = (
        approval.resolved_at.isoformat() if approval.resolved_at else None
    )
    await dispatch_event(
        session,
        org_id,
        "approval.cancelled",
        {
            "approval_id": approval.id,
            "action_name": approval.action_name,
            "cancelled_by": canceller,
            "resolved_at": resolved_at_iso,
        },
    )
    # ── Wave 2B PR A3 — review.completed maps cancellation per plan §7 ──
    await dispatch_event(
        session,
        org_id,
        "review.completed",
        {
            "review_id": approval.id,
            "final_status": "cancelled",
            "decisions": approval.decisions,
            "resolved_at": resolved_at_iso,
            "resolution_record_id": approval.resolution_record_id,
        },
    )
    return approval


async def get_approval_with_lazy_expiry(
    session: AsyncSession, org_id: str, approval_id: str
) -> Approval:
    """Fetch an approval; mark expired on read if past its deadline."""
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="Approval not found")

    if (
        approval.status == "pending"
        and approval.expires_at is not None
        and _now() > approval.expires_at
    ):
        return await _resolve_and_record(session, approval, "expired")
    return approval


async def list_approvals(
    session: AsyncSession,
    org_id: str,
    status: Optional[str],
    risk_tier: Optional[str],
    data_subject_id: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[Approval], int]:
    """List approvals with filters. Returns (rows, total)."""
    from sqlalchemy import func

    stmt = select(Approval).where(Approval.org_id == org_id)
    count_stmt = select(func.count()).select_from(Approval).where(Approval.org_id == org_id)

    if status is not None:
        stmt = stmt.where(Approval.status == status)
        count_stmt = count_stmt.where(Approval.status == status)
    if risk_tier is not None:
        stmt = stmt.where(Approval.risk_tier == risk_tier)
        count_stmt = count_stmt.where(Approval.risk_tier == risk_tier)
    if data_subject_id is not None:
        stmt = stmt.where(Approval.data_subject_id == data_subject_id)
        count_stmt = count_stmt.where(Approval.data_subject_id == data_subject_id)

    stmt = stmt.order_by(Approval.requested_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    return rows, total
