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
from .reviewer_roles import is_role_sufficient
from .webhooks import dispatch_event

logger = logging.getLogger("vera.approvals")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insufficient_role_detail(
    review_id: str, required_role: str | None, reviewer_role: str
) -> dict[str, object]:
    """Flat 403 envelope mirroring ``services.reviews._insufficient_role_detail``.

    Wave 2D follow-up W1.1 — the legacy ``POST /v1/approvals/{id}/decide``
    endpoint now enforces the same reviewer-role hierarchy A4's
    ``POST /v1/reviews/{id}/complete`` does. The error shape is
    duplicated (not imported) on purpose: ``services.reviews`` already
    imports from ``services.approvals`` — pulling the helper the other
    way would introduce a circular import. Keep the two envelope shapes
    in lock-step manually; the ``test_legacy_decide_role_enforcement``
    tests pin both payloads to the same fields.
    """
    return {
        "code": "reviewer_credentials_insufficient",
        "review_id": review_id,
        "required_role": required_role,
        "reviewer_role": reviewer_role,
        "detail": (
            f"Reviewer role {reviewer_role!r} does not satisfy "
            f"required role {required_role!r}."
        ),
    }


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

    Wave 2D PR A6.5 — atomicity contract
    ------------------------------------
    This function performs **no** ``session.commit()`` of its own. All
    writes (chain ``ActionRecord`` + ``Approval.status`` flip) land via
    ``session.flush()`` so the caller can commit the vote write, the
    resolution chain record, and the terminal status flip **in a single
    transaction**. The earlier two-commit pattern (vote commit then
    chain+status commit) released the ``SELECT … FOR UPDATE`` lock that
    ``services/reviews.py::complete_review`` held across the call,
    letting a concurrent caller observe a half-resolved row. See
    A6 PR #224 Codex finding #1.

    Webhook dispatch still fires inline here — ``dispatch_event`` is
    fire-and-forget (schedules ``asyncio.create_task``) so it's safe to
    run before the caller's commit. If the caller subsequently rolls
    back, the webhook will reference a row that doesn't exist in the
    canonical state; the subscriber's idempotency key
    (``approval_id`` / ``review_id``) makes the spurious delivery a
    no-op on retry. Callers that don't intend to commit MUST handle
    rollback themselves.
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
    # commit=False keeps the chain advance + the status flip below in
    # the caller's outer transaction. See A6.5 contract above.
    resolution_record = await build_and_insert_record(
        session,
        approval.org_id,
        resolution_record_data,
        commit=False,
    )

    approval.status = final_status
    approval.resolved_at = _now()
    approval.resolution_record_id = resolution_record.id
    await session.flush()

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


def _is_sqlite_session(session: AsyncSession) -> bool:
    """Mirror ``services.chain._is_sqlite`` without importing it.

    SQLite ignores ``SELECT … FOR UPDATE`` (no row locks); Postgres
    honours it. The flag gates the lock acquisition below.
    """
    url = str(session.bind.url) if session.bind else ""
    return "sqlite" in url


async def _lock_approval_row(
    session: AsyncSession, org_id: str, approval_id: str
) -> Optional[Approval]:
    """Fetch the approval row under a row-level lock on Postgres.

    Wave 2D PR A6.5: keeps the lock held across the vote write +
    resolution chain record + status flip so a concurrent caller cannot
    interleave between the writes. Closes Codex /review finding from
    A6 #224 where the previous two-commit shape released the lock the
    moment ``decide_approval`` committed the vote.

    SQLite path falls back to ``session.get`` — the driver is
    single-threaded and the in-process locks A6 added in
    ``services.reviews`` cover same-process races in the test suite.
    """
    if _is_sqlite_session(session):
        approval = await session.get(Approval, approval_id)
    else:
        result = await session.execute(
            select(Approval)
            .where(Approval.id == approval_id, Approval.org_id == org_id)
            .with_for_update()
        )
        approval = result.scalar_one_or_none()
    if approval is None or approval.org_id != org_id:
        return None
    return approval


async def decide_approval(
    session: AsyncSession,
    org_id: str,
    approval_id: str,
    decision: ApprovalDecision,
) -> Approval:
    """Record one reviewer's vote. Resolve if enough approvers have voted.

    Wave 2D PR A6.5 — single-transaction atomicity
    ----------------------------------------------
    Vote append, terminal status flip, and resolution ``ActionRecord``
    write commit together or roll back together. The row is fetched
    under ``SELECT … FOR UPDATE`` on Postgres and the lock is held
    until the single ``session.commit()`` at the end of the function,
    so a concurrent caller blocks on the row lock rather than observing
    a vote-without-status intermediate state. See the A6 #224 Codex
    finding (lock released mid-flow on Postgres).

    Wave 2D follow-up W1.1 — reviewer-role enforcement
    --------------------------------------------------
    Backports A4's role check (``services.reviews.complete_review``)
    to this legacy path so callers deciding on gated approvals (those
    A2 stashed ``required_role`` on) can no longer silently approve
    with the wrong role:

    * ``context.required_role`` is None → un-gated, any reviewer passes
      (legacy Phase 1 behaviour preserved).
    * ``context.required_role`` set + ``decision.reviewer_role`` omitted
      → 400 ``reviewer_role_required``.
    * ``context.required_role`` set + role insufficient → 403
      ``reviewer_credentials_insufficient`` with the same flat envelope
      A4 uses; sets ``reviewed_below_threshold=True`` and writes a
      chain record; approval stays pending so a higher-role reviewer
      can still resolve it.

    Closes phase2-acceptance-findings
    ``legacy-decide-no-role-enforcement`` (Critical) +
    ``require_permission-admin-too-strict-on-decide`` (Medium — the
    route-level permission relaxation is in ``routes/approvals.py``).
    """
    approval = await _lock_approval_row(session, org_id, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already {approval.status}",
        )

    # Lazy expiration check. Falls into the single-transaction write
    # path below; the 410 raise commits the expired status + chain
    # record together.
    if approval.expires_at is not None and _now() > approval.expires_at:
        await _resolve_and_record(session, approval, "expired")
        await session.commit()
        await session.refresh(approval)
        raise HTTPException(status_code=410, detail="Approval has expired")

    # ── W1.1 reviewer-role enforcement ────────────────────────────────
    # Mirrors ``services.reviews.complete_review``. Runs BEFORE the
    # dual-verification guard so an under-credentialed reviewer's
    # attempt is recorded as ``reviewer_credentials_insufficient``
    # rather than potentially being swallowed by the "already voted"
    # branch. No-op for un-gated legacy approvals where A2 didn't
    # stash a ``required_role`` in ``context``.
    context = approval.context or {}
    required_role = context.get("required_role")
    gate_name = context.get("gate_name")

    if required_role is not None:
        if decision.reviewer_role is None:
            # Backward-compat callers who never sent ``reviewer_role``
            # used to slip through silently; surface the requirement
            # explicitly so they can't approve a gated review by
            # accident. 400 (not 403) because the request shape is the
            # problem, not the reviewer's credentials.
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "reviewer_role_required",
                    "review_id": approval.id,
                    "required_role": required_role,
                    "detail": (
                        "This approval is gated with required_role="
                        f"{required_role!r}; decide calls must include "
                        "a reviewer_role."
                    ),
                },
            )

        if not is_role_sufficient(decision.reviewer_role, required_role):
            # Below-threshold callback. Write the chain record + flip
            # the flag, then raise 403. We commit BEFORE raising so the
            # audit row is durable even if the 403 response gets lost
            # on the wire — matches the pattern in
            # ``services.reviews._complete_review_locked``.
            record_data = ActionRecordCreate(
                action_name=approval.action_name,
                action_type="reviewer_credentials_insufficient",
                agent_name=approval.requested_by_agent,
                data_subject_id=approval.data_subject_id,
                authorized_by=f"reviewer:{decision.approver}",
                authorization_scope=approval.risk_tier,
                result="failure",
                input_data={
                    "review_id": approval.id,
                    "request_record_id": approval.request_record_id,
                },
                reasoning={
                    "required_role": required_role,
                    "reviewer_role": decision.reviewer_role,
                    "reviewer_id": decision.approver,
                    "gate_name": gate_name,
                    "attempted_decision": decision.decision,
                    "note": decision.note,
                    # Disambiguate from A4's path so audit-PDF
                    # generators can render endpoint-specific copy if
                    # they want; both endpoints share action_type.
                    "endpoint": "legacy_decide",
                },
            )
            await build_and_insert_record(session, org_id, record_data)

            approval.reviewed_below_threshold = True
            await session.commit()
            await session.refresh(approval)

            logger.info(
                "decide_approval.insufficient_role",
                extra={
                    "review_id": approval.id,
                    "org_id": org_id,
                    "required_role": required_role,
                    "reviewer_role": decision.reviewer_role,
                    "reviewer_id": decision.approver,
                    "gate_name": gate_name,
                },
            )

            raise HTTPException(
                status_code=403,
                detail=_insufficient_role_detail(
                    approval.id, required_role, decision.reviewer_role
                ),
            )

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

    # Compute terminal state in-memory; _resolve_and_record is no-op-
    # safe to skip when the vote does not push the row over the
    # threshold (stays pending).
    terminal_status: Optional[str] = None
    if decision.decision == "reject":
        terminal_status = "rejected"
    else:
        approve_count = sum(
            1 for d in approval.decisions if d.get("decision") == "approve"
        )
        if approve_count >= approval.approvers_required:
            terminal_status = "approved"

    if terminal_status is not None:
        # A6.5: chain record + status flip happen inside the SAME open
        # transaction as the vote append. _resolve_and_record now uses
        # flush() so the single commit below is the durability
        # boundary.
        await _resolve_and_record(session, approval, terminal_status)

    await session.commit()
    await session.refresh(approval)
    return approval


async def cancel_approval(
    session: AsyncSession, org_id: str, approval_id: str, canceller: str
) -> Approval:
    """Admin or requesting agent cancels a pending approval.

    Wave 2D PR A6.5 — same single-transaction atomicity as
    ``decide_approval``: cancel-vote append, terminal status flip,
    and cancellation ``ActionRecord`` commit together under a held row
    lock so a concurrent decider can't observe a half-cancelled row.
    """
    approval = await _lock_approval_row(session, org_id, approval_id)
    if approval is None:
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

    # Write a cancellation record to the chain. commit=False keeps the
    # chain advance inside the outer transaction so the vote + status
    # + chain record all commit or roll back together (A6.5 contract).
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
        session, org_id, resolution_record_data, commit=False
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
        # A6.5: _resolve_and_record no longer commits on its own —
        # callers own the transaction boundary. Commit here so the
        # lazy-expiry path stays equivalent to the pre-refactor
        # behaviour (one read → one durable expiry transition).
        await _resolve_and_record(session, approval, "expired")
        await session.commit()
        await session.refresh(approval)
        return approval
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
