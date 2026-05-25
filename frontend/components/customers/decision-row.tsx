"use client";

/**
 * DecisionRow — Wave 2C PR C1.
 *
 * Single decision row inside the Customer detail → Decisions tab.
 * Composes the Phase 1 PR 0b primitives (SeverityBadge, StatusDot) with
 * Phase 2 Wave 2A/2B data (gate Ruling + webhook delivery status).
 *
 * Visual spec (per dashboard-design-system.md §Severity badge, §Status
 * indicator, §Voice & copy):
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │ [HIGH] Controlled substance — DEA review required                │
 *   │ 45 CFR 1308.12 · clinical_scribe.controlled_substance            │
 *   │ ● Webhook delivered  ·  3m ago                                   │
 *   │ Review expires in 2h 14m                                         │
 *   └──────────────────────────────────────────────────────────────────┘
 *
 * Variant routing
 * ===============
 * - Ruling.effect → SeverityBadge severity:
 *     ALLOW        → LOW   (olive)
 *     REQUIRE_HITL → MEDIUM (amber)
 *     BLOCK        → HIGH  (brick)
 *   Severity language pairs ("Allowed" / "Review required" / "Blocked")
 *   match the badge tier per the §Voice & copy manual rule.
 *
 * - DecisionWebhookStatus → StatusDot variant:
 *     delivered → ok       (olive)
 *     pending   → muted    (ink-3)
 *     retrying  → warn     (amber) + title="Retry N/7, next at HH:MM UTC"
 *     aborted   → error    (brick)
 *
 * - HITL countdown: rendered only when ruling.effect === 'require_hitl'
 *   AND hitl_expires_at is set. Uses ``formatTimeUntil`` so "expired"
 *   surfaces when the timestamp has passed (no auto-pulse — re-renders
 *   on React Query polls only).
 *
 * Copy rules enforced in this component (CLAUDE.md / dashboard-design):
 *   - No banned-marketing or banned-legalese vocabulary in user-facing
 *     strings; reviewed by ``scripts/check_copy_violations.py``.
 *   - "Customer" never "Tenant" in user-visible text.
 *   - tabular-nums on counts + timestamps for clean vertical alignment.
 */

import * as React from "react";

import { SeverityBadge, type Severity } from "@/components/ui/severity-badge";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import {
  formatAbsoluteUTC,
  formatHourMinuteUTC,
  formatRelativeTime,
  formatTimeUntil,
} from "@/lib/utils";
import type {
  CustomerDecision,
  RulingEffect,
  DecisionWebhookStatus,
} from "@/lib/api-types";

const RULING_SEVERITY: Record<RulingEffect, Severity> = {
  allow: "LOW",
  require_hitl: "MEDIUM",
  block: "HIGH",
};

// Severity-paired label per the §Voice & copy rule ("HIGH" pairs with a
// specific consequence; "MEDIUM" with Review/Recommended; "LOW" with
// Allowed/Optional). Reviewed manually in CI — script doesn't catch it.
const RULING_LABEL: Record<RulingEffect, string> = {
  allow: "Allowed",
  require_hitl: "Review required",
  block: "Blocked",
};

const DELIVERY_VARIANT: Record<DecisionWebhookStatus, StatusVariant> = {
  delivered: "ok",
  pending: "muted",
  retrying: "warn",
  aborted: "error",
};

const DELIVERY_LABEL: Record<DecisionWebhookStatus, string> = {
  delivered: "Webhook delivered",
  pending: "Webhook pending",
  retrying: "Webhook retrying",
  aborted: "Webhook delivery aborted",
};

interface DecisionRowProps {
  decision: CustomerDecision;
}

export function DecisionRow({ decision }: DecisionRowProps) {
  const {
    action_timestamp,
    agent_name,
    action_name,
    ruling,
    webhook_delivery,
    hitl_expires_at,
  } = decision;

  return (
    <li
      data-slot="decision-row"
      data-decision-id={decision.id}
      data-ruling-effect={ruling?.effect ?? "none"}
      className="space-y-2 border-b border-[color:var(--ink-4)] px-4 py-4 last:border-b-0"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        {ruling ? (
          <SeverityBadge
            severity={RULING_SEVERITY[ruling.effect]}
            aria-label={`Ruling: ${RULING_LABEL[ruling.effect]}`}
            data-testid="decision-row-ruling-badge"
          >
            {RULING_LABEL[ruling.effect]}
          </SeverityBadge>
        ) : (
          <SeverityBadge
            severity="INFO"
            aria-label="No gate evaluated this decision"
            data-testid="decision-row-ruling-badge"
          >
            No gate
          </SeverityBadge>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-medium text-[color:var(--ink)] leading-snug">
            {ruling?.reason_detail ?? action_name}
          </p>
          {ruling?.citation || ruling?.gate_name ? (
            <p className="mt-0.5 text-[12px] text-[color:var(--ink-2)]">
              {ruling?.citation ? <span>{ruling.citation}</span> : null}
              {ruling?.citation && ruling?.gate_name ? (
                <span aria-hidden="true"> · </span>
              ) : null}
              {ruling?.gate_name ? <span>{ruling.gate_name}</span> : null}
            </p>
          ) : null}
        </div>
        <time
          dateTime={action_timestamp}
          title={formatAbsoluteUTC(action_timestamp)}
          className="shrink-0 text-[12px] text-[color:var(--ink-3)] tabular-nums"
        >
          {formatRelativeTime(action_timestamp)}
        </time>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-1 text-[12px] text-[color:var(--ink-2)]">
        <span className="tabular-nums" data-testid="decision-row-agent">
          {agent_name}
        </span>
        {webhook_delivery ? (
          <span data-testid="decision-row-webhook">
            <StatusDot
              variant={DELIVERY_VARIANT[webhook_delivery.status]}
              label={DELIVERY_LABEL[webhook_delivery.status]}
              title={_deliveryTooltip(webhook_delivery)}
            />
          </span>
        ) : null}
        {ruling?.effect === "require_hitl" && hitl_expires_at ? (
          <span
            className="tabular-nums text-[color:var(--ink-2)]"
            data-testid="decision-row-hitl-countdown"
          >
            Review{" "}
            {formatTimeUntil(hitl_expires_at) === "expired"
              ? "expired"
              : `expires ${formatTimeUntil(hitl_expires_at)}`}
          </span>
        ) : null}
        {ruling?.effect === "require_hitl" && ruling.required_role ? (
          <span className="text-[color:var(--ink-3)]">
            Reviewer: {ruling.required_role}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function _deliveryTooltip(
  d: NonNullable<CustomerDecision["webhook_delivery"]>,
): string | undefined {
  if (d.status === "retrying" && d.next_retry_at) {
    return `Retry ${d.attempt_count}/${d.max_attempts}, next at ${formatHourMinuteUTC(d.next_retry_at)}`;
  }
  if (d.status === "aborted" && d.aborted_at) {
    return `Aborted after ${d.attempt_count} attempts on ${formatAbsoluteUTC(d.aborted_at)}`;
  }
  if (d.status === "delivered" && d.succeeded_at) {
    return `Delivered ${formatAbsoluteUTC(d.succeeded_at)}`;
  }
  if (d.status === "pending") {
    return "Queued for first attempt";
  }
  return undefined;
}
