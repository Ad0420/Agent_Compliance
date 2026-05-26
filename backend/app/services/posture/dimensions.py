"""Per-dimension posture math (Phase 4 Wave 1 PR B1).

One pure async function per dimension. Each returns a
:class:`DimensionResult` carrying everything the response-layer needs
to render either a ``MeasuredDimension`` or a
``NotYetEligibleDimension`` — the response serialisation lives in
``compute.py``.

Voice rules (project-wide; see CLAUDE.md):
    * "Customer" not "Tenant" / "Hospital"
    * Comma separators on numbers (12,500 not 12500)
    * Full dates with year ("Mar 15, 2026" not "Mar 15")

These rules apply to ``measured_fact_line`` and ``reason`` strings that
ultimately appear on the dashboard. Keep them short — the dashboard
renders them in a tight tile.

Low-volume thresholds
---------------------
We diverge slightly from ``policy-engine-mvp.md`` defaults to match
the brief's "low-volume guard" table:

    * Artifact freshness: dimension is ``not_yet_eligible`` until at
      least one BAA is signed (threshold=1). ``compute_artifact_freshness``
      returns "not yet eligible" with needed=1 for orgs with zero BAAs.
    * HITL completion: ≥10 HITL-triggering decisions in window.
    * Reviewer integrity: ≥10 reviewed approvals in window.
    * Notice delivery rate: ≥10 webhook delivery attempts in window.
    * Chain integrity: always eligible; binary 100/0 from the existing
      chain-integrity aggregator.
    * Workflow timeliness: ≥10 decided approvals in window.

Workflow SLA
------------
The default SLA is 4h (decided_at - requested_at). We compute
``pct_within_sla`` rather than p95 because the dashboard renders the
pct number directly; the p95 value is a follow-up enhancement that
doesn't change the response shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, BAAAgreement, WebhookDeliveryAttempt
from ..chain_integrity import compute_chain_integrity
from ..reviewer_roles import is_role_sufficient


# ── Thresholds + tunables ──────────────────────────────────────────

THRESHOLD_ARTIFACT_FRESHNESS = 1
THRESHOLD_HITL_COMPLETION = 10
THRESHOLD_REVIEWER_INTEGRITY = 10
THRESHOLD_NOTICE_DELIVERY_RATE = 10
THRESHOLD_WORKFLOW_TIMELINESS = 10

# Default workflow SLA — 4h between requested_at and decided_at. Per
# the brief, this is org-configurable in a future PR; we hold to the
# default here and keep the parameter name on the signature so
# ``compute.py`` can pass it through once the org column lands.
DEFAULT_WORKFLOW_SLA_HOURS = 4

# How recently a BAA's signed_at must land to count as "fresh". One
# year is the canonical artifact-refresh cadence we coach customers
# on. Older signatures stay valid but the dimension surfaces an
# "older than 1y" treatment in the fact line.
ARTIFACT_FRESHNESS_RECENT_DAYS = 365


# ── Result shape ───────────────────────────────────────────────────


@dataclass(frozen=True)
class DimensionResult:
    """Carrier for the dimension math output.

    Either ``score`` is set (measured) or ``current`` + ``threshold``
    are set (not yet eligible). ``compute.py`` decides which branch
    by checking ``score is not None``.
    """

    name: str
    # Measured path:
    score: Optional[int]  # 0..100
    raw_count: int
    measured_fact_line: str
    # Not-yet-eligible path:
    threshold: int
    current: int
    needed: int
    reason: str


def _comma(n: int) -> str:
    """Render an int with thousands separators per the project copy rules."""
    return f"{n:,}"


def _measured(
    name: str,
    *,
    score: int,
    raw_count: int,
    measured_fact_line: str,
) -> DimensionResult:
    """Build a ``DimensionResult`` in the measured shape."""
    score = max(0, min(100, int(score)))
    return DimensionResult(
        name=name,
        score=score,
        raw_count=raw_count,
        measured_fact_line=measured_fact_line,
        threshold=0,
        current=0,
        needed=0,
        reason="",
    )


def _not_yet_eligible(
    name: str,
    *,
    threshold: int,
    current: int,
    reason: str,
) -> DimensionResult:
    """Build a ``DimensionResult`` in the not-yet-eligible shape."""
    needed = max(0, threshold - current)
    return DimensionResult(
        name=name,
        score=None,
        raw_count=current,
        measured_fact_line="",
        threshold=threshold,
        current=current,
        needed=needed,
        reason=reason,
    )


# ── Window helpers ─────────────────────────────────────────────────


def _utc_now_naive() -> datetime:
    """Naive UTC ``now`` — matches the DateTime columns in the schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _window_start(window_days: int) -> datetime:
    """Inclusive lower bound for the rolling window."""
    return _utc_now_naive() - timedelta(days=window_days)


# ── 1. Artifact freshness ──────────────────────────────────────────


async def compute_artifact_freshness(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
) -> DimensionResult:
    """Score = % of recent BAAs signed within the freshness window.

    The minimum threshold is one *signed* BAA. Below that, the
    dimension is not yet eligible with ``needed=1`` so the dashboard
    can render "Upload a BAA to unlock this dimension."

    Once at least one BAA is signed, we score against the share that
    are still inside the ``ARTIFACT_FRESHNESS_RECENT_DAYS`` window. An
    org with one BAA signed yesterday → 100. An org with one BAA
    signed 18 months ago → 0 with a fact line surfacing the staleness.

    Note: ``window_days`` is intentionally *not* used as the freshness
    window — artifact freshness is measured against the canonical
    annual refresh cadence, not the rolling activity window the other
    dimensions share. We accept the parameter for signature symmetry.
    """
    del window_days  # Unused; see docstring.

    name = "artifact_freshness"

    # Count signed BAAs (signed_at NOT NULL). The dimension is about
    # documented attestations, not draft uploads.
    signed_q = select(func.count(BAAAgreement.id)).where(
        BAAAgreement.org_id == org_id,
        BAAAgreement.signed_at.is_not(None),
    )
    signed_count = int((await session.execute(signed_q)).scalar_one() or 0)

    if signed_count < THRESHOLD_ARTIFACT_FRESHNESS:
        return _not_yet_eligible(
            name,
            threshold=THRESHOLD_ARTIFACT_FRESHNESS,
            current=signed_count,
            reason="No signed BAA on file yet",
        )

    cutoff = _utc_now_naive() - timedelta(days=ARTIFACT_FRESHNESS_RECENT_DAYS)
    fresh_q = select(func.count(BAAAgreement.id)).where(
        BAAAgreement.org_id == org_id,
        BAAAgreement.signed_at.is_not(None),
        BAAAgreement.signed_at >= cutoff,
    )
    fresh_count = int((await session.execute(fresh_q)).scalar_one() or 0)

    score = int(round(100.0 * fresh_count / signed_count))
    if fresh_count == signed_count:
        fact = (
            f"{_comma(signed_count)} signed BAA"
            f"{'s' if signed_count != 1 else ''} on file, all within "
            "the past year"
        )
    elif fresh_count == 0:
        fact = (
            f"{_comma(signed_count)} signed BAA"
            f"{'s' if signed_count != 1 else ''} on file, none signed "
            "within the past year"
        )
    else:
        fact = (
            f"{_comma(fresh_count)} of {_comma(signed_count)} signed "
            "BAAs signed within the past year"
        )
    return _measured(
        name,
        score=score,
        raw_count=signed_count,
        measured_fact_line=fact,
    )


# ── 2. HITL completion ─────────────────────────────────────────────


async def compute_hitl_completion(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
) -> DimensionResult:
    """Score = % of HITL-triggering approvals decided in the window.

    Denominator: approvals with ``requested_at`` in window (the org
    asked for human review). Numerator: those that also have a
    ``decided_at`` in window (the human actually decided in time).

    "Decided in window" includes any decision after requested_at —
    we don't require the decision itself to land inside the rolling
    window if the request did, because that would penalise a recent
    approval that's legitimately still in flight. The follow-up B2
    AI Insights endpoint can do the more nuanced "still pending after
    24h" treatment.
    """
    name = "hitl_completion"
    since = _window_start(window_days)

    requested_q = select(func.count(Approval.id)).where(
        Approval.org_id == org_id,
        Approval.requested_at >= since,
    )
    requested = int((await session.execute(requested_q)).scalar_one() or 0)

    if requested < THRESHOLD_HITL_COMPLETION:
        return _not_yet_eligible(
            name,
            threshold=THRESHOLD_HITL_COMPLETION,
            current=requested,
            reason="Insufficient HITL events in window",
        )

    decided_q = select(func.count(Approval.id)).where(
        Approval.org_id == org_id,
        Approval.requested_at >= since,
        Approval.decided_at.is_not(None),
    )
    decided = int((await session.execute(decided_q)).scalar_one() or 0)

    score = int(round(100.0 * decided / requested))
    fact = (
        f"{_comma(requested)} HITL event"
        f"{'s' if requested != 1 else ''} requested · "
        f"{_comma(decided)} decided before commit"
    )
    return _measured(
        name,
        score=score,
        raw_count=requested,
        measured_fact_line=fact,
    )


# ── 3. Reviewer integrity ──────────────────────────────────────────


async def compute_reviewer_integrity(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
) -> DimensionResult:
    """Score = % of decisions made by a reviewer holding a sufficient role.

    For every approval with a decided_at in the window, scan its
    ``decisions`` JSON array. Each vote with a ``reviewer_role`` that
    satisfies the gate's ``required_role`` (per
    ``services.reviewer_roles.is_role_sufficient``) is counted as a
    correct-role decision; the rest are role-mismatches.

    Denominator = total decisions in window. Numerator = decisions
    where the reviewer's role was sufficient (or where the gate
    didn't pin a required_role — un-gated approvals can't have a
    mismatch by definition).

    Approvals that flipped ``reviewed_below_threshold=True`` count
    against the score even when a higher-role reviewer later resolved
    them — the integrity question is "did someone with the wrong
    credentials *attempt* to clear this gate?" and the answer is yes.
    """
    name = "reviewer_integrity"
    since = _window_start(window_days)

    # Pull approvals decided in window with their decisions JSON +
    # required_role context. ``decided_at`` is the row-level
    # terminal-decision timestamp; rows with NULL decided_at are still
    # pending and don't carry a reviewer-integrity signal yet.
    q = select(
        Approval.id,
        Approval.context,
        Approval.decisions,
        Approval.reviewed_below_threshold,
    ).where(
        Approval.org_id == org_id,
        Approval.decided_at.is_not(None),
        Approval.decided_at >= since,
    )
    rows = list((await session.execute(q)).all())

    total_decisions = 0
    correct_role = 0
    for _id, context, decisions, below in rows:
        ctx = context or {}
        required_role = ctx.get("required_role")
        votes_for_this_approval = 0
        for vote in decisions or []:
            total_decisions += 1
            votes_for_this_approval += 1
            reviewer_role = vote.get("reviewer_role")
            if reviewer_role is None:
                # Un-gated legacy vote with no role claim. Count as
                # correct only if the gate also had no required_role
                # — otherwise this is a silent under-credentialed
                # decision (the legacy decide path that pre-dated
                # Wave 2D W1.1).
                if required_role is None:
                    correct_role += 1
                continue
            if is_role_sufficient(reviewer_role, required_role):
                correct_role += 1

        # If THIS approval was flagged below-threshold but its votes
        # array didn't surface the bad vote (legacy decide path that
        # wrote the failure as a chain record rather than a vote),
        # still count the attempt against the score. We guard on the
        # per-approval vote counter — using the running ``total_
        # decisions`` here would silently swallow the below-threshold
        # flag whenever an earlier approval contributed votes.
        if below and votes_for_this_approval == 0:
            total_decisions += 1

    if total_decisions < THRESHOLD_REVIEWER_INTEGRITY:
        return _not_yet_eligible(
            name,
            threshold=THRESHOLD_REVIEWER_INTEGRITY,
            current=total_decisions,
            reason="Insufficient reviewed approvals in window",
        )

    score = int(round(100.0 * correct_role / total_decisions))
    fact = (
        f"{_comma(total_decisions)} reviewer decision"
        f"{'s' if total_decisions != 1 else ''} · "
        f"{_comma(correct_role)} with sufficient role"
    )
    return _measured(
        name,
        score=score,
        raw_count=total_decisions,
        measured_fact_line=fact,
    )


# ── 4. Notice delivery rate ────────────────────────────────────────


async def compute_notice_delivery_rate(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
) -> DimensionResult:
    """Score = % of webhook delivery attempts that succeeded in window.

    A successful attempt is one with a 2xx ``status_code``. Anything
    else (4xx, 5xx, transport-level failure with status_code=None)
    counts against the score.

    Denominator: webhook delivery attempts in window. We use *attempts*
    rather than deliveries because the dashboard surface is "are
    notices going out?" — a delivery that succeeded on attempt 3 is
    still 1/3 successful attempts from the channel's reliability POV,
    and that's the regulator-relevant signal.
    """
    name = "notice_delivery_rate"
    since = _window_start(window_days)

    # Join attempts → deliveries to filter by org_id. ``WebhookDelivery
    # .org_id`` is denormalised from the subscription row precisely for
    # cross-org queries like this — no transitive join to the
    # subscription table needed.
    from ...models import WebhookDelivery

    total_q = (
        select(func.count(WebhookDeliveryAttempt.id))
        .join(
            WebhookDelivery,
            WebhookDeliveryAttempt.delivery_id == WebhookDelivery.id,
        )
        .where(
            WebhookDelivery.org_id == org_id,
            WebhookDeliveryAttempt.attempted_at >= since,
        )
    )
    total = int((await session.execute(total_q)).scalar_one() or 0)

    if total < THRESHOLD_NOTICE_DELIVERY_RATE:
        return _not_yet_eligible(
            name,
            threshold=THRESHOLD_NOTICE_DELIVERY_RATE,
            current=total,
            reason="Insufficient webhook delivery attempts in window",
        )

    # Successful attempts: status_code in [200, 299]. Postgres + SQLite
    # both honour ``BETWEEN`` against an integer column.
    success_q = (
        select(func.count(WebhookDeliveryAttempt.id))
        .join(
            WebhookDelivery,
            WebhookDeliveryAttempt.delivery_id == WebhookDelivery.id,
        )
        .where(
            WebhookDelivery.org_id == org_id,
            WebhookDeliveryAttempt.attempted_at >= since,
            WebhookDeliveryAttempt.status_code.is_not(None),
            WebhookDeliveryAttempt.status_code >= 200,
            WebhookDeliveryAttempt.status_code < 300,
        )
    )
    succeeded = int((await session.execute(success_q)).scalar_one() or 0)

    score = int(round(100.0 * succeeded / total))
    fact = (
        f"{_comma(total)} webhook attempt"
        f"{'s' if total != 1 else ''} · "
        f"{_comma(succeeded)} succeeded"
    )
    return _measured(
        name,
        score=score,
        raw_count=total,
        measured_fact_line=fact,
    )


# ── 5. Chain integrity ─────────────────────────────────────────────


async def compute_chain_integrity_dimension(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
) -> DimensionResult:
    """Binary 100/0 (with a 50-score "warn" middle tier) from the
    existing chain-integrity aggregator.

    Always eligible — there's always *some* chain integrity signal,
    even for a brand new org (in which case the aggregator reports
    "no checkpoints yet" with status='ok' and we surface 100).

    Mapping:
        * status='ok'    → 100 (everything verified, within cadence)
        * status='warn'  → 50  (verified but cadence overdue)
        * status='error' → 0   (verification failed OR chain gap)
    """
    del window_days  # Always-eligible; uses the aggregator's 30d scan.
    name = "chain_integrity"
    result = await compute_chain_integrity(session, org_id)
    if result.status == "ok":
        score = 100
    elif result.status == "warn":
        score = 50
    else:
        score = 0

    # Pretty fact line. ``result.message`` is already regulator-ready
    # copy ("All recent checkpoints verified.", "Gap detected...", etc.)
    # — we surface it verbatim with the depth/cadence appendix.
    fact = (
        f"{_comma(result.chain_depth)} checkpoint"
        f"{'s' if result.chain_depth != 1 else ''} sealed · "
        f"{result.cadence} cadence · {result.message}"
    )
    return _measured(
        name,
        score=score,
        raw_count=result.chain_depth,
        measured_fact_line=fact,
    )


# ── 6. Workflow timeliness ─────────────────────────────────────────


async def compute_workflow_timeliness(
    session: AsyncSession,
    org_id: str,
    *,
    window_days: int,
    sla_hours: int = DEFAULT_WORKFLOW_SLA_HOURS,
) -> DimensionResult:
    """Score = % of decided approvals where (decided_at - requested_at) ≤ SLA.

    Denominator: approvals with ``decided_at`` set in window. Numerator:
    those whose decision landed within ``sla_hours`` of the request.

    We use the *count* form (pct_within_sla) rather than a p95 latency
    measure because the dashboard renders the pct number directly. A
    follow-up enhancement can layer p95 onto the response without
    changing the fact line.
    """
    name = "workflow_timeliness"
    since = _window_start(window_days)

    decided_q = select(
        Approval.requested_at, Approval.decided_at
    ).where(
        Approval.org_id == org_id,
        Approval.decided_at.is_not(None),
        Approval.decided_at >= since,
    )
    rows = list((await session.execute(decided_q)).all())
    decided_count = len(rows)

    if decided_count < THRESHOLD_WORKFLOW_TIMELINESS:
        return _not_yet_eligible(
            name,
            threshold=THRESHOLD_WORKFLOW_TIMELINESS,
            current=decided_count,
            reason="Insufficient decided approvals in window",
        )

    sla = timedelta(hours=sla_hours)
    within = 0
    for requested_at, decided_at in rows:
        if requested_at is None or decided_at is None:
            # ``requested_at`` has server_default=now(), so NULL should
            # only happen for malformed test fixtures — guard anyway so
            # the dimension can't NPE on a bad row.
            continue
        if (decided_at - requested_at) <= sla:
            within += 1

    score = int(round(100.0 * within / decided_count))
    fact = (
        f"{_comma(decided_count)} decision"
        f"{'s' if decided_count != 1 else ''} · "
        f"{_comma(within)} within {sla_hours}h SLA"
    )
    return _measured(
        name,
        score=score,
        raw_count=decided_count,
        measured_fact_line=fact,
    )
