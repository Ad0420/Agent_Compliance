"""Approval routes — proxy a physician decision to Vera, unblock the worker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from simulator.customers.scribemd.backend.auth import require_session
from simulator.customers.scribemd.backend.schemas import DecideApprovalRequest
from simulator.customers.scribemd.backend.workflow_runner import resolve_pending


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.post("/{vera_approval_id}/decide")
async def decide_approval(
    vera_approval_id: str,
    body: DecideApprovalRequest,
    _user: str = Depends(require_session),
) -> dict:
    """Resolve a pending approval.

    The actual `POST /v1/approvals/{id}/decide` call to Vera is made by the
    workflow thread (see `workflows/encounter.py::_decide_approval_via_api`)
    once the physician callback returns. Here we just wake the worker up
    with the captured decision and return its outcome.
    """
    found = resolve_pending(
        vera_approval_id, body.decision, body.approver, body.note
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No pending approval with that id. The encounter may have "
                "already terminated, expired, or never reached the HITL gate."
            ),
        )
    return {
        "approval_id": vera_approval_id,
        "decision": body.decision,
        "approver": body.approver,
        "received": True,
    }
