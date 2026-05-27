"use client";

/**
 * MeasuredDimensionCard — Phase 4 Wave 2 PR C1.
 *
 * One card per dimension in ``CompliancePostureResponse.measured[]``.
 * The asymmetric posture layout is deliberate: no bar charts, no
 * gauges, no sparklines (per dashboard-design-system.md and Phase 4
 * gate decision #28). The card shows three things only:
 *
 *   1. A status dot + dimension label (top row).
 *   2. The integer score, ``--display-3`` size, ``tabular-nums``, with
 *      a percent suffix (middle).
 *   3. The ``measured_fact_line`` string rendered verbatim from the
 *      backend (bottom, ``--ink-2`` smaller text).
 *
 * Status thresholds are pinned in the exported ``scoreVariant`` helper
 * so tests can lock the boundary behaviour without re-importing the
 * component module.
 */

import * as React from "react";

import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import type { ComplianceDimensionName, MeasuredDimension } from "@/lib/api-client";

/**
 * Map a 0..100 score to a status variant. Pinned boundaries per the
 * Phase 4 brief: ≥80 ok, 50..79 warn, <50 error.
 */
export function scoreVariant(score: number): StatusVariant {
  if (score >= 80) return "ok";
  if (score >= 50) return "warn";
  return "error";
}

/** Human-readable dimension labels. Mirrors the backend's literal names. */
export const DIMENSION_LABELS: Record<ComplianceDimensionName, string> = {
  artifact_freshness: "Artifact freshness",
  hitl_completion: "HITL completion",
  reviewer_integrity: "Reviewer integrity",
  notice_delivery_rate: "Notice delivery rate",
  chain_integrity: "Chain integrity",
  workflow_timeliness: "Workflow timeliness",
};

export interface MeasuredDimensionCardProps {
  dimension: MeasuredDimension;
}

export function MeasuredDimensionCard({
  dimension,
}: MeasuredDimensionCardProps) {
  const variant = scoreVariant(dimension.score);
  const label = DIMENSION_LABELS[dimension.name];

  return (
    <article
      data-testid="measured-dimension-card"
      data-dimension={dimension.name}
      data-variant={variant}
      className={cn(
        "flex flex-col gap-3 rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-5",
        "shadow-[var(--shadow-1)]",
      )}
    >
      <StatusDot variant={variant} label={label} />
      <p
        data-testid="measured-dimension-score"
        className="font-display text-4xl font-normal leading-none tabular-nums text-[color:var(--ink)]"
      >
        {dimension.score}
        <span className="ml-1 text-2xl text-[color:var(--ink-2)]">%</span>
      </p>
      <p
        data-testid="measured-dimension-fact-line"
        className="text-[13px] leading-snug text-[color:var(--ink-2)] tabular-nums"
      >
        {dimension.measured_fact_line}
      </p>
    </article>
  );
}
