"use client";

/**
 * CoverageSection — Phase 4 Wave 2 PR C1.
 *
 * Renders above the posture composite headline. The single sentence
 * answers: "of all the AI agents this org runs, how many are sending
 * runtime data into Vera?" — the prerequisite for posture being
 * meaningful at all.
 *
 * Voice: "Customer" not "Tenant", comma-separated numbers, never
 * "score". The chip strip is a horizontal row of agent_type pills; a
 * green dot indicates the agent has runtime data flowing, paper-3 dot
 * indicates it was detected (declared / auto-discovered / imported)
 * but no decisions are landing yet.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import type { Coverage } from "@/lib/api-client";

export interface CoverageSectionProps {
  coverage: Coverage;
}

/** Comma-separated integer per dashboard voice spec. */
function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function CoverageSection({ coverage }: CoverageSectionProps) {
  const { covered, detected, items } = coverage;

  if (detected === 0) {
    return (
      <section
        data-testid="coverage-section"
        data-empty="true"
        className="space-y-2"
      >
        <p className="text-[13px] uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
          Coverage
        </p>
        <p className="text-[15px] text-[color:var(--ink)]">
          No AI agents detected for this org yet.
        </p>
      </section>
    );
  }

  return (
    <section data-testid="coverage-section" className="space-y-3">
      <p className="text-[13px] uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
        Coverage
      </p>
      <p className="text-[15px] text-[color:var(--ink)]">
        Runtime posture covers{" "}
        <span className="font-semibold tabular-nums">
          {formatCount(covered)}
        </span>{" "}
        of{" "}
        <span className="font-semibold tabular-nums">
          {formatCount(detected)}
        </span>{" "}
        active AI agents.
      </p>
      <ul
        data-testid="coverage-chip-strip"
        className="flex flex-wrap items-center gap-2"
      >
        {items.map((chip) => (
          <li
            key={chip.agent_type}
            data-status={chip.status}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border border-[color:var(--ink-4)] px-3 py-1 text-[12px]",
              chip.status === "covered"
                ? "bg-[color:var(--paper-2)] text-[color:var(--ink)]"
                : "bg-[color:var(--paper-3)] text-[color:var(--ink-2)]",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                chip.status === "covered"
                  ? "bg-[color:var(--olive)]"
                  : "bg-[color:var(--ink-3)]",
              )}
            />
            <span>{chip.agent_type}</span>
            <span className="sr-only">
              {chip.status === "covered"
                ? " (covered)"
                : " (detected, no runtime data)"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
