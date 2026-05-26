"""Review Inbox API (W2.1).

The clinician's in-band UI calls these endpoints. The Approve/Reject
button routes through Vera's SDK (``complete_review``) so the call lands
on the audit chain via an SDK-recorded action rather than a raw HTTP
hit. Vera then POSTs ``review.completed`` back to ``/vera/webhooks``;
we flip the row to terminal there.

`GET /api/reviews` — list, default scope ``pending``.
`POST /api/reviews/{id}/decide` — record decision via Vera SDK.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.customers.scribemd.backend.auth import require_session
from simulator.customers.scribemd.backend.config import get_settings
from simulator.customers.scribemd.backend.db import get_session
from simulator.customers.scribemd.backend.models import ReviewInboxItem
from simulator.customers.scribemd.backend.schemas import (
    DecideReviewRequest,
    ReviewInboxItemResponse,
    ReviewInboxListResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


# ── SDK factory hook ────────────────────────────────────────────────────────
#
# We resolve a Vera SDK client on every Approve/Reject call so the
# `complete_review` request goes through the audited SDK rather than raw
# HTTP. Tests swap this for a recording fake; production resolves via
# `simulator.shared.vera_setup.get_client`.


def _default_get_vera_client(*, agent_name: str):
    from simulator.shared.vera_setup import get_client

    settings = get_settings()
    return get_client(
        settings.vera_customer_slug,
        agent_name=agent_name,
        framework="scribemd-review-inbox",
    )


get_vera_client: Callable[..., object] = _default_get_vera_client


def install_test_vera_factory(factory: Callable[..., object]) -> None:
    """Swap the SDK client factory. Tests call this in setup."""
    global get_vera_client
    get_vera_client = factory


def restore_default_vera_factory() -> None:
    global get_vera_client
    get_vera_client = _default_get_vera_client


# ── Routes ──────────────────────────────────────────────────────────────────


StatusFilter = Literal["pending", "approved", "rejected", "expired", "all"]


@router.get("", response_model=ReviewInboxListResponse)
async def list_reviews(
    status_filter: StatusFilter = Query("pending", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: str = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> ReviewInboxListResponse:
    """List Review Inbox items. Default scope = pending, newest first."""
    stmt = select(ReviewInboxItem).order_by(ReviewInboxItem.created_at.desc())
    if status_filter != "all":
        stmt = stmt.where(ReviewInboxItem.status == status_filter)
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    items = [ReviewInboxItemResponse.model_validate(row.to_dict()) for row in rows]
    return ReviewInboxListResponse(items=items, total=len(items))


@router.get("/{approval_id}", response_model=ReviewInboxItemResponse)
async def get_review(
    approval_id: str,
    _user: str = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> ReviewInboxItemResponse:
    row = await session.get(ReviewInboxItem, approval_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review_not_found",
        )
    return ReviewInboxItemResponse.model_validate(row.to_dict())


@router.post("/{approval_id}/decide", response_model=ReviewInboxItemResponse)
async def decide_review(
    approval_id: str,
    body: DecideReviewRequest,
    user: str = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> ReviewInboxItemResponse:
    """Record the clinician's decision through Vera's SDK.

    The local row is flipped to the decided state *optimistically* — we
    keep `status="pending"` and stash the actor on a separate field
    until Vera's `review.completed` webhook arrives to confirm. That
    way the audit chain stays canonical and a network failure mid-call
    doesn't surface as "approved on the EHR but not on Vera".

    Status codes match Vera's underlying ``/v1/reviews/{id}/complete``:

    * 200 — accepted; the row will flip to terminal when the matching
      webhook arrives back.
    * 403 — reviewer's role doesn't satisfy ``required_role``.
    * 404 — no such review on this customer.
    * 409 — already resolved.
    * 410 — expired.
    """
    row = await session.get(ReviewInboxItem, approval_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review_not_found",
        )
    if row.status != "pending":
        # Already terminal — surface as 409 so the UI can refresh.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"review_already_{row.status}",
        )

    # Build an SDK client and call complete_review. We catch the SDK's
    # branded errors and map them onto the EHR's HTTP shape.
    try:
        client = get_vera_client(agent_name="scribemd-review-inbox")
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not build Vera SDK client: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="vera_client_unavailable",
        ) from exc

    decided_at = datetime.now(timezone.utc).isoformat()

    try:
        # The SDK's `complete_review` is sync (httpx.Client + retry budget).
        # Offload to a worker thread so the FastAPI event loop stays
        # responsive — a multi-second Vera roundtrip would otherwise
        # block every concurrent request on this process.
        await asyncio.to_thread(
            client.complete_review,
            review_id=approval_id,
            decision=body.decision,
            reviewer_role=body.reviewer_role,
            reviewer_id=user,
            note=body.note,
            decided_at=decided_at,
        )
    except Exception as exc:  # noqa: BLE001
        # Map the SDK's branded errors onto HTTP status codes. We import
        # lazily so this module doesn't hard-fail at import when the SDK
        # is missing in some pruned test environment.
        try:
            from vera.errors import (
                ReviewerCredentialsInsufficient,
                VeraClientError,
            )
        except ImportError:  # pragma: no cover — defensive
            ReviewerCredentialsInsufficient = ()  # type: ignore[assignment]
            VeraClientError = ()  # type: ignore[assignment]

        if ReviewerCredentialsInsufficient and isinstance(
            exc, ReviewerCredentialsInsufficient  # type: ignore[arg-type]
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="reviewer_credentials_insufficient",
            ) from exc
        if VeraClientError and isinstance(exc, VeraClientError):  # type: ignore[arg-type]
            sdk_status = getattr(exc, "status_code", 502) or 502
            raise HTTPException(
                status_code=sdk_status,
                detail=str(exc) or "vera_client_error",
            ) from exc
        logger.exception("complete_review failed for %s", approval_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="vera_complete_review_failed",
        ) from exc
    finally:
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:  # noqa: BLE001
            pass

    # Stash decided_by/note on the local row so the inbox view can show
    # "you decided X" even before Vera's webhook confirms the flip.
    row.decided_by = user
    row.decision_note = body.note
    await session.flush()
    await session.commit()
    return ReviewInboxItemResponse.model_validate(row.to_dict())
