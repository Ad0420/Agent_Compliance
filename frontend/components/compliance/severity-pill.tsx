"use client";

/**
 * SeverityPill — Phase 4 Wave 2 PR C2 (AI Insights surface).
 *
 * Local pill component scoped to the AI Insights surface. We don't reuse
 * the project-wide ``SeverityBadge`` here because the C2 brief pins a
 * slightly different colour mapping for the v1 insights surface:
 *
 *   HIGH   -> brick / red ink
 *   MEDIUM -> amber
 *   LOW    -> paper-3 background, ink-2 text (neutral, non-alarming —
 *             "minor drift, optional improvement" without the olive
 *             status-OK undertone the global LOW carries)
 *
 * The exported ``severityPillClasses`` map is what the test file pins
 * — if the class list drifts the test regresses and the contract
 * surface stays visible in code review. The brick / amber / paper-3
 * tokens come from ``dashboard-design-system.md`` §Severity badge.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

import type { Severity } from "@/lib/api-client";

/**
 * Tailwind class lists per severity. Exported so the test file can pin
 * the exact class strings — including the brick-foreground (``red ink``)
 * the C2 brief requires for HIGH.
 */
export const severityPillClasses: Record<Severity, string> = {
  HIGH: "bg-[color:var(--brick-bg)] text-[color:var(--brick)]",
  MEDIUM: "bg-[color:var(--amber-bg)] text-[color:var(--amber)]",
  LOW: "bg-[color:var(--paper-3)] text-[color:var(--ink-2)]",
};

export interface SeverityPillProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  severity: Severity;
}

export function SeverityPill({
  severity,
  className,
  ...rest
}: SeverityPillProps) {
  return (
    <span
      data-slot="insights-severity-pill"
      data-severity={severity}
      className={cn(
        "inline-flex h-[22px] items-center rounded-[6px] px-[10px]",
        "text-[11px] font-medium uppercase leading-none tracking-[0.04em]",
        "whitespace-nowrap",
        severityPillClasses[severity],
        className,
      )}
      {...rest}
    >
      {severity}
    </span>
  );
}
