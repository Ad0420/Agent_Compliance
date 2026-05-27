"use client";

/**
 * AwaitingDataRow — Phase 4 Wave 2 PR C1.
 *
 * Collapsed-by-default row reading "X dimensions awaiting data" with
 * an expand toggle. When expanded, lists each ``not_yet_eligible[]``
 * item with its threshold-context badge and the
 * "Needs N <unit> · has M" line.
 *
 * Voice: descriptive ("Needs 10 HITL events · has 2"), never
 * imperative ("Add more HITL events"). The badge text is pulled from
 * the backend's ``threshold`` / dimension name — never hardcoded —
 * so a backend rename can't drift the dashboard.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import type { ComplianceDimensionName, NotYetEligibleDimension } from "@/lib/api-client";
import { DIMENSION_LABELS } from "./measured-dimension-card";

/**
 * Human-readable unit label per dimension, used by the
 * "Needs N <unit> · has M" line. Pinned alongside the dimension
 * names so adding a new dimension is a deliberate compile-time
 * decision rather than a missing-key runtime drift.
 */
export const DIMENSION_UNITS: Record<ComplianceDimensionName, string> = {
  artifact_freshness: "artifacts",
  hitl_completion: "HITL events",
  reviewer_integrity: "reviewer decisions",
  notice_delivery_rate: "notice deliveries",
  chain_integrity: "checkpoints",
  workflow_timeliness: "workflow events",
};

/** Comma-separated integer per dashboard voice spec. */
function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export interface AwaitingDataRowProps {
  items: NotYetEligibleDimension[];
  /** When true the row starts expanded. Defaults to ``false``. */
  defaultExpanded?: boolean;
}

export function AwaitingDataRow({
  items,
  defaultExpanded = false,
}: AwaitingDataRowProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded);

  if (items.length === 0) return null;

  const count = items.length;

  return (
    <section
      data-testid="awaiting-data-row"
      data-expanded={expanded ? "true" : "false"}
      className="rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)]"
    >
      <button
        type="button"
        data-testid="awaiting-data-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-5 py-3 text-left",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
        )}
      >
        <span className="inline-flex items-center gap-2 text-[14px] text-[color:var(--ink)]">
          <span
            aria-hidden="true"
            className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--ink-3)]"
          />
          <span className="tabular-nums">{formatCount(count)}</span>{" "}
          {count === 1 ? "dimension" : "dimensions"} awaiting data
        </span>
        <span
          aria-hidden="true"
          className="text-[12px] text-[color:var(--ink-2)]"
        >
          {expanded ? "Hide" : "Show"}
        </span>
      </button>
      {expanded && (
        <ul
          data-testid="awaiting-data-list"
          className="divide-y divide-[color:var(--ink-4)] border-t border-[color:var(--ink-4)]"
        >
          {items.map((item) => (
            <li
              key={item.name}
              data-testid="awaiting-data-item"
              data-dimension={item.name}
              className="space-y-2 px-5 py-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[14px] font-medium text-[color:var(--ink)]">
                  {DIMENSION_LABELS[item.name]}
                </p>
                <span
                  data-testid="awaiting-data-threshold-badge"
                  className="rounded-full bg-[color:var(--paper-3)] px-2 py-0.5 text-[11px] uppercase tracking-[0.08em] text-[color:var(--ink-2)] tabular-nums"
                >
                  {DIMENSION_UNITS[item.name]} ≥{" "}
                  {formatCount(item.threshold)}
                </span>
              </div>
              <p className="text-[13px] text-[color:var(--ink-2)]">
                {item.reason}
              </p>
              <p
                data-testid="awaiting-data-progress"
                className="text-[13px] text-[color:var(--ink-2)] tabular-nums"
              >
                Needs{" "}
                <span className="font-semibold text-[color:var(--ink)]">
                  {formatCount(item.needed)}
                </span>{" "}
                {DIMENSION_UNITS[item.name]}
                {" · "}
                has{" "}
                <span className="font-semibold text-[color:var(--ink)]">
                  {formatCount(item.current)}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
