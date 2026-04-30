/**
 * StatusDot — live status indicator for a long-running operation.
 *
 * States:
 *   running   -> teal, gentle pulse (case is being processed by the agent)
 *   waiting   -> amber, static (queued / waiting on nurse approval)
 *   committed -> moss, static (decision recorded, case closed)
 *   error     -> crimson, static (something broke or escalation failed)
 *
 * The pulse is decoration only — color and label always communicate the same
 * thing (so `prefers-reduced-motion` users lose nothing). The pulse itself
 * is suppressed at the CSS layer when reduced-motion is preferred.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

export type StatusKind = "running" | "waiting" | "committed" | "error";

export interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  status: StatusKind;
  /** Show a textual label next to the dot. */
  label?: string;
  size?: "sm" | "md";
}

const palette: Record<StatusKind, { bg: string; ring: string; pulse: boolean }> =
  {
    running: { bg: "var(--teal)", ring: "rgba(15,118,110,0.32)", pulse: true },
    waiting: { bg: "var(--amber)", ring: "rgba(146,64,14,0.28)", pulse: false },
    committed: { bg: "var(--moss)", ring: "rgba(47,106,61,0.28)", pulse: false },
    error: { bg: "var(--crimson)", ring: "rgba(185,28,28,0.32)", pulse: false },
  };

const labelDefaults: Record<StatusKind, string> = {
  running: "Processing",
  waiting: "Waiting on nurse",
  committed: "Recorded",
  error: "Failed",
};

export function StatusDot({
  status,
  label,
  size = "md",
  className,
  ...rest
}: StatusDotProps) {
  const p = palette[status];
  const dotSize = size === "sm" ? "size-2" : "size-2.5";
  const text = label ?? labelDefaults[status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-sans text-sm text-[var(--ink-2)]",
        className,
      )}
      {...rest}
    >
      <span className="relative inline-flex">
        <span
          aria-hidden
          className={cn("rounded-full", dotSize)}
          style={{
            backgroundColor: p.bg,
            boxShadow: `0 0 0 3px ${p.ring}`,
          }}
        />
        {p.pulse && (
          <span
            aria-hidden
            className={cn("absolute inset-0 rounded-full triage-pulse")}
            style={{ boxShadow: "0 0 0 0 transparent" }}
          />
        )}
      </span>
      <span>{text}</span>
    </span>
  );
}
