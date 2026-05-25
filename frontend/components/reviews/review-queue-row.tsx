"use client";

/**
 * ReviewQueueRow — Wave 2D PR C2.
 *
 * Single row in the org-wide Review queue table (Compliance → Reviews).
 * Composes the Phase 1 PR 0b primitives (SeverityBadge, StatusDot) with
 * Wave 2B context (Approval.context.gate_name / required_role) and the
 * Wave 2C HITL countdown.
 *
 * Visual spec (matches dashboard-design-system.md §Table row + §Severity
 * badge + §Voice & copy):
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │ [HIGH]  3m ago      patient-1234       scribe-v3                 │
 *   │         2026-05-25  attending_physician                          │
 *   │                     add_diagnosis  ·  new_diagnosis              │
 *   │                     Expires in 2h 14m                            │
 *   └──────────────────────────────────────────────────────────────────┘
 *
 * Risk-tier → SeverityBadge mapping (mirrors RiskTier):
 *   critical → HIGH    (brick — irreversible, e.g. controlled substance)
 *   high     → HIGH    (brick)
 *   medium   → MEDIUM  (amber)
 *   low      → LOW     (olive)
 */

import * as React from "react";

import { SeverityBadge, type Severity } from "@/components/ui/severity-badge";
import {
  formatAbsoluteUTC,
  formatRelativeTime,
  formatTimeUntil,
} from "@/lib/utils";
import type { Approval, RiskTier } from "@/lib/api-types";

const RISK_SEVERITY: Record<RiskTier, Severity> = {
  critical: "HIGH",
  high: "HIGH",
  medium: "MEDIUM",
  low: "LOW",
};

const RISK_LABEL: Record<RiskTier, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  medium: "MEDIUM",
  low: "LOW",
};

export interface ReviewQueueRowProps {
  approval: Approval;
  /**
   * Display name resolved from the Approval's ``data_subject_id``. The
   * caller (ReviewQueueTable) does the customer-id → display-name
   * mapping once via a lookup so the row stays presentational.
   */
  customerDisplayName?: string | null;
  /** Whether this row is the currently-selected detail row. */
  selected?: boolean;
  /** Clicked-row callback — opens the detail panel. */
  onSelect?: (approval: Approval) => void;
}

/**
 * Extract gate_name from Approval.context. Wave 2B PR A2 stashes the
 * gate identifier there alongside ``required_role``; missing in
 * pre-A2 approvals (treat as "—" so the cell is visually quiet rather
 * than blank).
 */
function gateNameOf(context: Record<string, unknown>): string | null {
  const v = context.gate_name;
  return typeof v === "string" && v.length > 0 ? v : null;
}

function requiredRoleOf(context: Record<string, unknown>): string | null {
  const v = context.required_role;
  return typeof v === "string" && v.length > 0 ? v : null;
}

export function ReviewQueueRow({
  approval,
  customerDisplayName,
  selected,
  onSelect,
}: ReviewQueueRowProps) {
  const gateName = gateNameOf(approval.context);
  const requiredRole = requiredRoleOf(approval.context);
  const customerLabel =
    customerDisplayName ??
    approval.data_subject_id ??
    // Fallback so the column never collapses; "—" reads as "no data subject
    // captured" per dashboard-design-system.md §Voice & copy.
    "—";

  const handleClick = () => onSelect?.(approval);
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(approval);
    }
  };

  return (
    <tr
      data-slot="review-queue-row"
      data-review-id={approval.id}
      data-risk-tier={approval.risk_tier}
      data-selected={selected || undefined}
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      aria-selected={selected || undefined}
      className={
        "cursor-pointer border-b border-[color:var(--ink-4)] " +
        "transition-colors hover:bg-[color:var(--paper-2)] " +
        "focus-visible:outline focus-visible:outline-2 " +
        "focus-visible:outline-offset-[-2px] focus-visible:outline-[color:var(--ink)] " +
        (selected ? "bg-[color:var(--paper-2)]" : "bg-[color:var(--paper)]")
      }
    >
      <td className="px-3 py-3 align-top">
        <SeverityBadge
          severity={RISK_SEVERITY[approval.risk_tier]}
          aria-label={`Risk tier: ${RISK_LABEL[approval.risk_tier]}`}
          data-testid="review-queue-row-risk-badge"
        >
          {RISK_LABEL[approval.risk_tier]}
        </SeverityBadge>
      </td>
      <td className="px-3 py-3 align-top">
        <time
          dateTime={approval.requested_at}
          title={formatAbsoluteUTC(approval.requested_at)}
          className="text-[13px] text-[color:var(--ink)] tabular-nums"
        >
          {formatRelativeTime(approval.requested_at)}
        </time>
        <div className="mt-0.5 text-[11px] text-[color:var(--ink-3)] tabular-nums">
          {formatAbsoluteUTC(approval.requested_at)}
        </div>
      </td>
      <td
        className="px-3 py-3 align-top text-[13px] text-[color:var(--ink)]"
        data-testid="review-queue-row-customer"
      >
        {customerLabel}
      </td>
      <td
        className="px-3 py-3 align-top text-[13px] text-[color:var(--ink-2)]"
        data-testid="review-queue-row-agent"
      >
        {approval.requested_by_agent}
      </td>
      <td
        className="px-3 py-3 align-top text-[13px] text-[color:var(--ink)]"
        data-testid="review-queue-row-action"
      >
        {approval.action_name}
      </td>
      <td
        className="px-3 py-3 align-top text-[13px] text-[color:var(--ink-2)]"
        data-testid="review-queue-row-gate"
      >
        {gateName ?? "—"}
      </td>
      <td
        className="px-3 py-3 align-top text-[13px] text-[color:var(--ink-2)]"
        data-testid="review-queue-row-role"
      >
        {requiredRole ?? "—"}
      </td>
      <td className="px-3 py-3 align-top text-[13px] tabular-nums">
        {approval.expires_at ? (
          <span
            className={
              formatTimeUntil(approval.expires_at) === "expired"
                ? "text-[color:var(--brick)]"
                : "text-[color:var(--ink-2)]"
            }
            title={formatAbsoluteUTC(approval.expires_at)}
            data-testid="review-queue-row-expiry"
          >
            {formatTimeUntil(approval.expires_at) === "expired"
              ? "Expired"
              : formatTimeUntil(approval.expires_at)}
          </span>
        ) : (
          <span className="text-[color:var(--ink-3)]">No expiry</span>
        )}
      </td>
    </tr>
  );
}
