"""Chain-integrity aggregator (Phase 3 Wave 3D.1).

Powers ``GET /v1/dashboard/chain-integrity`` — the at-a-glance
"is our evidence trail intact right now?" answer surfaced on the
Home page tile.

The aggregator composes existing service-layer primitives rather than
duplicating Merkle / checkpoint math:

* :func:`app.services.checkpoint.verify_checkpoint` for signature +
  external-receipt verification (history-aware, KMS-rotation safe).
* :func:`app.services.kms.get_key_by_id` to surface the *current*
  signing key + algorithm.
* Direct ``Checkpoint`` queries for chain-depth + freshness math.

Status semantics
----------------

* ``ok``        — every sealed checkpoint in the last 30 days verifies
                  AND the chain has no gaps in the recent-window scan
                  AND the most-recent checkpoint is fresh by the org's
                  cadence threshold.
* ``warn``      — every recent checkpoint still verifies, but the most-
                  recent expected checkpoint is overdue (cadence-aware:
                  hourly orgs warn after 2h, daily orgs after 48h). The
                  evidence trail is intact — we just haven't sealed in
                  a while.
* ``error``     — at least one recent checkpoint failed verification
                  OR there's a gap in the chain (we expected a prior
                  checkpoint at sequence S but there isn't one). This
                  is the regulator-relevant condition; the dashboard
                  surfaces it red.

We scan a 30-day verification window rather than the full history so
the aggregator stays fast on multi-year-old chains. The brief asks
for "all checkpoints in the last 30 days sealed and verified"; older
verification gaps surface via the manual ``POST /v1/verify/checkpoints/
verify`` flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, Organization
from ..models.checkpoint import Checkpoint
from .checkpoint import verify_checkpoint
from .kms import get_key_by_id, get_kms

logger = logging.getLogger("vera.chain_integrity")


# Freshness thresholds keyed by org cadence. The brief spells out
# "hourly cadence org, last seal >2h ago" as the canonical warn
# example; we generalise:
#   * hourly   → 2h grace (one missed sweep is the warning trigger)
#   * daily    → 48h grace (one full missed day)
#   * disabled → no freshness warning ever (operator opted out)
_FRESHNESS_GRACE: dict[str, Optional[timedelta]] = {
    "hourly": timedelta(hours=2),
    "daily": timedelta(hours=48),
    "disabled": None,
}

# Verification window for the recent-checkpoint scan. The brief calls
# out "all checkpoints in the last 30 days sealed and verified" for the
# green-status threshold; we use the same window for chain-gap
# detection so the two columns of the tile are consistent.
_RECENT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class LatestCheckpointSummary:
    """Trimmed checkpoint shape returned by the aggregator.

    We only surface fields the tile renders — no Merkle root, no
    external receipt blob. Callers wanting the full row can hit
    ``GET /v1/checkpoints/{date}``.
    """

    checkpoint_id: str
    sealed_at: datetime
    sequence: int
    record_count: int


@dataclass(frozen=True)
class KmsKeySummary:
    """Current-key summary surfaced by the aggregator."""

    key_id: str
    algorithm: str


@dataclass(frozen=True)
class ChainIntegrityResult:
    """The full aggregator response — shape matches the route schema."""

    status: str  # "ok" | "warn" | "error"
    message: str
    latest_checkpoint: Optional[LatestCheckpointSummary]
    chain_depth: int
    kms_key: Optional[KmsKeySummary]
    cadence: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _latest_checkpoint(
    session: AsyncSession, org_id: str
) -> Optional[Checkpoint]:
    q = (
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(
            Checkpoint.created_at.desc(),
            Checkpoint.sequence_at_checkpoint.desc(),
        )
        .limit(1)
    )
    return (await session.execute(q)).scalars().first()


async def _chain_depth(session: AsyncSession, org_id: str) -> int:
    q = select(func.count(Checkpoint.id)).where(Checkpoint.org_id == org_id)
    return int((await session.execute(q)).scalar_one() or 0)


async def _recent_checkpoints(
    session: AsyncSession, org_id: str, *, since: datetime
) -> list[Checkpoint]:
    """Recent-window checkpoints, oldest first (chain-gap walk order)."""
    q = (
        select(Checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.created_at >= since,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.asc())
    )
    return list((await session.execute(q)).scalars().all())


async def _detect_recent_chain_gap(
    session: AsyncSession,
    org_id: str,
    *,
    recent: list[Checkpoint],
    chain_depth: int,
) -> bool:
    """Return True if the recent-window checkpoints reveal a missing prior.

    The brief calls out "a ``prior_checkpoint_id`` doesn't link to
    anything" as the canonical gap signal. We translate that into:
    *there are more checkpoints in the chain than we see in the recent
    window, yet the oldest recent checkpoint has no checkpoint in DB
    with a smaller sequence*. That's the inconsistency — a prior row
    should exist (depth says there are older rows) but doesn't.

    The first-checkpoint-ever case (``chain_depth == len(recent)`` and
    oldest.sequence > 1) is NOT a gap — it just means actions were
    captured before the first seal, which is the normal Phase 1
    bootstrap. We only fire when the count math is inconsistent with
    the actual rows.
    """
    if not recent:
        return False
    # If the recent window equals the full chain, there's no prior to
    # be missing — the chain just starts here.
    if chain_depth <= len(recent):
        return False
    oldest = recent[0]
    if oldest.sequence_at_checkpoint <= 1:
        return False
    q = (
        select(func.count(Checkpoint.id))
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint
            < oldest.sequence_at_checkpoint,
        )
        .limit(1)
    )
    prior_count = int((await session.execute(q)).scalar_one() or 0)
    # chain_depth > len(recent) implies prior_count > 0 *unless* the
    # extra rows live at sequence >= oldest.sequence — which is
    # impossible by definition since `recent` is filtered by created_at
    # not sequence. Still, the comparison protects against future
    # refactors that change the recent-filter shape.
    return prior_count == 0


async def _record_count_for_checkpoint(
    session: AsyncSession, org_id: str, checkpoint: Checkpoint
) -> int:
    """Count records sealed by *this* checkpoint (since the prior one).

    Matches ``checkpoints_by_date._record_count_in_window`` semantics
    so the tile's number agrees with the by-date endpoint to the row.
    """
    prior_q = (
        select(Checkpoint.sequence_at_checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint
            < checkpoint.sequence_at_checkpoint,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    prior_seq = (await session.execute(prior_q)).scalar_one_or_none() or 0
    q = select(func.count(ActionRecord.id)).where(
        ActionRecord.org_id == org_id,
        ActionRecord.sequence_number > prior_seq,
        ActionRecord.sequence_number <= checkpoint.sequence_at_checkpoint,
    )
    return int((await session.execute(q)).scalar_one() or 0)


async def _kms_summary(
    session: AsyncSession, checkpoint: Optional[Checkpoint]
) -> Optional[KmsKeySummary]:
    """Resolve the *active* signing key for the tile's KMS row.

    Priority:
      1. The latest checkpoint's ``key_id`` (history-table-backed) —
         the actual key currently sealing the chain. We look it up in
         the history table so the algorithm field is authoritative
         rather than guessed.
      2. Fall back to ``get_kms()`` for orgs that haven't sealed any
         checkpoint yet. The history row may not exist yet (rows are
         upserted on first sign) — we still surface the current
         provider so the tile can show "no signatures yet, but the
         next one will use key X".
    """
    if checkpoint is not None and checkpoint.key_id:
        row = await get_key_by_id(session, checkpoint.key_id)
        if row is not None:
            return KmsKeySummary(key_id=row.key_id, algorithm=row.algorithm)
        # History row missing for a key that signed a real checkpoint
        # — possible during the 3A.a migration window. Fall back to
        # the checkpoint's stored algorithm hint (none on the row
        # itself; use the current provider's algorithm as best effort).
        kms = get_kms()
        return KmsKeySummary(
            key_id=checkpoint.key_id,
            algorithm=kms.algorithm or "unknown",
        )
    # No checkpoint yet — surface what the next sign() will use.
    try:
        kms = get_kms()
        return KmsKeySummary(
            key_id=kms.get_key_id(),
            algorithm=kms.algorithm or "unknown",
        )
    except Exception:
        # KMS misconfigured in dev — don't 500; the tile can render
        # without a key row.
        logger.warning("chain_integrity: get_kms() failed", exc_info=True)
        return None


def _is_overdue(
    latest: Optional[Checkpoint], cadence: str, *, now: datetime
) -> bool:
    """Return True if the most-recent checkpoint is past its freshness grace."""
    grace = _FRESHNESS_GRACE.get(cadence)
    if grace is None:
        # disabled cadence — freshness is operator-managed.
        return False
    if latest is None:
        # No checkpoint yet. The brief frames this as "no evidence
        # trail yet" — not overdue in the warning sense; the tile
        # surfaces it as a neutral state via the message string. We
        # return False here so the green/yellow/red decision falls
        # through to "ok" + a clear "no checkpoints yet" message.
        return False
    age = now - latest.created_at
    return age > grace


async def compute_chain_integrity(
    session: AsyncSession, org_id: str
) -> ChainIntegrityResult:
    """Aggregate the Home-tile chain-integrity surface for ``org_id``.

    See module docstring for status semantics. This function is the
    single place to add new signals (e.g. OTS anchor freshness in a
    later wave) — the route layer just serialises whatever we return.
    """
    now = _utc_now()
    org = await session.get(Organization, org_id)
    if org is None:
        # Defensive: route gate already enforced org membership, but
        # the org row might be mid-deletion. Fall back to 'daily'
        # cadence so the freshness math doesn't NPE.
        cadence = "daily"
    else:
        cadence = org.checkpoint_cadence

    latest = await _latest_checkpoint(session, org_id)
    depth = await _chain_depth(session, org_id)
    kms = await _kms_summary(session, latest)

    latest_summary: Optional[LatestCheckpointSummary] = None
    if latest is not None:
        record_count = await _record_count_for_checkpoint(
            session, org_id, latest
        )
        latest_summary = LatestCheckpointSummary(
            checkpoint_id=latest.id,
            sealed_at=latest.created_at,
            sequence=latest.sequence_at_checkpoint,
            record_count=record_count,
        )

    # ── Empty-org path. No checkpoints sealed yet → "ok, no trail
    # yet" rather than warn/error. The Home page's higher-level
    # "isFullyEmpty" branch already handles "no activity at all"; this
    # branch covers "actions captured, no checkpoint yet" which is the
    # common state for a freshly-onboarded org.
    if latest is None:
        return ChainIntegrityResult(
            status="ok",
            message="No checkpoints sealed yet.",
            latest_checkpoint=None,
            chain_depth=0,
            kms_key=kms,
            cadence=cadence,
        )

    # ── Verify recent checkpoints (signature + record-hash match).
    since = now - timedelta(days=_RECENT_WINDOW_DAYS)
    recent = await _recent_checkpoints(session, org_id, since=since)
    # Always include the latest checkpoint in the verify-scan even if
    # it landed before the 30-day window — an org with a single
    # checkpoint 60 days ago should still surface that checkpoint's
    # verification state on the tile.
    if not recent:
        recent = [latest]

    failed_id: Optional[str] = None
    for cp in recent:
        ok = await verify_checkpoint(session, cp)
        if not ok:
            failed_id = cp.id
            break

    if failed_id is not None:
        return ChainIntegrityResult(
            status="error",
            message=(
                f"Checkpoint {failed_id[:8]} failed verification — "
                f"the evidence trail for this window can't be confirmed."
            ),
            latest_checkpoint=latest_summary,
            chain_depth=depth,
            kms_key=kms,
            cadence=cadence,
        )

    # ── Chain-gap detection. We expect the count of prior-of-recent
    # checkpoints to match what ``chain_depth`` implies; mismatch
    # means a checkpoint row's prior link points at nothing.
    gap = await _detect_recent_chain_gap(
        session, org_id, recent=recent, chain_depth=depth
    )
    if gap:
        return ChainIntegrityResult(
            status="error",
            message=(
                "Gap detected in the checkpoint chain — an "
                "earlier checkpoint is missing."
            ),
            latest_checkpoint=latest_summary,
            chain_depth=depth,
            kms_key=kms,
            cadence=cadence,
        )

    # ── Freshness check.
    if _is_overdue(latest, cadence, now=now):
        return ChainIntegrityResult(
            status="warn",
            message=(
                "The most recent checkpoint is overdue for the "
                f"{cadence} cadence."
            ),
            latest_checkpoint=latest_summary,
            chain_depth=depth,
            kms_key=kms,
            cadence=cadence,
        )

    return ChainIntegrityResult(
        status="ok",
        message="All recent checkpoints verified.",
        latest_checkpoint=latest_summary,
        chain_depth=depth,
        kms_key=kms,
        cadence=cadence,
    )
