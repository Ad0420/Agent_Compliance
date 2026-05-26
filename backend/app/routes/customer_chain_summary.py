"""``GET /v1/customers/{tenant_id}/chain-summary`` — Wave 3D.2.

Feeds the Customer detail page's "Verification & Evidence Trail" panel.

Returned shape::

    {
      "tenant_id": "cleveland_clinic",
      "customer_display_name": "Cleveland Clinic",
      "latest_checkpoint": {
        "checkpoint_id": "...",
        "merkle_root": "...",
        "signed_at": "2026-05-25T20:00:00.000",
        "kms_key_id": "...",
        "kms_algorithm": "hmac-sha256",
        "kms_public_key_pem": null,
        "customer_record_count": 847,
        "total_record_count": 1842,
        "sequence_at_checkpoint": 7234
      } | null,
      "timeline": [
        { "date": "2026-04-26", "status": "sealed"|"none"|"pending",
          "checkpoint_id": "...", "customer_record_count": 12 },
        ...
      ],
      "verification_supported": true|false,
      "verification_unsupported_reason": null|"hmac_symmetric_no_shared_secret"
    }

The 30-day timeline is the last 30 calendar days inclusive of today. Each
day's tile shows the latest checkpoint sealed on that day (matches
``GET /v1/checkpoints/{date}`` semantics) plus a count of how many
records belonging to *this customer* fell in that checkpoint's window.

The panel uses ``customer_record_count`` for messaging ("847 records
from cleveland_clinic in chk-7f4a..."). ``total_record_count`` is
returned alongside so the dashboard can show "847 of 1,842 records in
this checkpoint belong to this customer" without N+1 calls to
``/v1/checkpoints/{date}``.

IAM: customer-tier reads only their own org; staff-tier passes
``X-Org-Id`` and writes a ``staff_audit_log`` row. Mirrors the pattern
from ``checkpoints_by_date.py``.

Note on ``verification_supported``: the dashboard's in-browser verifier
uses Web Crypto API. Asymmetric keys (RSA/ECDSA) can be verified in
the browser given the public PEM; HMAC-SHA256 (the local-dev key
type and the AWS KMS HMAC mode) requires the shared secret, which
must never live in the browser. We surface this distinction here so
the panel can grey out the "Verify" button with an honest reason
rather than failing silently or shipping the secret.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ActionRecord, Checkpoint, Customer, Organization
from ..services.auth import AuthContext, require_permission_with_context
from ..services.evidence_export import (
    build_evidence_bundle_tar_gz,
    bundle_filename,
    summarize_evidence_bundle,
)
from ..services.iam import audit_staff_read
from ..services.kms import ALGO_HMAC_SHA256, get_key_by_id

logger = logging.getLogger("vera.customer_chain_summary")

# Last 30 calendar days INCLUSIVE of today → 30 tiles. Matches the brief
# ("30-day timeline … each day a small tile"). The window slides; the
# dashboard never asks for "May 2026" — only "the last 30 days".
TIMELINE_DAYS = 30


router = APIRouter(prefix="/customers", tags=["customers"])


# ── Internal data shapes ─────────────────────────────────────────────


@dataclass
class _TimelineDay:
    """One tile on the 30-day strip."""

    date: str
    status: str  # 'sealed' | 'none' | 'pending'
    checkpoint_id: Optional[str]
    customer_record_count: int


# ── Helpers ──────────────────────────────────────────────────────────


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_iso_ms(ts: datetime) -> str:
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    ts = ts.replace(microsecond=(ts.microsecond // 1000) * 1000)
    return ts.isoformat(timespec="milliseconds")


async def _resolve_customer_or_404(
    session: AsyncSession, *, org_id: str, tenant_id: str
) -> Customer:
    """Org-scoped customer lookup with cross-org-safe 404."""
    result = await session.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        # 404 (not 403) on cross-org — same convention as the rest of
        # the customer routes. Confirming existence would be a side
        # channel.
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


async def _latest_checkpoint(
    session: AsyncSession, *, org_id: str
) -> Optional[Checkpoint]:
    """Most recent sealed checkpoint for ``org_id``, or ``None``."""
    q = (
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(
            Checkpoint.sequence_at_checkpoint.desc(),
            Checkpoint.created_at.desc(),
        )
        .limit(1)
    )
    return (await session.execute(q)).scalars().first()


async def _previous_seq(
    session: AsyncSession, *, org_id: str, this_seq: int
) -> int:
    """Sequence-at-checkpoint of the immediately-prior checkpoint, or 0."""
    q = (
        select(Checkpoint.sequence_at_checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint < this_seq,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    val = (await session.execute(q)).scalar_one_or_none()
    return int(val) if val is not None else 0


async def _record_counts_in_window(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_id: str,
    prior_seq: int,
    this_seq: int,
) -> tuple[int, int]:
    """Return ``(customer_count, total_count)`` for the half-open window
    ``(prior_seq, this_seq]``.

    Two queries because filtering by ``tenant_id`` and not filtering form
    different aggregates; doing it in one query with a GROUP BY would be
    more brittle than the cost saved. The ``idx_ar_org_tenant_seq``
    composite index covers the customer-filtered count cheaply.
    """
    customer_q = select(func.count(ActionRecord.id)).where(
        ActionRecord.org_id == org_id,
        ActionRecord.tenant_id == tenant_id,
        ActionRecord.sequence_number > prior_seq,
        ActionRecord.sequence_number <= this_seq,
    )
    total_q = select(func.count(ActionRecord.id)).where(
        ActionRecord.org_id == org_id,
        ActionRecord.sequence_number > prior_seq,
        ActionRecord.sequence_number <= this_seq,
    )
    customer_count = int((await session.execute(customer_q)).scalar_one() or 0)
    total_count = int((await session.execute(total_q)).scalar_one() or 0)
    return customer_count, total_count


async def _checkpoints_in_window(
    session: AsyncSession,
    *,
    org_id: str,
    start: datetime,
    end: datetime,
) -> list[Checkpoint]:
    """All checkpoints sealed in ``[start, end)`` ordered by created_at."""
    q = (
        select(Checkpoint)
        .where(
            and_(
                Checkpoint.org_id == org_id,
                Checkpoint.created_at >= start,
                Checkpoint.created_at < end,
            )
        )
        .order_by(Checkpoint.created_at.asc())
    )
    return list((await session.execute(q)).scalars().all())


async def _build_timeline(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_id: str,
    today: date_cls,
    cadence: str,
) -> list[_TimelineDay]:
    """Build the 30-day timeline strip.

    For each calendar day in the window we report the *latest* checkpoint
    sealed that day (matching ``GET /v1/checkpoints/{date}`` semantics)
    and how many records belonging to this tenant fell in that
    checkpoint's window. Days with no checkpoint show ``status='none'``,
    except for today which shows ``status='pending'`` when the org's
    cadence is configured (daily/hourly) — same UX hint the
    by-date endpoint gives via 409.
    """
    start_day = today - timedelta(days=TIMELINE_DAYS - 1)
    window_start = datetime.combine(start_day, datetime.min.time())
    window_end = datetime.combine(today + timedelta(days=1), datetime.min.time())

    checkpoints = await _checkpoints_in_window(
        session, org_id=org_id, start=window_start, end=window_end
    )

    # Group checkpoints by calendar day; for ties (multiple checkpoints in
    # the same day) keep the LATEST one — same tiebreaker the by-date
    # endpoint uses.
    by_day: dict[date_cls, Checkpoint] = {}
    for cp in checkpoints:
        d = cp.created_at.date()
        existing = by_day.get(d)
        if (
            existing is None
            or cp.sequence_at_checkpoint > existing.sequence_at_checkpoint
        ):
            by_day[d] = cp

    timeline: list[_TimelineDay] = []
    cadence_active = cadence in ("daily", "hourly")
    for i in range(TIMELINE_DAYS):
        d = start_day + timedelta(days=i)
        cp = by_day.get(d)
        if cp is not None:
            prior = await _previous_seq(
                session,
                org_id=org_id,
                this_seq=cp.sequence_at_checkpoint,
            )
            customer_count, _ = await _record_counts_in_window(
                session,
                org_id=org_id,
                tenant_id=tenant_id,
                prior_seq=prior,
                this_seq=cp.sequence_at_checkpoint,
            )
            timeline.append(
                _TimelineDay(
                    date=d.isoformat(),
                    status="sealed",
                    checkpoint_id=cp.id,
                    customer_record_count=customer_count,
                )
            )
        else:
            # Today with cadence configured but no checkpoint sealed yet
            # → pending. Past days with no checkpoint and cadence
            # configured → still a real gap (the operator should
            # investigate); we surface those as 'none' so the visual is
            # honest and the dashboard's "gap detected" surface can pick
            # it up.
            status = "pending" if (d == today and cadence_active) else "none"
            timeline.append(
                _TimelineDay(
                    date=d.isoformat(),
                    status=status,
                    checkpoint_id=None,
                    customer_record_count=0,
                )
            )
    return timeline


# ── Route ────────────────────────────────────────────────────────────


@router.get("/{tenant_id}/chain-summary")
async def get_customer_chain_summary(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
) -> dict:
    """Return latest-checkpoint summary + 30-day timeline for this customer.

    Customer-tier sees their own org only. Staff-tier passes
    ``X-Org-Id`` and writes a ``staff_audit_log`` row.
    """
    org_id = ctx.org_id

    customer = await _resolve_customer_or_404(
        session, org_id=org_id, tenant_id=tenant_id
    )

    # Org cadence drives the "pending today" semantic. Default to
    # ``daily`` when the column is NULL (shouldn't happen post-3A.b but
    # the schema allows it).
    org = await session.get(Organization, org_id)
    cadence = (
        org.checkpoint_cadence
        if org is not None and org.checkpoint_cadence
        else "daily"
    )

    latest = await _latest_checkpoint(session, org_id=org_id)
    latest_payload: Optional[dict] = None
    verification_supported = False
    unsupported_reason: Optional[str] = None

    if latest is not None:
        prior = await _previous_seq(
            session,
            org_id=org_id,
            this_seq=latest.sequence_at_checkpoint,
        )
        customer_count, total_count = await _record_counts_in_window(
            session,
            org_id=org_id,
            tenant_id=tenant_id,
            prior_seq=prior,
            this_seq=latest.sequence_at_checkpoint,
        )

        kms_algorithm = ""
        kms_public_key_pem: Optional[str] = None
        if latest.key_id:
            history = await get_key_by_id(session, latest.key_id)
            if history is not None:
                kms_algorithm = history.algorithm
                kms_public_key_pem = history.public_key_pem

        # Asymmetric → in-browser verification is supported via Web
        # Crypto API ``crypto.subtle.verify``. HMAC → not supported in
        # the browser; the shared secret cannot ship to the client and
        # the dashboard greys out the inline Verify button with a
        # documented reason. Both still produce a valid evidence bundle
        # downloadable from this surface; the CLI verifier on the
        # customer's side can verify HMAC via the shared secret it
        # already holds.
        if kms_algorithm and kms_algorithm != ALGO_HMAC_SHA256 and kms_public_key_pem:
            verification_supported = True
        else:
            unsupported_reason = "hmac_symmetric_no_shared_secret"

        latest_payload = {
            "checkpoint_id": latest.id,
            "merkle_root": latest.merkle_root,
            "signed_at": _format_iso_ms(latest.created_at),
            "kms_key_id": latest.key_id,
            "kms_algorithm": kms_algorithm or None,
            "kms_public_key_pem": kms_public_key_pem,
            "customer_record_count": customer_count,
            "total_record_count": total_count,
            "sequence_at_checkpoint": latest.sequence_at_checkpoint,
        }

    today = _naive_utc_now().date()
    timeline = await _build_timeline(
        session,
        org_id=org_id,
        tenant_id=tenant_id,
        today=today,
        cadence=cadence,
    )

    # Staff-tier audit. The body here is chain-integrity + aggregate
    # counts — no PHI fields. ``redacted=False`` because there's
    # nothing to redact.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/customers/{tenant_id}/chain-summary",
            org_id=org_id,
            resource_type="customer_chain_summary",
            resource_id=tenant_id,
            redacted=False,
        )

    return {
        "tenant_id": customer.tenant_id,
        "customer_display_name": customer.display_name,
        "latest_checkpoint": latest_payload,
        "timeline": [
            {
                "date": t.date,
                "status": t.status,
                "checkpoint_id": t.checkpoint_id,
                "customer_record_count": t.customer_record_count,
            }
            for t in timeline
        ],
        "verification_supported": verification_supported,
        "verification_unsupported_reason": unsupported_reason,
    }


# ── Evidence bundle export ───────────────────────────────────────────


class EvidenceExportRequest(BaseModel):
    """Body for ``POST /v1/customers/{tenant_id}/evidence-export``.

    ``start_date`` / ``end_date`` are inclusive calendar dates (UTC).
    The default range covers the trailing 90 days — matches the
    dashboard modal's default. ``preview=true`` returns the summary
    JSON only (counts + warnings) without materialising the archive
    bytes; the modal calls this first to show the customer how many
    records will be in the bundle before they commit to the download.
    """

    start_date: Optional[date_cls] = Field(
        default=None,
        description=(
            "Inclusive UTC calendar date. Defaults to 90 days before today."
        ),
    )
    end_date: Optional[date_cls] = Field(
        default=None,
        description="Inclusive UTC calendar date. Defaults to today.",
    )
    preview: bool = Field(
        default=False,
        description=(
            "When true, returns summary JSON only (counts + warnings) "
            "without building the archive. The dashboard's confirmation "
            "modal uses this to show the customer what they're about to "
            "download."
        ),
    )


def _resolve_range(
    body: EvidenceExportRequest,
) -> tuple[datetime, datetime]:
    """Resolve the request's date range to a half-open [start, end) UTC
    window of naive datetimes (matching the DB DateTime columns).

    Defaults: end=today (inclusive), start=end-90d.
    """
    today = _naive_utc_now().date()
    end_day = body.end_date or today
    if body.start_date is not None:
        start_day = body.start_date
    else:
        start_day = end_day - timedelta(days=89)  # 90 inclusive days

    if start_day > end_day:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "detail": "start_date must be on or before end_date.",
            },
        )

    start = datetime.combine(start_day, datetime.min.time())
    end = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
    return start, end


@router.post("/{tenant_id}/evidence-export")
async def export_customer_evidence(
    tenant_id: str,
    body: EvidenceExportRequest,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
):
    """Build (or preview) the customer-scoped evidence bundle.

    When ``preview=true`` → returns ``{customer_record_count,
    checkpoint_count, warnings, ...}`` so the modal can render the
    selective-disclosure preview ("This export will contain X,XXX
    records belonging only to {customer_name}.") before the actual
    download.

    When ``preview=false`` → returns the ``.tar.gz`` bytes with
    ``Content-Type: application/gzip`` and a
    ``Content-Disposition: attachment`` header carrying the
    suggested filename.

    Staff-tier:
      Allowed. The bundle is chain-integrity material; canonical record
      JSON does include the same PHI fields the proof endpoint refuses
      to serve to staff. We therefore audit-log the export at the
      ``redacted=False`` level (staff are reading PHI). This matches the
      pattern from ``checkpoints_by_date`` (chain integrity is staff-
      readable) while flagging the access to the customer's
      "who-read-my-data" surface.

      One difference from ``GET /v1/records/{id}/merkle-proof``: the
      single-record proof endpoint *refuses* staff reads outright
      because the brief reserves it for the customer's own credentials.
      The bundle endpoint is the staff-and-customer evidence-handoff
      surface — it can be downloaded by a Vera engineer responding to a
      regulator request alongside the customer, with the audit row
      written so the customer sees the access. If we ever need to
      tighten this, we can flip the staff branch to a 403 like
      ``records.py`` does; for v1 the audit trail is the answer.
    """
    org_id = ctx.org_id
    customer = await _resolve_customer_or_404(
        session, org_id=org_id, tenant_id=tenant_id
    )
    org = await session.get(Organization, org_id)
    if org is None:
        # Shouldn't happen — the auth context already resolved org_id —
        # but defending against this saves a stack trace later.
        raise HTTPException(status_code=404, detail="Organization not found")

    start, end = _resolve_range(body)

    if body.preview:
        summary = await summarize_evidence_bundle(
            session, customer=customer, start=start, end=end
        )
        if ctx.is_staff:
            await audit_staff_read(
                session,
                staff_id=ctx.staff_id or "",
                endpoint="/v1/customers/{tenant_id}/evidence-export?preview=1",
                org_id=org_id,
                resource_type="customer_evidence_bundle_preview",
                resource_id=tenant_id,
                redacted=False,
            )
        return {
            "tenant_id": summary.tenant_id,
            "customer_display_name": summary.customer_display_name,
            "customer_record_count": summary.customer_record_count,
            "checkpoint_count": summary.checkpoint_count,
            "warnings": summary.warnings,
            "date_range": {
                "start": start.date().isoformat(),
                "end": (end - timedelta(microseconds=1)).date().isoformat(),
            },
        }

    archive_bytes, summary = await build_evidence_bundle_tar_gz(
        session, customer=customer, org=org, start=start, end=end
    )

    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/customers/{tenant_id}/evidence-export",
            org_id=org_id,
            resource_type="customer_evidence_bundle",
            resource_id=tenant_id,
            resource_count=summary.customer_record_count,
            redacted=False,
        )

    filename = bundle_filename(customer.tenant_id, start, end)
    return Response(
        content=archive_bytes,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Vera-Customer-Record-Count": str(summary.customer_record_count),
            "X-Vera-Checkpoint-Count": str(summary.checkpoint_count),
        },
    )
