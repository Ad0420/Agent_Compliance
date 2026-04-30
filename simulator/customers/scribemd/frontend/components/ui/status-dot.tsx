/**
 * StatusDot — live status indicator for a long-running operation.
 *
 * States:
 *   running   -> cobalt, gentle pulse (encounter is being processed)
 *   waiting   -> amber, static (queued / waiting on human approval)
 *   committed -> sage, static (chart entry committed)
 *   error     -> coral, static (something broke)
 *
 * Used by the topbar (live status of the active encounter), the encounter
 * pipeline, and the agent activity feed. Pulse uses the `scribemd-pulse`
 * keyframe defined in globals.css.
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
    running: { bg: "var(--cobalt)", ring: "rgba(46,91,216,0.32)", pulse: true },
    waiting: { bg: "var(--amber)", ring: "rgba(194,65,12,0.28)", pulse: false },
    committed: { bg: "var(--sage)", ring: "rgba(79,124,90,0.28)", pulse: false },
    error: { bg: "var(--coral)", ring: "rgba(180,35,24,0.32)", pulse: false },
  };

const labelDefaults: Record<StatusKind, string> = {
  running: "Processing",
  waiting: "Waiting",
  committed: "Committed",
  error: "Error",
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
            className={cn("absolute inset-0 rounded-full scribemd-pulse")}
            style={{ boxShadow: "0 0 0 0 transparent" }}
          />
        )}
      </span>
      <span>{text}</span>
    </span>
  );
}
