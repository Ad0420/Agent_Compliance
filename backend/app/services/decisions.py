"""Customer Decisions feed service (PR C1.5).

Produces the dashboard's Customer detail Decisions tab feed by joining
``ActionRecord`` to its (optional) ``Approval`` and (optional)
``WebhookDelivery`` rows server-side, returning a flat
``CustomerDecisionResponse`` per action.

Why a dedicated service
=======================

C1 (the frontend tab) was wired against ``GET /v1/actions?tenant_id=``
with a client-side adapter that read ``reasoning.gate_ruling`` /
``reasoning.webhook_delivery`` / ``reasoning.hitl_expires_at`` out of
the action's reasoning blob. The architectural reality is:

* The gate evaluator stashes its metadata on ``Approval.context``
  (gate_name / required_role / citation / reason) — NOT on
  ActionRecord.reasoning. Writing to reasoning would change
  ``HASHABLE_FIELDS`` and break chain integrity.
* Webhook delivery state is its own ``WebhookDelivery`` row keyed by
  ``idempotency_key = f"{approval_id}:{event_type}"`` for review events.
* Approval expiry timing lives on ``Approval.expires_at``.

This service does that three-way join once, server-side, so the
dashboard renders the right Ruling badge + delivery dot + HITL countdown
without N+1 follow-up fetches.

ALLOW limitation
================

ALLOW rulings never create an ``Approval`` row (the gate decided no
human action was needed). So this service can only surface Ruling data
for actions whose gate fired HITL or BLOCK. ALLOW-path actions show
``ruling=None`` in the response — the row still appears, just without a
gate badge. Fixing that ("show ALLOW rulings in the feed too") requires
either:

  * SDK-side denormalisation: write the Ruling onto a NON-hashable
    column on ActionRecord at capture time (would need a schema change
    that doesn't disturb the hash chain), OR
  * A new ``gate_evaluations`` table that records every Ruling the
    evaluator produced, joined here the same way ``Approval`` is.

Both approaches are out of scope for C1.5. See the PR body for the
follow-up tracking note.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, Approval, WebhookDelivery
from ..schemas.customer_decision import (
    CustomerDecisionResponse,
    CustomerDecisionRuling,
    CustomerDecisionWebhookDelivery,
    DecisionWebhookStatus,
    RulingEffect,
)
from .webhook_retry import MAX_ATTEMPTS

logger = logging.getLogger("vera.decisions")


# Default + cap match the convention used by ``routes/customers.list_customers``
# (default 50, max 200) but the decisions feed allows a higher cap so a
# Customer with thousands of actions can still backfill the tab in one
# bounded round-trip if needed. Kept here (not in the route) so the
# service contract is the source of truth.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def _derive_webhook_status(delivery: WebhookDelivery) -> DecisionWebhookStatus:
    """Collapse ``WebhookDelivery.status`` into the UI's narrower vocabulary.

    The Decisions tab speaks ``delivered | pending | retrying | aborted``
    — a customer-facing simplification. The mapping mirrors the original
    C1 adapter (frontend/lib/api-client.ts::_coerceWebhookDelivery) so
    rows render identically whether the adapter or this service produced
    the payload.
    """
    status = delivery.status
    if status == "succeeded":
        return "delivered"
    if status == "aborted":
        return "aborted"
    # ``pending`` / ``in_progress`` collapse to ``pending`` unless we can
    # see this is a real retry-in-flight (attempt > 1 with a scheduled
    # next attempt). Matches the C1 adapter's heuristic.
    attempt_count = delivery.attempt_count or 0
    if status == "pending" and attempt_count > 1 and delivery.next_retry_at is not None:
        return "retrying"
    return "pending"


def _build_ruling(approval: Approval) -> CustomerDecisionRuling:
    """Construct the Ruling DTO from an approval's context blob.

    The HITL materializer (``services/gates/hitl.py``) stashes the
    winning gate's metadata in ``Approval.context`` so the reviewer-
    completion path (PR A4) can read it without joining a separate
    table. Same blob, different reader: this surface lets the dashboard
    show the gate badge without a second round-trip.

    ``effect`` derivation:
      * The presence of an Approval row means a gate fired HITL or
        BLOCK — pure ALLOW never creates one. We surface ``require_hitl``
        as the effect today; once a Block-without-HITL path lands
        (Phase 2 PR B-something), this should branch on
        ``context.get("effect")`` once the materializer writes it.
    """
    ctx = approval.context or {}
    # Guard the literal narrowing — context is JSON, so callers could in
    # principle write any string. Default to require_hitl since that's
    # the only effect the current materializer produces.
    raw_effect = ctx.get("effect")
    effect: RulingEffect = (
        raw_effect if raw_effect in ("allow", "require_hitl", "block") else "require_hitl"
    )
    return CustomerDecisionRuling(
        effect=effect,
        # reason is machine-readable ("gated", "block_baa_expired"); the
        # materializer sets "reason" from the ruling, default to "gated"
        # for safety on legacy rows.
        reason=ctx.get("reason") or "gated",
        # action_summary is the human-readable framing the reviewer sees
        # ("CMS requires an attending physician to confirm…"). Re-use it
        # here so the tab's expanded panel can echo the same copy.
        reason_detail=approval.action_summary,
        citation=ctx.get("citation"),
        review_id=approval.id,
        # fix_url is owned by the gate definition; no materializer
        # writes it today. Surface what's there if a future writer adds it.
        fix_url=ctx.get("fix_url"),
        required_role=ctx.get("required_role"),
        gate_name=ctx.get("gate_name"),
    )


def _build_webhook_delivery(
    delivery: WebhookDelivery,
) -> CustomerDecisionWebhookDelivery:
    return CustomerDecisionWebhookDelivery(
        status=_derive_webhook_status(delivery),
        attempt_count=delivery.attempt_count or 0,
        max_attempts=MAX_ATTEMPTS,
        next_retry_at=delivery.next_retry_at,
        last_status_code=delivery.last_status_code,
        succeeded_at=delivery.succeeded_at,
        aborted_at=delivery.aborted_at,
    )


def _hitl_expires_at(approval: Approval) -> Optional[datetime]:
    """Surface ``Approval.expires_at`` only while the review is still pending.

    After approval / rejection / expiry / cancellation the expiry clock
    is no longer meaningful for the UI — the row's badge already
    captures the terminal state.
    """
    if approval.status != "pending" or approval.expires_at is None:
        return None
    return approval.expires_at


async def _latest_webhook_delivery_per_approval(
    session: AsyncSession,
    *,
    org_id: str,
    approval_ids: Sequence[str],
) -> dict[str, WebhookDelivery]:
    """Batch-fetch the most recent ``WebhookDelivery`` for each approval.

    The producer-side idempotency convention for ``review.*`` events
    (see ``services/webhooks._default_idempotency_key``) is
    ``f"{approval_id}:{event_type}"``. We filter on the ``approval_id:``
    prefix and pick the most recently created delivery per prefix,
    matching what the Decisions tab actually wants to show ("latest
    delivery attempt for this review").

    Done as a separate query (rather than a single SQL CTE) to keep the
    join readable + portable across SQLite (tests) and Postgres
    (production). The cardinality is bounded by ``limit`` (default 50,
    max 500), so the second round-trip is cheap.

    A LIKE-based prefix filter on ``idempotency_key`` is the lowest-
    common-denominator way to do this; both SQLite and Postgres handle
    ``LIKE 'approval_id:%'`` without an extra index because the row
    count for a given org is small. If this becomes hot, we'd add an
    expression index on ``substring(idempotency_key from '^[^:]+')``.
    """
    if not approval_ids:
        return {}

    # Build the OR of LIKE patterns. We can't use ``IN`` here because the
    # idempotency_key includes the event_type suffix; we want all
    # ``review.*`` events for any of these approvals.
    like_clauses = [
        WebhookDelivery.idempotency_key.like(f"{aid}:%") for aid in approval_ids
    ]

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.org_id == org_id)
        .where(or_(*like_clauses))
        .order_by(WebhookDelivery.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    # Bucket by the approval_id prefix; keep the FIRST seen (deliveries
    # are ordered desc by created_at, so the first row per prefix is the
    # most recent).
    latest: dict[str, WebhookDelivery] = {}
    for d in rows:
        # ``idempotency_key`` is non-null at the DB level; split on the
        # first ``:`` to recover the approval_id prefix.
        prefix, _, _ = (d.idempotency_key or "").partition(":")
        if not prefix or prefix not in approval_ids or prefix in latest:
            # Skip prefixes we didn't ask for (defensive — the LIKE
            # filter should have screened these) and rows that arrived
            # after a more recent one already won the bucket.
            continue
        latest[prefix] = d
    return latest


async def list_customer_decisions(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_id: str,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> tuple[list[CustomerDecisionResponse], int]:
    """Return Decisions tab rows for one Customer.

    Returns ``(rows, total)`` where ``rows`` is at most ``limit``
    ``CustomerDecisionResponse`` objects ordered by
    ``ActionRecord.sequence_number DESC`` (newest first) and ``total``
    is the unpaginated count for the (org, tenant) pair.

    Caller is responsible for verifying the Customer exists + belongs to
    the org BEFORE calling (the route does this so a missing customer
    returns 404 instead of 200 + empty list). This function will happily
    return an empty list for an org/tenant pair that has zero
    ActionRecords.
    """
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0

    # 1) Total count for this (org, tenant). Cheap with the
    # idx_ar_org_tenant_seq composite index.
    count_stmt = (
        select(func.count(ActionRecord.id))
        .where(ActionRecord.org_id == org_id)
        .where(ActionRecord.tenant_id == tenant_id)
    )
    total = int((await session.execute(count_stmt)).scalar() or 0)

    if total == 0:
        return [], 0

    # 2) Page of ActionRecord rows for this customer. Sorted newest
    # first so the Decisions tab matches the rest of the dashboard's
    # default chronological ordering.
    action_stmt = (
        select(ActionRecord)
        .where(ActionRecord.org_id == org_id)
        .where(ActionRecord.tenant_id == tenant_id)
        .order_by(ActionRecord.sequence_number.desc())
        .limit(limit)
        .offset(offset)
    )
    actions = list((await session.execute(action_stmt)).scalars().all())
    if not actions:
        # Empty page (offset past the end) — return the count so the UI
        # can render "no rows in this slice" without re-querying.
        return [], total

    action_ids = [a.id for a in actions]

    # 3) Approvals attached to any of those action rows. The
    # ``request_record_id`` FK points back to the ActionRecord that
    # triggered the HITL flow.
    approval_stmt = (
        select(Approval)
        .where(Approval.org_id == org_id)
        .where(Approval.request_record_id.in_(action_ids))
    )
    approvals = list((await session.execute(approval_stmt)).scalars().all())
    # An action could in principle have multiple approvals if the gate
    # was re-evaluated, but the request_record_id FK is set once at
    # materialization time. If a duplicate ever appears, take the most
    # recently requested — matches the dashboard's "show the latest
    # review" intent.
    approval_by_action: dict[str, Approval] = {}
    for ap in approvals:
        if ap.request_record_id is None:
            continue
        existing = approval_by_action.get(ap.request_record_id)
        if existing is None or (
            ap.requested_at and existing.requested_at and ap.requested_at > existing.requested_at
        ):
            approval_by_action[ap.request_record_id] = ap

    # 4) Latest WebhookDelivery per approval, keyed off the
    # ``f"{approval_id}:{event_type}"`` idempotency convention.
    approval_ids = [ap.id for ap in approval_by_action.values()]
    delivery_by_approval = await _latest_webhook_delivery_per_approval(
        session, org_id=org_id, approval_ids=approval_ids
    )

    # 5) Stitch into the response shape.
    rows: list[CustomerDecisionResponse] = []
    for action in actions:
        approval = approval_by_action.get(action.id)
        ruling = _build_ruling(approval) if approval is not None else None
        delivery = (
            delivery_by_approval.get(approval.id) if approval is not None else None
        )
        webhook_delivery = (
            _build_webhook_delivery(delivery) if delivery is not None else None
        )
        rows.append(
            CustomerDecisionResponse(
                id=action.id,
                sequence_number=action.sequence_number,
                action_timestamp=action.action_timestamp,
                agent_name=action.agent_name,
                action_name=action.action_name,
                action_type=action.action_type,
                result=action.result,
                ruling=ruling,
                webhook_delivery=webhook_delivery,
                hitl_expires_at=_hitl_expires_at(approval) if approval is not None else None,
            )
        )

    return rows, total


__all__ = ["list_customer_decisions", "DEFAULT_LIMIT", "MAX_LIMIT"]
