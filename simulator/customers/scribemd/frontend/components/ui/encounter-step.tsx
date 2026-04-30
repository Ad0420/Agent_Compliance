/**
 * EncounterStep — vertical pipeline step for the live agent progress feed.
 *
 * The Wave 2 agent will compose these into a vertical timeline showing what
 * ScribeMD is doing for the current encounter:
 *   1. Listening to room audio
 *   2. Drafting SOAP note
 *   3. Extracting orders
 *   4. Awaiting clinician sign-off
 *   5. Committing to the chart
 *
 * States:
 *   idle     -> hairline outline, muted ink (not started)
 *   active   -> cobalt rail, pulsing dot (currently running)
 *   done     -> sage rail, static check (completed)
 *   blocked  -> coral rail (blocked on review or hard error)
 *
 * The connector rail is rendered via the wrapper — the last step in a column
 * should pass `isLast` to suppress it.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

export type EncounterStepState = "idle" | "active" | "done" | "blocked";

export interface EncounterStepProps {
  state: EncounterStepState;
  label: string;
  sublabel?: string;
  /** Free-form payload (e.g. snippet of generated note, count of orders). */
  payload?: React.ReactNode;
  /** Hide the trailing connector. Set true on the final step. */
  isLast?: boolean;
  className?: string;
}

const stateStyles: Record<
  EncounterStepState,
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
    rail: "bg-[var(--cobalt)]",
    dot: "bg-[var(--cobalt-soft)] ring-2 ring-[var(--cobalt)]",
    dotInner: "bg-[var(--cobalt)]",
    label: "text-[var(--ink)] font-medium",
    icon: null,
    pulse: true,
  },
  done: {
    rail: "bg-[var(--sage)]",
    dot: "bg-[var(--sage)] ring-2 ring-[var(--sage-soft)]",
    dotInner: "bg-white",
    label: "text-[var(--ink-2)]",
    icon: <CheckIcon />,
    pulse: false,
  },
  blocked: {
    rail: "bg-[var(--coral)]",
    dot: "bg-[var(--coral)] ring-2 ring-[var(--coral-soft)]",
    dotInner: "bg-white",
    label: "text-[var(--ink)] font-medium",
    icon: <ExclamationIcon />,
    pulse: false,
  },
};

export function EncounterStep({
  state,
  label,
  sublabel,
  payload,
  isLast,
  className,
}: EncounterStepProps) {
  const s = stateStyles[state];

  return (
    <div className={cn("flex gap-4 relative", className)}>
      {/* Marker column — dot + connector rail */}
      <div className="relative flex flex-col items-center pt-0.5">
        <span
          className={cn(
            "relative flex size-6 items-center justify-center rounded-full",
            s.dot,
            s.pulse && "scribemd-pulse",
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
          <div className="mt-2.5 rounded-xl bg-[var(--paper-2)] px-3 py-2 font-sans text-xs text-[var(--ink-2)] leading-relaxed">
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
