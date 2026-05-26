"""Phase 2 Wave 2C PR A4 + Wave 2D PR A6 — reviewer completion service.

Implements ``POST /v1/reviews/{review_id}/complete``: a human reviewer
records their decision on a pending HITL approval that was created by
Wave 2B PR A2's gate materializer.

Flow (PR A4)
------------
1. Look up the ``Approval`` scoped to ``org_id`` under a row lock — 404
   if missing. The row lock (``SELECT ... FOR UPDATE`` on Postgres,
   no-op on SQLite) serialises concurrent callbacks; see PR A6 notes
   below.
2. If already terminal: 409 (resolved family — but see PR A6 for the
   approved/rejected branch) or 410 (expired). The expired check uses
   the same lazy-expiry contract as
   ``services.approvals.get_approval_with_lazy_expiry`` so the row's
   ``expires_at`` is honoured even if the sweeper hasn't run yet.
3. Pull ``required_role`` from ``Approval.context`` (A2 stashed it
   there). Compare to the reviewer-supplied role via
   ``services.reviewer_roles.is_role_sufficient``.
4. **Insufficient role** → write a chain ``ActionRecord`` with
   ``action_type='reviewer_credentials_insufficient'``,
   ``result='failure'``; set ``Approval.reviewed_below_threshold=True``;
   return HTTP 403 with the flat-error envelope the SDK already speaks.
5. **Sufficient role** → delegate to
   ``services.approvals.decide_approval`` (which writes the signed vote,
   final ``ActionRecord``, and dual ``approval.*`` + ``review.*``
   webhook emission); then populate the Wave 2B PR A5 columns
   ``decided_at`` + ``callback_received_at`` and return the row.

Wave 2B's forward-looking review explicitly called out the
``reviewed_below_threshold`` flag as load-bearing: the column defaults
to ``False`` and PR A4 is the writer for the True branch. The flag must
be flipped for *every* below-threshold callback even though the
approval stays pending — auditors look at this column to surface
silent-mask attempts.

Wave 2D PR A6 — attestation-conflict + concurrent-callback safety
------------------------------------------------------------------
Per v1-implementation-plan.md §Phase 2 line 108: "second callback with
the same ``review_id`` and a different decision is logged as
``attestation_conflict`` (canonical decision = first attestation)."

When the second callback arrives for a row that is already ``approved``
or ``rejected``:

* **Matching decision** → idempotent. Return the current
  ``Approval`` row. No new chain record, no new webhook event.
* **Conflicting decision** → write a chain ``ActionRecord`` with
  ``action_type='attestation_conflict'`` carrying both attestations,
  dispatch the ``attestation_conflict`` webhook event (event type
  reserved by PR A3 in ``services/webhooks.ALLOWED_EVENT_TYPES``), and
  raise ``HTTPException(409, AttestationConflictResponse(...))``.

The canonical decision is derived from ``approval.status`` (approved →
``approve``, rejected → ``reject``) — the source of truth for "who
decided what first" is the existing ``decide_approval`` resolution
record + ``decisions[0]`` vote. ``expired`` and ``cancelled`` rows are
NOT folded into the attestation-conflict path; they continue to surface
as 410 / 409 ``already cancelled`` per PR A4's existing contract (the
"canonical decision" concept doesn't apply when there *was* no
decision).

Concurrent callbacks (v1-test-plan.md "Concurrent callbacks race" gap
row): the row-level lock at step 1 serialises two simultaneous
callbacks for the same ``review_id``. On Postgres ``with_for_update()``
holds an actual row lock until commit, so the second transaction
blocks until the first finishes — the loser then sees an
``approved``/``rejected`` row and falls into the PR A6 second-callback
path (idempotent if same decision, conflict if different). SQLite is
single-threaded at the driver level so ``with_for_update()`` is a
documented no-op there; the test suite still exercises the second-
callback path via sequential calls.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval
from ..schemas.action import ActionRecordCreate
from ..schemas.approval import ApprovalDecision
from ..schemas.review import ReviewCompletionInput
from .approvals import _resolve_and_record, decide_approval
from .chain import build_and_insert_record
from .locks import get_review_lock
from .reviewer_roles import is_role_sufficient
from .webhooks import dispatch_event

logger = logging.getLogger("vera.reviews")


# Wave 2D closeout — clock-skew tolerance for client-supplied
# ``decided_at``. Reviewer clocks drift; we accept a 5-minute future
# window before rejecting as "in the future" (matches the tolerance
# typical webhook signers like Stripe / GitHub allow on signature
# timestamps). A 0-tolerance check would reject legitimate callbacks
# from clients whose NTP sync is off by seconds.
_DECIDED_AT_FUTURE_SKEW = timedelta(minutes=5)


def _now() -> datetime:
    """Naive UTC, matching services.approvals._now (project convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: datetime) -> datetime:
    """Normalise a (possibly tz-aware) datetime to naive UTC.

    The schema's ``Optional[datetime]`` accepts both naive and aware
    inputs (Pydantic v2 will parse ISO-8601 with offset). The rest of
    the project stores naive UTC — see ``models.Approval.requested_at``,
    ``Approval.expires_at`` and ``services.approvals._now`` — so we
    coerce here before any comparison. Naive inputs are assumed to
    already be UTC (matches the producer-side convention in
    ``schemas.approval``).
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_decided_at(
    payload_decided_at: datetime,
    approval: "Approval",  # noqa: F821 - forward ref kept readable
    now: datetime,
) -> datetime:
    """Validate a client-supplied ``decided_at`` against approval timing.

    Returns the normalised naive-UTC value when valid. Raises ``HTTPException``
    on any of the three documented failure modes — the SDK's
    ``wrap_httpx_error`` already speaks the flat-``code`` envelope.

    Failure modes (v1-test-plan.md "Callback timestamp validation" row):

    * ``decided_at`` more than ``_DECIDED_AT_FUTURE_SKEW`` ahead of
      server clock → 400 ``decided_at_in_future`` (defends against
      tampered client clocks claiming a decision was made after a row
      was tampered with — common forensic anti-pattern).
    * ``decided_at`` strictly older than ``approval.requested_at`` →
      400 ``decided_at_before_requested_at`` (impossible: a reviewer
      cannot decide before the approval was requested).
    * ``decided_at`` past ``approval.expires_at`` → 400 ``review_expired``
      (matches the lazy-expiry semantics in PR A4 so a client trying to
      backdate a decision into the expiry window still gets rejected).
    """
    normalised = _to_naive_utc(payload_decided_at)

    # Order matters. ``past-expiry`` is a strict subset of ``in-future``
    # whenever the review window is shorter than the skew tolerance —
    # but the spec asks for the more specific ``review_expired`` code
    # in that case. Check it FIRST so a reviewer trying to backdate a
    # decision into the closed window sees the right code instead of
    # the generic future-clock rejection.
    if (
        approval.expires_at is not None
        and normalised > approval.expires_at
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "review_expired",
                "review_id": approval.id,
                "decided_at": normalised.isoformat(),
                "expires_at": approval.expires_at.isoformat(),
                "detail": (
                    "decided_at sits past the review's expires_at; the "
                    "review window had already closed."
                ),
            },
        )

    if normalised > now + _DECIDED_AT_FUTURE_SKEW:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "decided_at_in_future",
                "review_id": approval.id,
                "decided_at": normalised.isoformat(),
                "server_now": now.isoformat(),
                "skew_tolerance_seconds": int(
                    _DECIDED_AT_FUTURE_SKEW.total_seconds()
                ),
                "detail": (
                    "decided_at is more than the allowed clock-skew "
                    "tolerance ahead of the server clock."
                ),
            },
        )

    if (
        approval.requested_at is not None
        and normalised < approval.requested_at
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "decided_at_before_requested_at",
                "review_id": approval.id,
                "decided_at": normalised.isoformat(),
                "requested_at": approval.requested_at.isoformat(),
                "detail": (
                    "decided_at predates the approval's requested_at; "
                    "a decision cannot be made before the review was "
                    "requested."
                ),
            },
        )

    return normalised


def _insufficient_role_detail(
    review_id: str, required_role: str | None, reviewer_role: str
) -> dict[str, object]:
    """Flat error envelope for the 403 path.

    Shape matches the SDK's ``wrap_httpx_error`` contract — top-level
    ``code`` plus context fields so the dashboard can render an
    actionable "wrong role" message without parsing a nested
    ``detail`` blob.
    """
    return {
        "code": "reviewer_credentials_insufficient",
        "review_id": review_id,
        "required_role": required_role,
        "reviewer_role": reviewer_role,
        "detail": (
            f"Reviewer role {reviewer_role!r} does not satisfy "
            f"required role {required_role!r}."
        ),
    }


# ── Wave 2D PR A6 helpers ────────────────────────────────────────────────


# Mapping from terminal Approval.status to the canonical decision verb a
# reviewer would have sent. Centralised so the conflict-detection path
# and the chain metadata stay in sync; ``expired``/``cancelled`` are
# intentionally absent (PR A4 already handles those — no decision means
# no canonical attestation, so the conflict concept doesn't apply).
_STATUS_TO_DECISION: dict[str, str] = {
    "approved": "approve",
    "rejected": "reject",
}


def _is_sqlite_session(session: AsyncSession) -> bool:
    """Detect SQLite to decide whether ``SELECT FOR UPDATE`` is legal.

    Mirrors ``services.chain._is_sqlite`` rather than importing it: the
    duplicate is two lines and avoids dragging chain.py's import-time
    side effects into a fresh code path.
    """
    url = str(session.bind.url) if session.bind else ""
    return "sqlite" in url


async def _lock_approval(
    session: AsyncSession, org_id: str, review_id: str
) -> Optional[Approval]:
    """Fetch the approval under a row-level lock when on Postgres.

    Postgres: ``SELECT ... FOR UPDATE`` blocks a second concurrent
    callback until the first transaction commits, so the loser
    deterministically observes the resolved row and falls into the
    second-callback path (PR A6) instead of racing into
    ``decide_approval`` and producing two competing votes.

    SQLite: ``with_for_update()`` is unsupported (and the in-memory
    driver is single-threaded anyway). We fall back to a plain
    ``session.get`` so the test suite still exercises the rest of the
    code path. Production runs on Postgres so the lock IS load-bearing
    there.
    """
    if _is_sqlite_session(session):
        approval = await session.get(Approval, review_id)
    else:
        result = await session.execute(
            select(Approval)
            .where(Approval.id == review_id, Approval.org_id == org_id)
            .with_for_update()
        )
        approval = result.scalar_one_or_none()
    if approval is None or approval.org_id != org_id:
        return None
    return approval


def _canonical_decision_for(approval: Approval) -> Optional[str]:
    """Map an approval's terminal status to its canonical decision verb.

    Returns ``None`` for non-conflict-eligible terminal states
    (``expired`` / ``cancelled``) so the caller routes those to PR A4's
    legacy 410 / 409 handlers instead of fabricating a phantom
    attestation conflict.
    """
    return _STATUS_TO_DECISION.get(approval.status)


def _canonical_attestation_summary(
    approval: Approval, canonical_decision: str
) -> dict[str, object]:
    """Snapshot the canonical attestation that produced the terminal status.

    Returns the minimum fields auditors need to reconstruct "who said
    what when": ``approver``, ``decision``, ``decided_at``, ``key_id``.

    /review finding (Codex #6): for ``approvers_required > 1`` flows,
    ``decisions[0]`` is the FIRST vote, which is NOT necessarily the
    vote whose decision matches the terminal status. Example: 2-of-N
    approve gate where reviewer A approves (decisions=[approve],
    pending), reviewer B rejects (decisions=[approve, reject], status
    flips to rejected). ``decisions[0]`` is approve but the canonical
    decision (= status verb) is reject — surfacing decisions[0] here
    would produce a conflict record claiming
    ``canonical_decision="reject"`` but
    ``canonical_attestation.decision="approve"``, which is
    self-contradictory evidence.

    Fix: find the *first* vote whose ``decision`` matches the canonical
    verb. That's the attestation that caused the terminal status flip
    (for single-approver flows, this is decisions[0]; for multi-approver
    flows, it's the vote that pushed the row over the threshold). Falls
    back to a status-only summary when the row is somehow terminal
    without a matching vote (defensive against future out-of-band
    resolution paths).
    """
    decisions = approval.decisions or []
    for vote in decisions:
        if vote.get("decision") == canonical_decision:
            return {
                "approver": vote.get("approver"),
                "decision": vote.get("decision"),
                "decided_at": vote.get("decided_at"),
                "key_id": vote.get("key_id"),
                "note": vote.get("note"),
            }
    return {
        "approver": None,
        "decision": canonical_decision,
        "decided_at": (
            approval.resolved_at.isoformat()
            if approval.resolved_at
            else None
        ),
        "key_id": None,
        "note": None,
    }


def _conflict_detail(
    review_id: str,
    canonical_decision: str,
    conflicting_decision: str,
) -> dict[str, object]:
    """Flat 409 envelope. Shape mirrors ``AttestationConflictResponse``.

    Returned inside ``HTTPException.detail``; FastAPI serialises it
    verbatim. Keep this in sync with
    ``schemas.review.AttestationConflictResponse``.
    """
    return {
        "code": "attestation_conflict",
        "review_id": review_id,
        "canonical_decision": canonical_decision,
        "conflicting_decision": conflicting_decision,
        "detail": (
            f"Review {review_id} was already attested as "
            f"{canonical_decision!r}; conflicting "
            f"{conflicting_decision!r} callback logged but not "
            "applied."
        ),
    }


async def _log_attestation_conflict(
    session: AsyncSession,
    approval: Approval,
    payload: ReviewCompletionInput,
    canonical_decision: str,
    conflict_detected_at: datetime,
) -> None:
    """Write the chain record + dispatch the ``attestation_conflict`` event.

    Per v1-implementation-plan.md §Phase 2 line 108 the canonical
    decision is the FIRST attestation; this helper records the SECOND
    (conflicting) callback as evidence without mutating the row's
    status. The record's ``result`` is ``failure`` because the second
    attestation was rejected as a state-machine transition, not because
    the reviewer was wrong about anything — the chain captures the
    attempted attestation so auditors can investigate disagreement.

    The webhook event reuses the customer-facing ``review.*`` payload
    style (``review_id`` not ``approval_id``) so dashboards and SDKs
    that already speak ``review.completed`` / ``review.expired`` can
    consume it without a new field naming convention.
    """
    context = approval.context or {}
    canonical_summary = _canonical_attestation_summary(approval, canonical_decision)
    conflict_summary = {
        "reviewer_id": payload.reviewer_id,
        "reviewer_role": payload.reviewer_role,
        "decision": payload.decision,
        # Reviewer-side timestamp would be ideal here but the input
        # schema doesn't carry one in Phase 2; use the conflict
        # detection time as a server-side stand-in so the record is
        # self-contained.
        "decided_at": conflict_detected_at.isoformat(),
        "note": payload.note,
    }

    record_data = ActionRecordCreate(
        action_name=approval.action_name,
        action_type="attestation_conflict",
        agent_name=approval.requested_by_agent,
        data_subject_id=approval.data_subject_id,
        # The conflicting reviewer is the proximate authoriser of THIS
        # chain entry. The canonical attestation stays the source of
        # truth for the approval itself (recorded on the original
        # ``human_approval_resolved`` record).
        authorized_by=f"reviewer:{payload.reviewer_id}",
        authorization_scope=approval.risk_tier,
        result="failure",
        input_data={
            "review_id": approval.id,
            "request_record_id": approval.request_record_id,
            "resolution_record_id": approval.resolution_record_id,
        },
        reasoning={
            "canonical_attestation": canonical_summary,
            "conflicting_attestation": conflict_summary,
            "canonical_decision": canonical_decision,
            "conflicting_decision": payload.decision,
            "conflict_detected_at": conflict_detected_at.isoformat(),
            "gate_name": context.get("gate_name"),
            "required_role": context.get("required_role"),
        },
    )
    await build_and_insert_record(session, approval.org_id, record_data)
    # ``build_and_insert_record`` writes within the caller's session; we
    # commit so the row is durable BEFORE the webhook dispatch (matches
    # the pattern in ``decide_approval`` / ``_resolve_and_record``).
    await session.commit()

    # /review finding (Codex #9): ``dispatch_event``'s
    # ``_default_idempotency_key`` only derives a key for ``review.*``
    # events, so without an explicit key here a client retry of the
    # SAME conflicting callback would burn a fresh webhook delivery
    # every time. Scope the key to (review_id, reviewer_id,
    # conflicting_decision) so retries from the same reviewer dedupe
    # while DISTINCT reviewers each get their own conflict event
    # (auditors need to see the full series of disagreement).
    idem_key = (
        f"{approval.id}:{payload.reviewer_id}:{payload.decision}"
        ":attestation_conflict"
    )
    await dispatch_event(
        session,
        approval.org_id,
        "attestation_conflict",
        {
            "review_id": approval.id,
            "canonical_decision": canonical_decision,
            "conflicting_decision": payload.decision,
            "canonical_attestation": canonical_summary,
            "conflicting_attestation": conflict_summary,
            "conflict_detected_at": conflict_detected_at.isoformat(),
            "resolution_record_id": approval.resolution_record_id,
        },
        idempotency_key=idem_key,
    )


async def complete_review(
    session: AsyncSession,
    org_id: str,
    review_id: str,
    data: ReviewCompletionInput,
) -> Approval:
    """Resolve a pending HITL approval on behalf of a human reviewer.

    Raises ``HTTPException`` with the documented status codes (403, 404,
    409, 410). On success returns the updated ``Approval`` row with the
    Wave 2B PR A5 timing columns populated.

    Wave 2D PR A6 — concurrent-callback safety
    ------------------------------------------
    Two layers of locking serialise simultaneous callbacks on the same
    ``review_id``:

    1. **In-process** ``asyncio.Lock`` keyed by ``review_id`` — covers
       single-process deployments AND the SQLite test suite (where the
       DB-level lock is a no-op).
    2. **Cross-process** ``SELECT … FOR UPDATE`` inside
       ``_lock_approval`` — covers multi-instance Postgres deployments
       where two replicas might receive callbacks for the same
       ``review_id`` simultaneously.

    The lock is released before the function returns; nested calls are
    not supported and would deadlock — there are none in the codebase.
    """
    # Layer 1: in-process serialisation. Held for the duration of the
    # callback so the loser observes the canonical resolution and
    # routes to ``_handle_second_callback`` rather than racing into
    # ``decide_approval``.
    #
    # Defense against /review finding (Codex #8): validate the path
    # segment is a UUID BEFORE allocating a lock keyed by it. Otherwise
    # any caller with a valid write API key could POST arbitrary
    # ``/v1/reviews/<random_string>/complete`` and grow the unbounded
    # ``_review_locks`` dict in every worker — a slow memory-DoS
    # vector. Approvals are stored with stringified UUIDs (see
    # ``models.Approval.id`` default), so rejecting non-UUID paths is a
    # 100% correct precondition.
    try:
        uuid.UUID(review_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Review not found")

    review_lock = await get_review_lock(review_id)
    async with review_lock:
        return await _complete_review_locked(session, org_id, review_id, data)


async def _complete_review_locked(
    session: AsyncSession,
    org_id: str,
    review_id: str,
    data: ReviewCompletionInput,
) -> Approval:
    """Body of ``complete_review`` executed under the per-review lock."""
    # Layer 2: row-level DB lock. ``with_for_update()`` on Postgres
    # blocks a second concurrent callback from a SIBLING process; on
    # SQLite it's a no-op (driver is single-threaded and the in-process
    # lock above covers the race).
    approval = await _lock_approval(session, org_id, review_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Review not found")

    # ── Wave 2D closeout — client-supplied decided_at validation.
    # Validate BEFORE branching on approval state so a malformed
    # timestamp is rejected uniformly regardless of pending /
    # terminal / expired state (the 400 reason is a contract about
    # the *callback*, not about the review). Skip when the client
    # omits the field — that preserves PR A4's "server fills with
    # now()" default.
    now_for_validation = _now()
    validated_decided_at: Optional[datetime] = None
    if data.decided_at is not None:
        validated_decided_at = _validate_decided_at(
            data.decided_at, approval, now_for_validation
        )

    # ── Already-terminal guards. Mirror the lazy-expiry contract from
    # services.approvals.get_approval_with_lazy_expiry so a reviewer
    # racing the sweeper sees a consistent 410 even on the first
    # callback.
    if approval.status != "pending":
        # Wave 2D PR A6: ``approved`` / ``rejected`` is now the
        # attestation-conflict branch — match-or-conflict against the
        # canonical first attestation rather than blanket-409. Other
        # terminal states (``expired`` / ``cancelled``) keep PR A4's
        # original behaviour.
        canonical_decision = _canonical_decision_for(approval)
        if canonical_decision is not None:
            return await _handle_second_callback(
                session=session,
                org_id=org_id,
                approval=approval,
                payload=data,
                canonical_decision=canonical_decision,
            )

        if approval.status == "expired":
            raise HTTPException(status_code=410, detail="Review has expired")
        raise HTTPException(
            status_code=409, detail=f"Review is already {approval.status}"
        )

    # Lazy expiration: same contract as
    # ``services.approvals.decide_approval`` — transition the row to
    # ``expired`` and fire the ``review.expired`` webhook BEFORE
    # raising 410. Skipping the transition would leave the row in
    # pending state until the sweeper runs and silently drop the
    # ``review.expired`` event that customers depend on for cleanup.
    if approval.expires_at is not None and _now() > approval.expires_at:
        # A6.5: _resolve_and_record no longer commits on its own; commit
        # here so the expired status + chain record are durable before
        # the 410 surfaces to the caller.
        await _resolve_and_record(session, approval, "expired")
        await session.commit()
        await session.refresh(approval)
        raise HTTPException(status_code=410, detail="Review has expired")

    context = approval.context or {}
    required_role = context.get("required_role")
    gate_name = context.get("gate_name")

    if not is_role_sufficient(data.reviewer_role, required_role):
        # ── Below-threshold callback. Plan §"CRITICAL design notes" calls
        # this out as the load-bearing requirement: write the chain
        # record AND flip the flag, even though the approval itself
        # stays pending (so a higher-role reviewer can still resolve it
        # later).
        record_data = ActionRecordCreate(
            action_name=approval.action_name,
            action_type="reviewer_credentials_insufficient",
            agent_name=approval.requested_by_agent,
            data_subject_id=approval.data_subject_id,
            authorized_by=f"reviewer:{data.reviewer_id}",
            authorization_scope=approval.risk_tier,
            result="failure",
            input_data={
                "review_id": approval.id,
                "request_record_id": approval.request_record_id,
            },
            reasoning={
                "required_role": required_role,
                "reviewer_role": data.reviewer_role,
                "reviewer_id": data.reviewer_id,
                "gate_name": gate_name,
                "attempted_decision": data.decision,
                # ``note`` is bounded to 2 KB by ReviewCompletionInput
                # so this is safe to anchor in the chain.
                "note": data.note,
            },
        )
        await build_and_insert_record(session, org_id, record_data)

        approval.reviewed_below_threshold = True
        await session.commit()
        await session.refresh(approval)

        logger.info(
            "review.complete.insufficient_role",
            extra={
                "review_id": approval.id,
                "org_id": org_id,
                "required_role": required_role,
                "reviewer_role": data.reviewer_role,
                "reviewer_id": data.reviewer_id,
                "gate_name": gate_name,
            },
        )

        raise HTTPException(
            status_code=403,
            detail=_insufficient_role_detail(
                approval.id, required_role, data.reviewer_role
            ),
        )

    # ── Sufficient role. Delegate to the existing approval-decision
    # service so the chain vote signature, dual webhook emission, and
    # status-machine all stay in lock-step with the legacy
    # POST /v1/approvals/{id}/decide path.
    #
    # W1.1 follow-up: ``decide_approval`` now also performs the
    # reviewer-role check itself (backported from this very function).
    # Forward the validated ``reviewer_role`` so the downstream check
    # is a tautological pass rather than a ``reviewer_role_required``
    # rejection. The double-check is intentional — A4's check fires
    # first under the per-review asyncio lock so chain records are
    # written for below-threshold callbacks before the row-level DB
    # lock is even acquired.
    decision = ApprovalDecision(
        decision=data.decision,
        # ``approver`` is the canonical identifier the signed vote
        # records. Combine reviewer_id with role so a single human
        # acting under different role hats produces distinct
        # signatures.
        approver=f"{data.reviewer_id}:{data.reviewer_role}",
        note=data.note,
        reviewer_role=data.reviewer_role,
    )
    resolved = await decide_approval(session, org_id, review_id, decision)

    # Wave 2B PR A5 columns. PR A2 left them server-default False/NULL;
    # PR A4 is the writer for the post-decision branch. Set
    # ``decided_at`` only when the row actually moved to a terminal
    # state — single-vote approvals always do, but a 2-of-N approval
    # with ``approve`` from one reviewer stays pending and we should
    # NOT pretend the row is decided yet.
    #
    # Wave 2D closeout — when the reviewer supplied a validated
    # ``decided_at`` we trust that value over ``_now()`` so the row
    # records the human's clock (per spec) rather than the server's
    # processing time. The server's wall-clock is still captured on
    # ``callback_received_at`` so auditors can reconstruct both sides.
    now = _now()
    resolved.callback_received_at = now
    if resolved.status != "pending":
        resolved.decided_at = validated_decided_at or now
    await session.commit()
    await session.refresh(resolved)

    logger.info(
        "review.complete.resolved",
        extra={
            "review_id": resolved.id,
            "org_id": org_id,
            "final_status": resolved.status,
            "reviewer_id": data.reviewer_id,
            "reviewer_role": data.reviewer_role,
            "gate_name": gate_name,
        },
    )
    return resolved


async def _handle_second_callback(
    *,
    session: AsyncSession,
    org_id: str,
    approval: Approval,
    payload: ReviewCompletionInput,
    canonical_decision: str,
) -> Approval:
    """Resolve the PR A6 second-callback branch.

    Called when ``complete_review`` observes a row whose status is
    ``approved`` or ``rejected``. Two outcomes:

    * Matching decision → idempotent. Return the row as-is so the SDK
      sees a 200 with the canonical state. No chain write, no event.
    * Differing decision → log + emit + raise 409 with the
      ``attestation_conflict`` envelope.

    Splitting this off keeps ``complete_review``'s flow readable; the
    helper is module-private and tested via ``complete_review``'s
    integration tests in ``test_attestation_conflict.py``.
    """
    if payload.decision == canonical_decision:
        logger.info(
            "review.complete.idempotent_second_callback",
            extra={
                "review_id": approval.id,
                "org_id": org_id,
                "canonical_decision": canonical_decision,
                "reviewer_id": payload.reviewer_id,
                "reviewer_role": payload.reviewer_role,
            },
        )
        return approval

    # ── Conflicting second attestation. Write the chain record + fire
    # the webhook BEFORE raising so the audit trail is durable even if
    # the 409 response gets lost on the wire.
    conflict_detected_at = _now()
    await _log_attestation_conflict(
        session=session,
        approval=approval,
        payload=payload,
        canonical_decision=canonical_decision,
        conflict_detected_at=conflict_detected_at,
    )
    logger.warning(
        "review.complete.attestation_conflict",
        extra={
            "review_id": approval.id,
            "org_id": org_id,
            "canonical_decision": canonical_decision,
            "conflicting_decision": payload.decision,
            "reviewer_id": payload.reviewer_id,
            "reviewer_role": payload.reviewer_role,
        },
    )
    raise HTTPException(
        status_code=409,
        detail=_conflict_detail(
            approval.id, canonical_decision, payload.decision
        ),
    )


__all__ = ["complete_review"]
