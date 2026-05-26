"""GET /v1/checkpoints/{date} — Wave 3B.1.

Returns the checkpoint sealed at end of the given ISO-8601 calendar date
(UTC). The response is byte-stable across calls for the same checkpoint
— auditors will diff it against the customer's S3 mirror export.

IAM tier rules (Wave 3A.c):
* Customer tier reads only their own org's checkpoints.
* Staff tier MAY pass ``X-Org-Id`` header to read any org; every staff
  read writes a row to ``staff_audit_log`` via ``services.iam.
  audit_staff_read``. The brief spec'd ``?org_id=`` query param; we
  use the established ``X-Org-Id`` header for IAM consistency with
  the rest of the staff-tier API. Documented in PR body.

Response shape:
    {
        "checkpoint_id": ...,
        "org_id": ...,
        "merkle_root": ...,
        "kms_key_id": ...,
        "signature": ...,
        "signed_at": ...,
        "head_action_id": ...,
        "record_count": ...,
        "prior_checkpoint_id": ...,
        "sequence_at_checkpoint": ...,
        "hash_at_checkpoint": ...
    }

Errors:
* 400 — malformed ``date`` (not ISO-8601 calendar form).
* 404 — no checkpoint sealed on that day for the resolved org.
* 409 — today's date is requested and today's checkpoint hasn't sealed
        yet. Carries ``Retry-After: 60`` header so SDK clients can
        back off automatically. Body: ``{"code": "checkpoint_pending"}``.
"""

from __future__ import annotations

import json
import logging
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ActionRecord, Checkpoint
from ..services.auth import AuthContext, require_permission_with_context
from ..services.iam import IamTier, audit_staff_read

logger = logging.getLogger("vera.checkpoints_by_date")

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_iso_date(raw: str) -> date_cls:
    """Parse an ISO-8601 calendar date (``YYYY-MM-DD``). 400 on bad input.

    We don't accept full ISO timestamps — the route is calendar-day
    granularity by contract (auditors diff "the checkpoint for
    May 25") and accepting timestamps would let two different
    timestamps return different checkpoints for the same day.
    """
    try:
        return date_cls.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date",
                "detail": (
                    "date path parameter must be an ISO-8601 calendar "
                    "date (YYYY-MM-DD)."
                ),
            },
        ) from exc


async def _latest_checkpoint_in_window(
    session: AsyncSession,
    *,
    org_id: str,
    day: date_cls,
) -> Optional[Checkpoint]:
    """Return the checkpoint sealed at the end of ``day`` for ``org_id``.

    "Sealed at end of day" = the checkpoint with the latest
    ``created_at`` in the UTC half-open window [day 00:00, day+1 00:00).
    Multiple checkpoints in the same day → we return the latest (matches
    the contract: auditors diff against THE checkpoint for that day).
    """
    window_start = datetime.combine(day, datetime.min.time())
    window_end = window_start + timedelta(days=1)
    q = (
        select(Checkpoint)
        .where(
            and_(
                Checkpoint.org_id == org_id,
                Checkpoint.created_at >= window_start,
                Checkpoint.created_at < window_end,
            )
        )
        .order_by(Checkpoint.created_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalars().first()


async def _prior_checkpoint_id(
    session: AsyncSession,
    *,
    org_id: str,
    checkpoint: Checkpoint,
) -> Optional[str]:
    q = (
        select(Checkpoint.id)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint
            < checkpoint.sequence_at_checkpoint,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _record_count_in_window(
    session: AsyncSession,
    *,
    org_id: str,
    checkpoint: Checkpoint,
    prior_seq: int,
) -> int:
    q = (
        select(ActionRecord.id)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.sequence_number > prior_seq,
            ActionRecord.sequence_number
            <= checkpoint.sequence_at_checkpoint,
        )
    )
    res = await session.execute(q)
    return len(res.scalars().all())


async def _prior_seq(
    session: AsyncSession,
    *,
    org_id: str,
    checkpoint: Checkpoint,
) -> int:
    q = (
        select(Checkpoint.sequence_at_checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint
            < checkpoint.sequence_at_checkpoint,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    res = (await session.execute(q)).scalar_one_or_none()
    return int(res) if res is not None else 0


async def _head_action_id(
    session: AsyncSession,
    *,
    org_id: str,
    checkpoint: Checkpoint,
) -> Optional[str]:
    q = select(ActionRecord.id).where(
        ActionRecord.org_id == org_id,
        ActionRecord.sequence_number == checkpoint.sequence_at_checkpoint,
    )
    return (await session.execute(q)).scalar_one_or_none()


def _format_signed_at(ts: datetime) -> str:
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    ts = ts.replace(microsecond=(ts.microsecond // 1000) * 1000)
    return ts.isoformat(timespec="milliseconds")


async def _build_response_body(
    session: AsyncSession,
    *,
    org_id: str,
    checkpoint: Checkpoint,
) -> dict[str, Any]:
    prior_seq = await _prior_seq(session, org_id=org_id, checkpoint=checkpoint)
    prior_id = await _prior_checkpoint_id(
        session, org_id=org_id, checkpoint=checkpoint
    )
    record_count = await _record_count_in_window(
        session, org_id=org_id, checkpoint=checkpoint, prior_seq=prior_seq
    )
    head_id = await _head_action_id(
        session, org_id=org_id, checkpoint=checkpoint
    )
    return {
        "checkpoint_id": checkpoint.id,
        "org_id": checkpoint.org_id,
        "merkle_root": checkpoint.merkle_root,
        "kms_key_id": checkpoint.key_id,
        "signature": checkpoint.signature,
        "signed_at": _format_signed_at(checkpoint.created_at),
        "head_action_id": head_id,
        "record_count": record_count,
        "prior_checkpoint_id": prior_id,
        "sequence_at_checkpoint": checkpoint.sequence_at_checkpoint,
        "hash_at_checkpoint": checkpoint.hash_at_checkpoint,
    }


@router.get("/{checkpoint_date}")
async def get_checkpoint_by_date(
    checkpoint_date: str,
    response: Response,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> Response:
    """Return the checkpoint sealed at end of ``checkpoint_date`` (UTC).

    See module docstring for the response shape and error contract.

    Byte-stability: we serialise via ``json.dumps(..., sort_keys=True,
    separators=(",", ":"))`` and return a raw ``Response`` rather than
    relying on FastAPI's default JSON encoder so two callers asking
    for the same checkpoint get byte-identical bodies. Auditors diff
    the response body against the customer's S3 mirror export.
    """
    day = _parse_iso_date(checkpoint_date)
    org_id = ctx.org_id  # staff path already resolved this via X-Org-Id

    # ── Customer-vs-staff IAM enforcement happens inside
    # require_permission_with_context. Here we just record the staff
    # read (NOT for the customer path — customers reading their own
    # data don't write audit rows).

    cp = await _latest_checkpoint_in_window(
        session, org_id=org_id, day=day
    )

    if cp is None:
        # 409 vs 404. If the day is today and we expect a checkpoint
        # later (cadence sweeper is mid-tick), surface 409 with
        # Retry-After so SDK callers back off cleanly instead of
        # caching a 404 for the rest of the day.
        today = _utc_now().date()
        if day == today:
            if ctx.tier == IamTier.STAFF_READ_ONLY:
                await audit_staff_read(
                    session,
                    staff_id=ctx.staff_id or "",
                    endpoint="/v1/checkpoints/{checkpoint_date}",
                    org_id=org_id,
                    resource_type="checkpoint",
                    resource_id=None,
                    redacted=False,
                )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "checkpoint_pending",
                    "detail": (
                        "Today's checkpoint hasn't been sealed yet. The "
                        "cadence sweeper runs on a configured interval; "
                        "try again shortly."
                    ),
                },
                headers={"Retry-After": "60"},
            )

        if ctx.tier == IamTier.STAFF_READ_ONLY:
            await audit_staff_read(
                session,
                staff_id=ctx.staff_id or "",
                endpoint="/v1/checkpoints/{checkpoint_date}",
                org_id=org_id,
                resource_type="checkpoint",
                resource_id=None,
                redacted=False,
            )
        raise HTTPException(
            status_code=404,
            detail={
                "code": "checkpoint_not_found",
                "detail": (
                    f"No checkpoint sealed on {checkpoint_date} (UTC) "
                    f"for org {org_id}."
                ),
            },
        )

    body = await _build_response_body(
        session, org_id=org_id, checkpoint=cp
    )

    # Wave 3A.c — staff read audit. The body here carries no PHI
    # (chain integrity columns only); we still log the access so the
    # customer dashboard can show "Vera staff accessed checkpoint X on
    # day Y". ``redacted=False`` because the response body has no PHI
    # to redact — flagged so a future STAFF_FULL tier introducing PHI
    # in this endpoint can't pretend the response was redacted.
    if ctx.tier == IamTier.STAFF_READ_ONLY:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/checkpoints/{checkpoint_date}",
            org_id=org_id,
            resource_type="checkpoint",
            resource_id=cp.id,
            redacted=False,
        )

    # Byte-stable JSON. ``sort_keys=True`` matches the canonicalize
    # helper, ``separators=(",", ":")`` strips whitespace. Both ensure
    # the response is reproducible across calls.
    body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return Response(
        content=body_bytes,
        media_type="application/json",
        status_code=200,
    )
