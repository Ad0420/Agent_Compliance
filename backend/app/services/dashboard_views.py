"""Dashboard view serializers — HIPAA minimum-necessary PHI redaction (W1.2).

Closes Phase 2 acceptance finding ``dashboard-should-not-display-phi``
(CRITICAL). Per HIPAA's minimum-necessary standard (45 CFR 164.502(b)),
each entity in the BAA chain should access only the minimum PHI needed
for their purpose. Vera's dashboard purpose is the audit trail — not the
PHI itself — so dashboard responses MUST NOT include PHI fields like
``diagnoses``, ``medication_orders``, ``patient_mrn``, free-text notes,
or even the opaque ``data_subject_id``.

Why a separate view (not a schema change)
=========================================

The ``Approval`` / ``CustomerDecisionResponse`` shapes are wire contracts
shared with SDK callers. The SDK is an in-band tool that runs inside the
customer's own backend (in-scope for their BAA), so it legitimately needs
the full shape — ``data_subject_id`` for HITL polling correlation,
``context`` PHI fields for the customer's own review UI.

The dashboard, by contrast, is operated by AI vendor staff (e.g. Abridge
engineers + compliance officers) — a separate trust boundary. Same
endpoints serve both, distinguished by auth method: Clerk session →
dashboard (strip PHI), API key → SDK (full shape).

This module owns the strip logic. Routes call the right serializer based
on the ``api_key`` half of ``require_permission``'s return tuple
(``api_key is None`` ↔ Clerk session ↔ dashboard).

Defense in depth
================

Even if the frontend dropped its PHI-rendering, leaving PHI on the wire
keeps it in browser memory, network logs, observability tooling, and any
intermediate proxy. The server-side strip is the only place where the
"dashboard never sees PHI" property actually holds.
"""
from __future__ import annotations

from typing import Any

from ..models import Approval
from ..schemas.customer_decision import CustomerDecisionResponse


# Whitelist of ``Approval.context`` keys that are safe for the dashboard.
# Everything else is dropped. Whitelist (not blacklist) so a new PHI field
# added to ``context`` by a future gate doesn't silently leak — the new
# field would have to be added here explicitly to surface to the dashboard.
_SAFE_APPROVAL_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "gate_name",
        "required_role",
        "citation",
        "reason",
        # ``effect`` is the ruling effect ("require_hitl"/"block"/"allow") —
        # gate metadata, not PHI. Surfaced so the dashboard can render the
        # same ruling badge as the SDK.
        "effect",
        # ``fix_url`` is the gate pack's remediation link (e.g. CMS docs).
        # No PHI; safe to render.
        "fix_url",
    }
)


def _safe_approval_context(context: dict | None) -> dict:
    """Project ``Approval.context`` down to the dashboard-safe whitelist.

    Returns an empty dict for missing / empty input so the response shape
    stays stable (``context: {}`` not ``context: None``) — matches the
    Approval model's ``default=dict`` and avoids None-checks downstream.

    Drops any key not in ``_SAFE_APPROVAL_CONTEXT_KEYS``. Typical dropped
    keys for a clinical gate ruling include ``encounter_id``,
    ``patient_mrn``, ``diagnoses``, ``medication_orders``,
    ``lab_or_imaging_orders``, ``original_input_data``, ``transcript``,
    ``note``, and anything else the gate writer chose to stash on the
    context blob.
    """
    if not context:
        return {}
    return {
        key: context[key]
        for key in _SAFE_APPROVAL_CONTEXT_KEYS
        if key in context
    }


def serialize_approval_for_dashboard(approval: Approval) -> dict[str, Any]:
    """Strip PHI from an ``Approval`` row for dashboard rendering.

    Omitted fields and why:

    * ``data_subject_id`` — opaque but per-patient identifier; dashboard
      doesn't need it for any UI use case (no per-patient lookups from
      the vendor's compliance UI).
    * ``action_summary`` — often contains PHI in narrative form
      ("Commit note for encounter MRN-12345: 1 new diagnosis…"). Gates
      construct this for SDK callers / reviewers; the dashboard shows
      the gate's ``citation`` + ``required_role`` instead.
    * Most ``context`` keys — only the whitelisted gate-metadata keys
      survive (see ``_safe_approval_context``).

    Preserved fields:

    * IDs, FKs, status, risk tier, approver counts, timestamps — all
      operational metadata the vendor's compliance team needs to monitor
      chain health, expiry countdowns, and webhook delivery.
    * ``decisions`` — the signed-vote list. Reviewer names + decision
      strings are not PHI; the signatures themselves are required for
      the audit story.
    * ``reviewed_below_threshold`` — surfaces enforcement violations to
      the compliance officer; not PHI.
    """
    return {
        "id": approval.id,
        "org_id": approval.org_id,
        "request_record_id": approval.request_record_id,
        "resolution_record_id": approval.resolution_record_id,
        "requested_by_agent": approval.requested_by_agent,
        # OMITTED: data_subject_id
        "action_name": approval.action_name,
        # OMITTED: action_summary (frequent PHI carrier)
        "context": _safe_approval_context(approval.context),
        "risk_tier": approval.risk_tier,
        "approvers_required": approval.approvers_required,
        "status": approval.status,
        "decisions": approval.decisions or [],
        "requested_at": approval.requested_at,
        "expires_at": approval.expires_at,
        "resolved_at": approval.resolved_at,
        "client_review_started_at": approval.client_review_started_at,
        "decided_at": approval.decided_at,
        "webhook_sent_at": approval.webhook_sent_at,
        "callback_received_at": approval.callback_received_at,
        "reviewed_below_threshold": approval.reviewed_below_threshold,
    }


def serialize_decision_for_dashboard(
    decision: CustomerDecisionResponse,
) -> dict[str, Any]:
    """Strip PHI from a Customer Decisions feed row.

    ``services/decisions._build_ruling`` populates
    ``CustomerDecisionRuling.reason_detail`` from
    ``Approval.action_summary`` — which is a human-readable narrative
    that the clinical gates commonly write with PHI baked in
    ("Commit note for encounter MRN-31504806: 1 new diagnosis, 2
    controlled medications."). That's fine for the SDK reviewer surface
    (in-band, in-scope for the customer's BAA) but it cannot reach the
    dashboard.

    We project the response down to:

    * All operational fields (id, sequence_number, timestamps, agent/
      action names, result, webhook delivery, hitl_expires_at).
    * Ruling gate-metadata only (effect / reason / citation / review_id
      / fix_url / required_role / gate_name). ``reason_detail`` is
      nulled — that's the PHI carrier.

    Returns a dict (not the Pydantic model) so the call shape matches
    ``serialize_approval_for_dashboard``. The route's ``response_model``
    re-validates and re-shapes the dict on the way out.
    """
    payload = decision.model_dump()
    ruling = payload.get("ruling")
    if ruling is not None:
        # ``reason_detail`` comes from Approval.action_summary; null it
        # so the dashboard cannot read the narrative PHI the gate wrote
        # for the in-band reviewer.
        ruling["reason_detail"] = None
    return payload


def is_dashboard_request(api_key: object | None) -> bool:
    """Return True when the caller is a Clerk-authenticated dashboard user.

    ``require_permission`` returns ``(org_id, api_key)`` where ``api_key``
    is ``None`` for Clerk sessions and a populated ``APIKey`` row for
    legacy bearer-token callers (the SDK + any direct API consumers).

    The cleanest dashboard-vs-SDK distinction we have today. If we ever
    add a third auth method that should be treated as a dashboard
    surface, extend this predicate rather than scattering ``is None``
    checks across the route layer.
    """
    return api_key is None


__all__ = [
    "serialize_approval_for_dashboard",
    "serialize_decision_for_dashboard",
    "is_dashboard_request",
]
