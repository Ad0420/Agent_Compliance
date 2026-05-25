"""Phase 2 Wave 2C PR A4 — reviewer completion route.

Mounts ``POST /v1/reviews/{review_id}/complete``. Companion to the
legacy ``/v1/approvals/{id}/decide`` route — the customer-facing
``review.*`` namespace lets the dashboard (Phase 2D PR C2) and
out-of-band tools resolve a pending HITL approval without speaking the
older ``approval.*`` vocabulary.

Auth is ``write`` permission; the reviewer identity itself is carried
in the request body (``reviewer_role`` / ``reviewer_id``) and validated
against the role hierarchy in ``services.reviewer_roles``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.approval import ApprovalResponse
from ..schemas.review import ReviewCompletionInput
from ..services.auth import require_permission
from ..services.reviews import complete_review

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/{review_id}/complete", response_model=ApprovalResponse)
async def complete_review_route(
    review_id: str,
    data: ReviewCompletionInput,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("write")),
):
    """Human reviewer records their decision on a pending HITL approval.

    Returns the updated ``Approval`` row. Status codes:

    * **200** — decision recorded, row resolved (or still pending if
      the gate requires multiple approvers).
    * **403** — reviewer's role does not satisfy the gate's
      ``required_role``. Sets ``reviewed_below_threshold=True`` and
      writes a ``reviewer_credentials_insufficient`` chain record.
    * **404** — no such review for this org.
    * **409** — review already resolved / cancelled.
    * **410** — review expired.
    * **422** — input validation error.
    """
    org_id, _ = auth
    approval = await complete_review(session, org_id, review_id, data)
    return ApprovalResponse.model_validate(approval)
