/**
 * SessionStep — vertical pipeline step for the live triage progress feed.
 *
 * The Wave 2 view-layer agent will compose these into a vertical timeline
 * showing the steps of a single triage session:
 *   1. Patient submits symptoms
 *   2. AI assesses, recommends a care level (self-care / virtual / urgent / ER)
 *   3. Red-flag terms detected → policy holds for nurse review
 *   4. Nurse reviews, confirms or overrides
 *   5. Patient sees the (escalated) recommendation
 *
 * States:
 *   idle     -> hairline outline, muted ink (not started)
 *   active   -> teal rail, pulsing dot (currently running) — color + label
 *               carry the state, the pulse is decoration only
 *   done     -> moss rail, static check (completed)
 *   blocked  -> crimson rail, exclamation (blocked on review or escalation)
 *
 * The connector rail is rendered via the wrapper — the last step in a
 * column should pass `isLast` to suppress it.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

export type SessionStepState = "idle" | "active" | "done" | "blocked";

export interface SessionStepProps {
  state: SessionStepState;
  label: string;
  sublabel?: string;
  /** Free-form payload (e.g. detected red-flag terms, AI level pill). */
  payload?: React.ReactNode;
  /** Hide the trailing connector. Set true on the final step. */
  isLast?: boolean;
  className?: string;
}

const stateStyles: Record<
  SessionStepState,
  {
    rail: string;
    dot: string;
    dotInner: string;
    label: string;
    icon: React.ReactNode;
    pulse: boolean;
  }
> = {
  idle: {
    rail: "bg-[var(--hairline)]",
    dot: "bg-[var(--paper-2)] ring-1 ring-[var(--hairline)]",
    dotInner: "bg-[var(--ink-4)]",
    label: "text-[var(--ink-3)]",
    icon: null,
    pulse: false,
  },
  active: {
    rail: "bg-[var(--teal)]",
    dot: "bg-[var(--teal-soft)] ring-2 ring-[var(--teal)]",
    dotInner: "bg-[var(--teal)]",
    label: "text-[var(--ink)] font-medium",
    icon: null,
    pulse: true,
  },
  done: {
    rail: "bg-[var(--moss)]",
    dot: "bg-[var(--moss)] ring-2 ring-[var(--moss-soft)]",
    dotInner: "bg-white",
    label: "text-[var(--ink-2)]",
    icon: <CheckIcon />,
    pulse: false,
  },
  blocked: {
    rail: "bg-[var(--crimson)]",
    dot: "bg-[var(--crimson)] ring-2 ring-[var(--crimson-soft)]",
    dotInner: "bg-white",
    label: "text-[var(--ink)] font-medium",
    icon: <ExclamationIcon />,
    pulse: false,
  },
};

export function SessionStep({
  state,
  label,
  sublabel,
  payload,
  isLast,
  className,
}: SessionStepProps) {
  const s = stateStyles[state];

  return (
    <div className={cn("flex gap-4 relative", className)}>
      {/* Marker column — dot + connector rail */}
      <div className="relative flex flex-col items-center pt-0.5">
        <span
          className={cn(
            "relative flex size-6 items-center justify-center rounded-full",
            s.dot,
            s.pulse && "triage-pulse",
          )}
          aria-hidden
        >
          {s.icon ? (
            <span className="text-white">{s.icon}</span>
          ) : (
            <span className={cn("size-2 rounded-full", s.dotInner)} />
          )}
        </span>
        {!isLast && (
          <span
            aria-hidden
            className={cn("flex-1 w-px mt-1.5 mb-1.5 min-h-6", s.rail)}
          />
        )}
      </div>

      {/* Body */}
      <div className={cn("flex-1 pb-6", isLast && "pb-0")}>
        <div className={cn("font-sans text-sm leading-snug", s.label)}>
          {label}
        </div>
        {sublabel && (
          <div className="mt-0.5 font-sans text-xs text-[var(--ink-3)]">
            {sublabel}
          </div>
        )}
        {payload && (
          <div className="mt-2.5 rounded-lg bg-[var(--paper-2)] px-3 py-2 font-sans text-xs text-[var(--ink-2)] leading-relaxed">
            {payload}
          </div>
        )}
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden
    >
      <path
        d="M2.5 6.2L4.7 8.4L9.5 3.6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ExclamationIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
      <rect x="5.25" y="2.5" width="1.5" height="4" rx="0.5" fill="currentColor" />
      <rect x="5.25" y="7.5" width="1.5" height="1.6" rx="0.5" fill="currentColor" />
    </svg>
  );
}
