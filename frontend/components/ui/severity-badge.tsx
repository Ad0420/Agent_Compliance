"use client";

/**
 * SeverityBadge — Phase 1 PR 0b component primitive.
 *
 * Small pill used to mark issue severity in Compliance insights, the
 * Recommendation card, Customer detail decision rows, and review queues.
 * Per `dashboard-design-system.md` §Severity badge: 22px tall, 6px radius
 * (rectangular pill, not full pill), uppercase 11px Inter 500 with 0.04em
 * tracking, text-only (no icon).
 *
 * Variant -> token table:
 *   HIGH   -> brick-bg / brick
 *   MEDIUM -> amber-bg / amber
 *   LOW    -> olive-bg / olive
 *   INFO   -> paper-3 / ink-2   (added for spec completeness; design-system
 *            §Severity badge defines three levels but the Recommendation
 *            card + Compliance insights spec both reference an INFO-tier
 *            for non-actionable notes — using the neutral `ink-2` pair so
 *            it never reads as a status colour.)
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export type Severity = "HIGH" | "MEDIUM" | "LOW" | "INFO";

const severityStyles: Record<Severity, string> = {
  HIGH: "bg-[color:var(--brick-bg)] text-[color:var(--brick)]",
  MEDIUM: "bg-[color:var(--amber-bg)] text-[color:var(--amber)]",
  LOW: "bg-[color:var(--olive-bg)] text-[color:var(--olive)]",
  INFO: "bg-[color:var(--paper-3)] text-[color:var(--ink-2)]",
};

export interface SeverityBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  severity: Severity;
  /**
   * Children override the default severity label. Default renders the
   * uppercase severity name itself ("HIGH", "MEDIUM", "LOW", "INFO").
   */
  children?: React.ReactNode;
}

export function SeverityBadge({
  severity,
  className,
  children,
  ...rest
}: SeverityBadgeProps) {
  return (
    <span
      data-slot="severity-badge"
      data-severity={severity}
      className={cn(
        "inline-flex h-[22px] items-center rounded-[6px] px-[10px]",
        "text-[11px] font-medium uppercase leading-none tracking-[0.04em]",
        "whitespace-nowrap",
        severityStyles[severity],
        className,
      )}
      {...rest}
    >
      {children ?? severity}
    </span>
  );
}
