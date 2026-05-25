"""Phase 2 Wave 2C PR A4 — reviewer completion service.

Implements ``POST /v1/reviews/{review_id}/complete``: a human reviewer
records their decision on a pending HITL approval that was created by
Wave 2B PR A2's gate materializer.

Flow
----
1. Look up the ``Approval`` scoped to ``org_id`` — 404 if missing.
2. If already terminal: 409 (resolved family) or 410 (expired). The
   expired check uses the same lazy-expiry contract as
   ``services.approvals.get_approval_with_lazy_expiry`` so the row's
   ``expires_at`` is honoured even if the sweeper hasn't run yet.
3. Pull ``required_role`` from ``Approval.context`` (A2 stashed it
   there). Compare to the reviewer-supplied role via
   ``services.reviewer_roles.is_role_sufficient``.
4. **Insufficient role** → write a chain ``ActionRecord`` with
   ``action_type='reviewer_credentials_insufficient'``,
   ``result='failure'``; set ``Approval.reviewed_below_threshold=True``;
   return HTTP 403 with the flat-error envelope the SDK already speaks.
5. **Sufficient role** → delegate to
   ``services.approvals.decide_approval`` (which writes the signed vote,
   final ``ActionRecord``, and dual ``approval.*`` + ``review.*``
   webhook emission); then populate the Wave 2B PR A5 columns
   ``decided_at`` + ``callback_received_at`` and return the row.

Wave 2B's forward-looking review explicitly called out the
``reviewed_below_threshold`` flag as load-bearing: the column defaults
to ``False`` and PR A4 is the writer for the True branch. The flag must
be flipped for *every* below-threshold callback even though the
approval stays pending — auditors look at this column to surface
silent-mask attempts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval
from ..schemas.action import ActionRecordCreate
from ..schemas.approval import ApprovalDecision
from ..schemas.review import ReviewCompletionInput
from .approvals import decide_approval
from .chain import build_and_insert_record
from .reviewer_roles import is_role_sufficient

logger = logging.getLogger("vera.reviews")


def _now() -> datetime:
    """Naive UTC, matching services.approvals._now (project convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insufficient_role_detail(
    review_id: str, required_role: str | None, reviewer_role: str
) -> dict[str, object]:
    """Flat error envelope for the 403 path.

    Shape matches the SDK's ``wrap_httpx_error`` contract — top-level
    ``code`` plus context fields so the dashboard can render an
    actionable "wrong role" message without parsing a nested
    ``detail`` blob.
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


async def complete_review(
    session: AsyncSession,
    org_id: str,
    review_id: str,
    data: ReviewCompletionInput,
) -> Approval:
    """Resolve a pending HITL approval on behalf of a human reviewer.

    Raises ``HTTPException`` with the documented status codes (403, 404,
    409, 410). On success returns the updated ``Approval`` row with the
    Wave 2B PR A5 timing columns populated.
    """
    approval = await session.get(Approval, review_id)
    if approval is None or approval.org_id != org_id:
        raise HTTPException(status_code=404, detail="Review not found")

    # ── Already-terminal guards. Mirror the lazy-expiry contract from
    # services.approvals.get_approval_with_lazy_expiry so a reviewer
    # racing the sweeper sees a consistent 410 even on the first
    # callback.
    if approval.status != "pending":
        # Distinguish expired (410) from the other terminal states
        # (409). Cancelled / approved / rejected all surface as 409 —
        # the reviewer is too late, but for a different reason than
        # the deadline elapsing.
        if approval.status == "expired":
            raise HTTPException(status_code=410, detail="Review has expired")
        raise HTTPException(
            status_code=409, detail=f"Review is already {approval.status}"
        )

    # Lazy expiration: same naive-UTC comparison the approval service
    # uses. Don't transition the row here — the next
    # ``decide_approval`` call (or the sweeper) will, and 410 is what
    # the reviewer needs to see *now*.
    if approval.expires_at is not None and _now() > approval.expires_at:
        raise HTTPException(status_code=410, detail="Review has expired")

    context = approval.context or {}
    required_role = context.get("required_role")
    gate_name = context.get("gate_name")

    if not is_role_sufficient(data.reviewer_role, required_role):
        # ── Below-threshold callback. Plan §"CRITICAL design notes" calls
        # this out as the load-bearing requirement: write the chain
        # record AND flip the flag, even though the approval itself
        # stays pending (so a higher-role reviewer can still resolve it
        # later).
        record_data = ActionRecordCreate(
            action_name=approval.action_name,
            action_type="reviewer_credentials_insufficient",
            agent_name=approval.requested_by_agent,
            data_subject_id=approval.data_subject_id,
            authorized_by=f"reviewer:{data.reviewer_id}",
            authorization_scope=approval.risk_tier,
            result="failure",
            input_data={
                "review_id": approval.id,
                "request_record_id": approval.request_record_id,
            },
            reasoning={
                "required_role": required_role,
                "reviewer_role": data.reviewer_role,
                "reviewer_id": data.reviewer_id,
                "gate_name": gate_name,
                "attempted_decision": data.decision,
                # ``note`` is bounded to 2 KB by ReviewCompletionInput
                # so this is safe to anchor in the chain.
                "note": data.note,
            },
        )
        await build_and_insert_record(session, org_id, record_data)

        approval.reviewed_below_threshold = True
        await session.commit()
        await session.refresh(approval)

        logger.info(
            "review.complete.insufficient_role",
            extra={
                "review_id": approval.id,
                "org_id": org_id,
                "required_role": required_role,
                "reviewer_role": data.reviewer_role,
                "reviewer_id": data.reviewer_id,
                "gate_name": gate_name,
            },
        )

        raise HTTPException(
            status_code=403,
            detail=_insufficient_role_detail(
                approval.id, required_role, data.reviewer_role
            ),
        )

    # ── Sufficient role. Delegate to the existing approval-decision
    # service so the chain vote signature, dual webhook emission, and
    # status-machine all stay in lock-step with the legacy
    # POST /v1/approvals/{id}/decide path.
    decision = ApprovalDecision(
        decision=data.decision,
        # ``approver`` is the canonical identifier the signed vote
        # records. Combine reviewer_id with role so a single human
        # acting under different role hats produces distinct
        # signatures.
        approver=f"{data.reviewer_id}:{data.reviewer_role}",
        note=data.note,
    )
    resolved = await decide_approval(session, org_id, review_id, decision)

    # Wave 2B PR A5 columns. PR A2 left them server-default False/NULL;
    # PR A4 is the writer for the post-decision branch. Set
    # ``decided_at`` only when the row actually moved to a terminal
    # state — single-vote approvals always do, but a 2-of-N approval
    # with ``approve`` from one reviewer stays pending and we should
    # NOT pretend the row is decided yet.
    now = _now()
    resolved.callback_received_at = now
    if resolved.status != "pending":
        resolved.decided_at = now
    await session.commit()
    await session.refresh(resolved)

    logger.info(
        "review.complete.resolved",
        extra={
            "review_id": resolved.id,
            "org_id": org_id,
            "final_status": resolved.status,
            "reviewer_id": data.reviewer_id,
            "reviewer_role": data.reviewer_role,
            "gate_name": gate_name,
        },
    )
    return resolved


__all__ = ["complete_review"]
