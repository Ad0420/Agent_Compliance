"""Review routes — proxy a nurse decision to Vera, unblock the worker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from simulator.customers.triageguard.backend.auth import require_session
from simulator.customers.triageguard.backend.schemas import DecideReviewRequest
from simulator.customers.triageguard.backend.workflow_runner import resolve_pending


router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("/{vera_approval_id}/decide")
async def decide_review(
    vera_approval_id: str,
    body: DecideReviewRequest,
    _user: str = Depends(require_session),
) -> dict:
    """Resolve a pending nurse review.

    The actual `POST /v1/approvals/{id}/decide` call to Vera is made by
    the workflow thread (see `workflows/session.py::_decide_approval_via_api`)
    once the nurse callback returns. Here we just wake the worker up
    with the captured decision and return its outcome.
    """
    found = resolve_pending(
        vera_approval_id, body.decision, body.nurse, body.note
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No pending review with that id. The session may have "
                "already terminated, expired, or never reached the HITL gate."
            ),
        )
    return {
        "approval_id": vera_approval_id,
        "decision": body.decision,
        "nurse": body.nurse,
        "received": True,
    }
