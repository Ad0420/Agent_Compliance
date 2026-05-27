"use client";

/**
 * CompositeHeadline — Phase 4 Wave 2 PR C1.
 *
 * Renders the single-sentence headline from
 * ``CompliancePostureResponse.composite_headline`` ("Runtime posture:
 * N of 6 dimensions measured") next to the window selector
 * (7/30/90 days). The headline string comes from the backend verbatim
 * — voice & copy lives in the producer.
 *
 * The window selector is a plain ``<select>``: shadcn's Select wraps a
 * Radix popover and would over-engineer a three-option control. A
 * native select renders identically across browsers, is keyboard-
 * accessible by construction, and inherits the page focus ring.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export const COMPLIANCE_WINDOW_OPTIONS = [7, 30, 90] as const;
export type ComplianceWindowDays = (typeof COMPLIANCE_WINDOW_OPTIONS)[number];

export function isComplianceWindowOption(
  n: number,
): n is ComplianceWindowDays {
  return (COMPLIANCE_WINDOW_OPTIONS as readonly number[]).includes(n);
}

export interface CompositeHeadlineProps {
  headline: string;
  windowDays: ComplianceWindowDays;
  onWindowChange: (days: ComplianceWindowDays) => void;
}

export function CompositeHeadline({
  headline,
  windowDays,
  onWindowChange,
}: CompositeHeadlineProps) {
  return (
    <div
      data-testid="composite-headline"
      className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center"
    >
      <h2
        className={cn(
          "font-display text-2xl font-normal leading-tight text-[color:var(--ink)] sm:text-3xl",
        )}
      >
        {headline}
      </h2>
      <label className="inline-flex items-center gap-2 text-[12px] text-[color:var(--ink-2)]">
        <span className="uppercase tracking-[0.1em]">Window</span>
        <select
          data-testid="composite-headline-window"
          value={windowDays}
          onChange={(e) => {
            const parsed = Number(e.target.value);
            if (isComplianceWindowOption(parsed)) {
              onWindowChange(parsed);
            }
          }}
          className={cn(
            "rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] px-2 py-1 text-[13px] tabular-nums text-[color:var(--ink)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
          )}
        >
          {COMPLIANCE_WINDOW_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt} days
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
