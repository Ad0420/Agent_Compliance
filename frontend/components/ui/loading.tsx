"use client";

/**
 * Loading primitives — Phase 1 PR 0b component primitive.
 *
 * Two patterns per `dashboard-design-system.md` §Loading state:
 *
 *   - `Spinner` — 12px circular indeterminate spinner in ink, for actions
 *     in the 200ms-2s window (PDF generation kick-off, AI insight request).
 *     Renders inline next to the disabled button label that triggered it.
 *
 *   - `ProgressBar` — 4px-tall paper-3 track with an ink fill, for long
 *     jobs in the 2s-30s window (CSV import, audit PDF rendering). Optional
 *     label line rendered below the bar in 12px ink-2 ("Generating PDF
 *     (3 of 7 sections)...").
 *
 * No skeleton screens — skeletons read as marketing slop per the spec.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SpinnerProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Accessible label announced to screen readers. Default "Loading". */
  label?: string;
  /** Pixel size. Default 12 (matches the spec). */
  size?: 12 | 14 | 16 | 20 | 24;
}

export function Spinner({
  label = "Loading",
  size = 12,
  className,
  ...rest
}: SpinnerProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center", className)}
      {...rest}
    >
      <svg
        aria-hidden="true"
        className="animate-spin"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeOpacity="0.18"
          strokeWidth="3"
        />
        <path
          d="M22 12a10 10 0 0 0-10-10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export interface ProgressBarProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Progress value 0-100. If omitted, renders an indeterminate bar. */
  value?: number;
  /**
   * Optional status label rendered under the bar in 12px ink-2. e.g.,
   * "Generating PDF (3 of 7 sections)…"
   */
  label?: string;
  /**
   * Required for a11y when `label` is omitted — the screen-reader-only
   * accessible name for the progress indicator.
   */
  ariaLabel?: string;
}

export function ProgressBar({
  value,
  label,
  ariaLabel,
  className,
  ...rest
}: ProgressBarProps) {
  const isIndeterminate = value === undefined;
  const clamped = isIndeterminate
    ? undefined
    : Math.max(0, Math.min(100, value));

  return (
    <div
      data-slot="progress-bar"
      className={cn("w-full", className)}
      {...rest}
    >
      <div
        role="progressbar"
        aria-label={label ?? ariaLabel ?? "Progress"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={isIndeterminate ? undefined : clamped}
        className="relative h-1 w-full overflow-hidden rounded-full bg-[color:var(--paper-3)]"
      >
        {isIndeterminate ? (
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-1/3 animate-[progress-indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-[color:var(--ink)]"
          />
        ) : (
          <span
            aria-hidden="true"
            className="block h-full rounded-full bg-[color:var(--ink)] transition-[width] duration-200 ease-out"
            style={{ width: `${clamped}%` }}
          />
        )}
      </div>
      {label ? (
        <p className="mt-2 text-[12px] text-[color:var(--ink-2)]">{label}</p>
      ) : null}
      <style jsx>{`
        @keyframes progress-indeterminate {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(300%);
          }
        }
        @media (prefers-reduced-motion: reduce) {
          span[aria-hidden="true"] {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  );
}

export const Loading = { Spinner, ProgressBar };
