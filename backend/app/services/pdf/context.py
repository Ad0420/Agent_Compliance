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

import logging
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
from ..merkle_proof import (
    MerkleProofPayload,
    ProofUnavailable,
    build_proof,
)

logger = logging.getLogger("vera.pdf.context")


# Hard cap on the number of full Approval rows loaded into memory for the
# HITL section. Above this cap, we still render the aggregate counts
# (decisions captured, HITL events, reviewer-role breakdown via SQL
# GROUP BY) so the section stays correct — we just don't paginate the
# raw rows into the PDF. Picked at 500 to match the pilot scale called
# out in the PR brief; production scale will revisit once A2 lands.
_APPROVALS_HARD_CAP = 500

# A2: Hard cap on the number of ActionRecords for which we attach a
# Merkle ``proof.json`` to the PDF. 500 matches the pilot scale called
# out in the PR brief; above the cap the route returns
# ``413 too_many_records_for_pdf`` so the worker isn't blown by a single
# pathological date range. Tests can monkey-patch ``RECORDS_HARD_CAP`` to
# exercise the boundary at lower numbers.
_RECORDS_HARD_CAP = 500


# Fallback agent_type label used by ``services.chain`` when an ActionRecord
# has no ``action_class``. Mirrors ``_DEFAULT_AGENT_TYPE`` in that module —
# kept private to avoid coupling the PDF service to chain internals.
_UNCLASSIFIED_AGENT_TYPE = "unclassified"


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
    # The most recent sealed checkpoint whose window overlaps the report
    # date range — used for the Scope-page Merkle reference sentence.
    # ``None`` when no checkpoint has sealed any record in the range yet.
    checkpoint_for_range: Optional[Checkpoint] = None

    # ── Workforce training (from Organization.wizard_answers) ──
    workforce_training_attestations: list[dict] = field(default_factory=list)

    # ── A2: Coverage Matrix ──────────────────────────────────
    # One row per CustomerAgent (auto-discovered or declared). Each row
    # captures the per-agent_type coverage signals the Scope page renders
    # as a table + the blunt scope sentence underneath. Pre-computed in
    # ``build_context`` so renderers stay pure-function over the context.
    coverage_matrix: list[dict] = field(default_factory=list)

    # ── A2: Per-decision Merkle proof attachments ────────────
    # Tuples of ``(filename, proof_payload_dict)``. ``filename`` follows
    # the ``proof-<record_id_short_hash>.json`` convention. The
    # generator post-processes the rendered PDF and attaches each entry
    # as an embedded file the regulator can extract from Acrobat /
    # Preview. Records in the still-pending checkpoint window are NOT
    # added here — their record IDs go into ``pending_proof_record_ids``
    # below so the technical appendix can call them out honestly.
    merkle_attachments: list[tuple[str, dict]] = field(default_factory=list)
    pending_proof_record_ids: list[str] = field(default_factory=list)


class TooManyRecordsForPdf(Exception):
    """Raised when the # of ActionRecords in range exceeds the PDF cap.

    The route maps this to ``HTTP 413 too_many_records_for_pdf``. The cap
    is per-PDF so a single pathological date range can't blow the worker
    by demanding 50,000 Merkle proofs at once.
    """

    def __init__(self, *, record_count: int, cap: int) -> None:
        super().__init__(
            f"PDF would attach {record_count} Merkle proofs (cap: {cap})"
        )
        self.record_count = record_count
        self.cap = cap


def _normalize_agent_type(value: Optional[str]) -> str:
    """Mirror ``services.chain``'s agent_type normalisation.

    Used to map an ``ActionRecord.action_class`` to the same
    ``CustomerAgent.agent_type`` value that auto-discovery would have
    stamped at insert time. Keeping the rule in one place here means a
    future change to the chain-side normalisation only has to be
    propagated to one helper.
    """
    if not value:
        return _UNCLASSIFIED_AGENT_TYPE
    norm = value.strip().lower()
    return norm or _UNCLASSIFIED_AGENT_TYPE


async def build_context(
    session: AsyncSession,
    *,
    org: Organization,
    customer: Customer,
    date_from: date,
    date_to: date,
    branding: str,
    records_hard_cap: Optional[int] = None,
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

    # ── A2: Coverage Matrix + Merkle proof attachments ──────────────
    # The Coverage Matrix is per-agent_type. The simplest honest
    # mapping today is ``ActionRecord.action_class`` → normalised
    # ``agent_type`` — the exact same rule auto-discovery uses at insert
    # time (``services.chain._upsert_customer_and_agent``). Pulling the
    # in-range action classes for this Customer lets us mark each
    # CustomerAgent row as "captured in this window" / "detected but
    # silent in this window".
    cap = records_hard_cap if records_hard_cap is not None else _RECORDS_HARD_CAP
    await _populate_coverage_and_proofs(
        session,
        ctx,
        window_start=window_start,
        window_end=window_end,
        records_hard_cap=cap,
    )

    return ctx


async def _populate_coverage_and_proofs(
    session: AsyncSession,
    ctx: PdfContext,
    *,
    window_start: datetime,
    window_end: datetime,
    records_hard_cap: int,
) -> None:
    """Fill ``coverage_matrix`` + ``merkle_attachments`` on ``ctx``.

    Split out of ``build_context`` so the SQL is contained — the
    function does three things:

      1. Pull the in-range ``ActionRecord.action_class`` distribution
         (one ``GROUP BY``) so each CustomerAgent row knows whether any
         of its actions appeared in the window.
      2. Pull the in-range ``Approval.context["gate_name"]`` ↔
         requesting record's ``action_class`` mapping so each
         CustomerAgent knows which gates fired against it.
      3. Pull every in-range ActionRecord (up to the cap), build the
         Merkle proof for each one, and stage attachments.

    Why combine: the Coverage Matrix row's "PDF included" / "Posture
    included" columns both branch on whether any in-range
    ActionRecord exists for the agent_type, so we already need the
    capture map.
    """
    org_id = ctx.org.id
    tenant_id = ctx.customer.tenant_id

    # ── Step 1: in-range capture by action_class ─────────────────
    capture_rows = await session.execute(
        select(
            ActionRecord.action_class,
            func.count(ActionRecord.id),
        )
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id == tenant_id,
            ActionRecord.recorded_at >= window_start,
            ActionRecord.recorded_at < window_end,
        )
        .group_by(ActionRecord.action_class)
    )
    captured_count_by_agent_type: dict[str, int] = {}
    for action_class, cnt in capture_rows.all():
        at = _normalize_agent_type(action_class)
        captured_count_by_agent_type[at] = (
            captured_count_by_agent_type.get(at, 0) + int(cnt)
        )

    # ── Step 2: HITL gates per agent_type ────────────────────────
    # Approval already loaded in ctx.approvals (capped). For each
    # approval, look at its ``context["gate_name"]`` and resolve the
    # agent_type via the requesting record's action_class. Approvals
    # whose request_record_id is missing or unresolvable are tallied
    # under ``_UNCLASSIFIED_AGENT_TYPE`` — same convention as chain.py.
    request_record_ids = [
        ap.request_record_id for ap in ctx.approvals if ap.request_record_id
    ]
    action_class_by_record_id: dict[str, Optional[str]] = {}
    if request_record_ids:
        rec_rows = await session.execute(
            select(ActionRecord.id, ActionRecord.action_class).where(
                ActionRecord.id.in_(request_record_ids)
            )
        )
        for rid, ac in rec_rows.all():
            action_class_by_record_id[rid] = ac

    gates_by_agent_type: dict[str, set[str]] = {}
    for ap in ctx.approvals:
        action_class = action_class_by_record_id.get(ap.request_record_id or "")
        agent_type = _normalize_agent_type(action_class)
        gate_meta = ap.context if isinstance(ap.context, dict) else {}
        gate_name = gate_meta.get("gate_name")
        if not gate_name:
            continue
        gates_by_agent_type.setdefault(agent_type, set()).add(str(gate_name))

    # ── Step 3: assemble Coverage Matrix ─────────────────────────
    # One row per CustomerAgent. Sort by agent_type for stable output.
    sorted_agents = sorted(ctx.customer_agents, key=lambda a: a.agent_type or "")
    for ca in sorted_agents:
        at = (ca.agent_type or "").strip().lower() or _UNCLASSIFIED_AGENT_TYPE
        captured = captured_count_by_agent_type.get(at, 0)
        is_covered = captured > 0
        gates = sorted(gates_by_agent_type.get(at, set()))
        ctx.coverage_matrix.append(
            {
                "agent_type": at,
                "detected": True,
                "covered": is_covered,
                "captured_count": captured,
                "hitl_gates": gates,
                # v1: per-agent section toggles don't exist yet, so every
                # detected agent is included in the PDF when this PDF is
                # rendered. A2 brief: "v1: always ✓ since per-agent
                # section toggles don't exist yet — render ✓".
                "pdf_included": True,
                # Posture-included iff this agent contributed any
                # decision in the window. Approvals are the closest
                # proxy today (gates are how posture rolls up).
                "posture_included": is_covered,
            }
        )

    # ── Step 4: select the checkpoint backing the date range ─────
    # Used by the Scope page's "verify against checkpoint root <hash>"
    # sentence. The right checkpoint is "the latest one that sealed at
    # least one record in this report window" — i.e. its
    # ``sequence_at_checkpoint`` is ≥ the smallest in-range record's
    # ``sequence_number``. This is a tighter rule than "checkpoint
    # created in the window" (which would miss a checkpoint sealed
    # shortly AFTER the window closes that covers in-range records).
    min_seq_row = await session.execute(
        select(func.min(ActionRecord.sequence_number)).where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id == tenant_id,
            ActionRecord.recorded_at >= window_start,
            ActionRecord.recorded_at < window_end,
        )
    )
    min_seq_in_range = min_seq_row.scalar_one_or_none()
    if min_seq_in_range is not None:
        cp_in_range_row = await session.execute(
            select(Checkpoint)
            .where(
                Checkpoint.org_id == org_id,
                Checkpoint.sequence_at_checkpoint >= min_seq_in_range,
            )
            .order_by(Checkpoint.sequence_at_checkpoint.desc())
            .limit(1)
        )
        ctx.checkpoint_for_range = cp_in_range_row.scalars().first()

    # ── Step 5: pull in-range records + build proofs ─────────────
    # Reuse ``action_record_count`` (computed earlier with COUNT(*)) for
    # the cap check: it gives the honest total instead of "cap+1" so the
    # 413 response can tell the caller exactly how many records are in
    # range. This also lets us bail BEFORE pulling any row payloads —
    # the SELECT below is bounded by the cap, never the true count.
    if ctx.action_record_count > records_hard_cap:
        raise TooManyRecordsForPdf(
            record_count=ctx.action_record_count, cap=records_hard_cap
        )

    record_rows = await session.execute(
        select(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id == tenant_id,
            ActionRecord.recorded_at >= window_start,
            ActionRecord.recorded_at < window_end,
        )
        .order_by(ActionRecord.sequence_number.asc())
        .limit(records_hard_cap)
    )
    records: list[ActionRecord] = list(record_rows.scalars().all())

    # Build proofs one-by-one. Each ``build_proof`` is a few SQL roundtrips
    # but the work is bounded by the cap. Records in the still-pending
    # window raise ``ProofUnavailable("checkpoint_pending")`` — we skip
    # the attachment and record the id for the technical appendix.
    for record in records:
        try:
            payload: MerkleProofPayload = await build_proof(
                session, record=record
            )
        except ProofUnavailable as exc:
            if exc.code == "checkpoint_pending":
                ctx.pending_proof_record_ids.append(record.id)
                continue
            # Anything else is a data-integrity failure (e.g. proof root
            # mismatch). Log loudly and skip — we'd rather ship the PDF
            # with one missing attachment than crash the whole render.
            logger.warning(
                "merkle proof unavailable record_id=%s code=%s — "
                "skipping attachment",
                record.id,
                exc.code,
            )
            continue
        short = record.id.replace("-", "")[:12]
        filename = f"proof-{short}.json"
        ctx.merkle_attachments.append((filename, payload.to_dict()))


# Re-export for tests that want to monkeypatch the cap.
APPROVALS_HARD_CAP = _APPROVALS_HARD_CAP
RECORDS_HARD_CAP = _RECORDS_HARD_CAP
