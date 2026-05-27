"""Pre-loaded data the eight section renderers read from.

Build the ``PdfContext`` once at the top of ``generate_audit_pdf`` and
pass it into every section. This keeps the section files free of DB code
and lets us unit-test renderers against synthetic contexts without a
session. It also bounds the number of round-trips: every section reading
the same checkpoint / chain-state would otherwise N+1 those queries.

Performance budget for pilot scale (≤500 records in range): one bounded
fetch per data class. The Approvals list is sliced to a hard cap so a
pathological dataset can't blow the 30 s render budget — over the cap
we render an aggregate count + "first N shown" footnote rather than the
full table. A2 may revisit the cap when the per-decision Merkle proof
attachments land.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from ...models import (
    ActionRecord,
    Approval,
    BAAAgreement,
    BAAScope,
    ChainState,
    Checkpoint,
    Customer,
    CustomerAgent,
    Organization,
)


# Hard cap on the number of full Approval rows loaded into memory for the
# HITL section. Above this cap, we still render the aggregate counts
# (decisions captured, HITL events, reviewer-role breakdown via SQL
# GROUP BY) so the section stays correct — we just don't paginate the
# raw rows into the PDF. Picked at 500 to match the pilot scale called
# out in the PR brief; production scale will revisit once A2 lands.
_APPROVALS_HARD_CAP = 500


def _to_naive_utc(d: date | datetime) -> datetime:
    """Coerce a ``date`` or aware ``datetime`` to naive UTC at 00:00:00.

    DB DateTime columns in this project are tz-naive (matches
    ``services/hashing.py::_normalize``). Compare against tz-naive UTC
    so Postgres + SQLite both behave identically.
    """
    if isinstance(d, datetime):
        if d.tzinfo is not None:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d
    # Plain date → start-of-day UTC.
    return datetime(d.year, d.month, d.day, 0, 0, 0)


@dataclass
class PdfContext:
    """Everything the 8 section renderers need.

    All fields are pre-loaded by :func:`build_context` — section renderers
    are pure functions of the context plus the story list. This makes the
    section code testable without a DB and keeps renderer ordering
    independent of fetch ordering.
    """

    # ── Identity ─────────────────────────────────────────────
    org: Organization
    customer: Customer
    date_from: date
    date_to: date
    generated_at: datetime
    branding: str  # "customer" | "vera-neutral"

    # ── White-label branding (Phase 4 Wave 2 PR A3) ──────────
    # Pre-loaded off the ``Organization`` row in :func:`build_context` so
    # the cover renderer is fully synchronous — no network / DB round
    # trip during ReportLab layout. ``logo_bytes is None`` is the
    # signal for "no logo configured" → the cover renderer falls back
    # to a wordmark of the Customer name. ``accent_color_hex`` carries
    # the ``#RRGGBB`` literal validated at upload time; ``None`` means
    # "use project default".
    logo_bytes: Optional[bytes] = None
    logo_mime: Optional[str] = None
    accent_color_hex: Optional[str] = None

    # ── Counts (aggregates; cheap to compute) ────────────────
    action_record_count: int = 0
    approval_count: int = 0
    hitl_count_by_status: dict[str, int] = field(default_factory=dict)
    reviewer_role_breakdown: dict[str, int] = field(default_factory=dict)
    gate_firings_by_gate_name: dict[str, int] = field(default_factory=dict)
    demographic_data_captured: bool = False

    # ── Heavy data (capped) ──────────────────────────────────
    approvals: list[Approval] = field(default_factory=list)
    approvals_truncated_above: Optional[int] = None
    customer_agents: list[CustomerAgent] = field(default_factory=list)

    # ── BAA chain ────────────────────────────────────────────
    baa_agreements: list[BAAAgreement] = field(default_factory=list)
    baa_scopes: list[BAAScope] = field(default_factory=list)

    # ── Chain integrity / Technical appendix ─────────────────
    chain_state: Optional[ChainState] = None
    latest_checkpoint: Optional[Checkpoint] = None

    # ── Workforce training (from Organization.wizard_answers) ──
    workforce_training_attestations: list[dict] = field(default_factory=list)


async def build_context(
    session: AsyncSession,
    *,
    org: Organization,
    customer: Customer,
    date_from: date,
    date_to: date,
    branding: str,
) -> PdfContext:
    """One DB-pass build of everything the renderers need.

    Half-open window semantics: ``[date_from 00:00 UTC, date_to+1 00:00 UTC)``
    so a single-day report (date_from == date_to) covers exactly that
    calendar day.
    """
    window_start = _to_naive_utc(date_from)
    window_end = _to_naive_utc(date_to + timedelta(days=1))
    tenant_id = customer.tenant_id

    # Phase 4 Wave 2 PR A3 — explicitly load ``Organization.logo_bytes``
    # (the column is ``deferred=True`` on the model so generic
    # ``session.get(Organization, ...)`` doesn't pull the up-to-1 MB
    # blob on every dashboard fetch). Async SQLAlchemy raises
    # ``MissingGreenlet`` if a deferred column is accessed without an
    # explicit ``await`` round-trip; the cleanest pattern is to re-fetch
    # the row with ``undefer`` so the bytes are materialised before
    # ``_render_to_bytes`` runs inside ``asyncio.to_thread``.
    logo_row = await session.execute(
        select(Organization)
        .where(Organization.id == org.id)
        .options(undefer(Organization.logo_bytes))
    )
    org_with_logo = logo_row.scalar_one_or_none() or org
    # Materialise the bytes here (still inside the async session) so the
    # downstream renderer reads a plain ``bytes`` value, not an ORM
    # attribute that could lazy-load on a thread without greenlet ctx.
    logo_bytes_value = org_with_logo.logo_bytes

    ctx = PdfContext(
        org=org,
        customer=customer,
        date_from=date_from,
        date_to=date_to,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        branding=branding,
        # Pre-loaded above so the cover renderer (inside
        # ``asyncio.to_thread`` → ReportLab layout) never triggers a
        # deferred-column lazy load on a thread without greenlet
        # context.
        logo_bytes=logo_bytes_value,
        logo_mime=org.logo_mime,
        accent_color_hex=org.accent_color_hex,
    )

    # ── ActionRecord count ───────────────────────────────────
    ar_count = await session.execute(
        select(func.count(ActionRecord.id)).where(
            ActionRecord.org_id == org.id,
            ActionRecord.tenant_id == tenant_id,
            ActionRecord.recorded_at >= window_start,
            ActionRecord.recorded_at < window_end,
        )
    )
    ctx.action_record_count = int(ar_count.scalar_one() or 0)

    # ── Approvals (aggregate + capped rows) ──────────────────
    # The status breakdown is cheap (one GROUP BY); the row pull is
    # capped so a pathological dataset stays inside the 30 s render
    # budget. Approval is org-scoped — we filter by the request_record
    # join to scope to this Customer.
    approvals_subquery = (
        select(Approval)
        .join(
            ActionRecord,
            Approval.request_record_id == ActionRecord.id,
            isouter=False,
        )
        .where(
            Approval.org_id == org.id,
            ActionRecord.tenant_id == tenant_id,
            Approval.requested_at >= window_start,
            Approval.requested_at < window_end,
        )
    )

    # Status breakdown (no cap — pure aggregate).
    status_rows = await session.execute(
        select(Approval.status, func.count(Approval.id))
        .join(
            ActionRecord,
            Approval.request_record_id == ActionRecord.id,
            isouter=False,
        )
        .where(
            Approval.org_id == org.id,
            ActionRecord.tenant_id == tenant_id,
            Approval.requested_at >= window_start,
            Approval.requested_at < window_end,
        )
        .group_by(Approval.status)
    )
    for status, cnt in status_rows.all():
        ctx.hitl_count_by_status[str(status)] = int(cnt)
    ctx.approval_count = sum(ctx.hitl_count_by_status.values())

    # Capped row pull for the table.
    approval_rows = await session.execute(
        approvals_subquery.order_by(Approval.requested_at.asc()).limit(
            _APPROVALS_HARD_CAP + 1
        )
    )
    rows = list(approval_rows.scalars().all())
    if len(rows) > _APPROVALS_HARD_CAP:
        ctx.approvals_truncated_above = _APPROVALS_HARD_CAP
        ctx.approvals = rows[:_APPROVALS_HARD_CAP]
    else:
        ctx.approvals = rows

    # Reviewer-role + gate-name breakdown — pulled from Approval.context
    # (the HITL materialiser stashes gate metadata there). Cheap Python
    # loop over the already-loaded rows; no extra DB hit.
    for ap in ctx.approvals:
        gate_meta = ap.context if isinstance(ap.context, dict) else {}
        role = gate_meta.get("required_role") or "unspecified"
        ctx.reviewer_role_breakdown[role] = (
            ctx.reviewer_role_breakdown.get(role, 0) + 1
        )
        gate_name = gate_meta.get("gate_name") or "unknown"
        ctx.gate_firings_by_gate_name[gate_name] = (
            ctx.gate_firings_by_gate_name.get(gate_name, 0) + 1
        )
        # Demographic data capture flag — section 1557 monitoring. The
        # gate materialiser sets ``demographic_fields_present`` when the
        # action had any of the 1557-relevant fields (age, sex, race,
        # ethnicity). Falling back to checking gate_name keeps us honest
        # for ranks that haven't been re-tagged yet.
        if gate_meta.get("demographic_fields_present"):
            ctx.demographic_data_captured = True
        if "demographic" in str(gate_name).lower():
            ctx.demographic_data_captured = True

    # ── CustomerAgent rows (cheap; A2 expands into Coverage Matrix) ──
    ca_rows = await session.execute(
        select(CustomerAgent)
        .where(CustomerAgent.customer_id == customer.id)
        .order_by(CustomerAgent.last_seen_at.desc().nullslast())
    )
    ctx.customer_agents = list(ca_rows.scalars().all())

    # ── BAA chain (agreements + scopes for this Customer) ──────
    baa_rows = await session.execute(
        select(BAAAgreement)
        .where(BAAAgreement.customer_id == customer.id)
        .order_by(BAAAgreement.created_at.desc())
    )
    ctx.baa_agreements = list(baa_rows.scalars().all())

    if ctx.baa_agreements:
        baa_ids = [b.id for b in ctx.baa_agreements]
        scope_rows = await session.execute(
            select(BAAScope)
            .where(BAAScope.baa_agreement_id.in_(baa_ids))
            .order_by(BAAScope.granted_at.desc())
        )
        ctx.baa_scopes = list(scope_rows.scalars().all())

    # ── Chain state + latest checkpoint ──────────────────────
    ctx.chain_state = await session.get(ChainState, org.id)
    cp_row = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.org_id == org.id)
        .order_by(
            Checkpoint.sequence_at_checkpoint.desc(),
            Checkpoint.created_at.desc(),
        )
        .limit(1)
    )
    ctx.latest_checkpoint = cp_row.scalars().first()

    # ── Workforce training attestations (from org wizard_answers) ──
    # Phase 1 PR 14 wired ``wizard_answers`` JSON; PR 14 contracted to
    # store workforce training attestations under
    # ``wizard_answers.workforce_training_attestations`` (list of dicts).
    # If the field isn't populated, we render the "none recorded"
    # placeholder.
    if org.wizard_answers and isinstance(org.wizard_answers, dict):
        attestations = org.wizard_answers.get("workforce_training_attestations")
        if isinstance(attestations, list):
            ctx.workforce_training_attestations = attestations

    return ctx


# Re-export for tests that want to monkeypatch the cap.
APPROVALS_HARD_CAP = _APPROVALS_HARD_CAP
