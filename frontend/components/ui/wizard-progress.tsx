"use client";

/**
 * WizardProgress — Phase 1 PR 0b component primitive.
 *
 * Dot indicator for N-step wizards. Phase 1 PR 14 uses this for the 5-question
 * wizard; future phases reuse it for the audit-PDF builder, customer-onboarding
 * wizard, and template-generation flow.
 *
 * Behaviour:
 *   - Renders `totalSteps` 8px dots in a horizontal row, 12px gap.
 *   - Steps before `currentStep` (zero-indexed) are filled ink.
 *   - The `currentStep` dot is filled ink AND ringed (visual focus).
 *   - Steps after `currentStep` are paper-3.
 *   - Includes a `Step N of M` accessible label (sr-only by default; pass
 *     `showLabel` to render it visibly).
 *
 * The dots are not interactive by default — passing `onStepClick` makes
 * each prior step a button (skip-back-to-step). Forward navigation must go
 * through the wizard's own validation, so future-step dots are never
 * clickable even when `onStepClick` is provided.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface WizardProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  totalSteps: number;
  /** Zero-indexed current step. */
  currentStep: number;
  /** Optional click handler for prior-step navigation. */
  onStepClick?: (stepIndex: number) => void;
  /** Show "Step N of M" visibly. Default false (sr-only). */
  showLabel?: boolean;
  /** Override the accessible label format. */
  labelFormat?: (current: number, total: number) => string;
}

export function WizardProgress({
  totalSteps,
  currentStep,
  onStepClick,
  showLabel = false,
  labelFormat = (current, total) => `Step ${current + 1} of ${total}`,
  className,
  ...rest
}: WizardProgressProps) {
  const safeCurrent = Math.max(0, Math.min(totalSteps - 1, currentStep));
  const labelText = labelFormat(safeCurrent, totalSteps);

  return (
    <div
      data-slot="wizard-progress"
      role="group"
      aria-label={labelText}
      className={cn("flex items-center gap-3", className)}
      {...rest}
    >
      <ol className="flex items-center gap-3">
        {Array.from({ length: totalSteps }, (_, i) => {
          const isCompleted = i < safeCurrent;
          const isCurrent = i === safeCurrent;
          const isClickable = !!onStepClick && i < safeCurrent;

          const dot = (
            <span
              aria-hidden="true"
              className={cn(
                "block size-2 rounded-full transition-colors",
                isCompleted && "bg-[color:var(--ink)]",
                isCurrent && "bg-[color:var(--ink)] ring-2 ring-[color:var(--ink)] ring-offset-2 ring-offset-[color:var(--paper)]",
                !isCompleted && !isCurrent && "bg-[color:var(--paper-3)]",
              )}
            />
          );

          return (
            <li key={i} className="inline-flex">
              {isClickable ? (
                <button
                  type="button"
                  onClick={() => onStepClick?.(i)}
                  aria-label={`Go back to step ${i + 1}`}
                  aria-current={isCurrent ? "step" : undefined}
                  className={cn(
                    "inline-flex size-5 items-center justify-center rounded-full",
                    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                    "focus-visible:outline-[color:var(--ink)]",
                  )}
                >
                  {dot}
                </button>
              ) : (
                <span
                  aria-current={isCurrent ? "step" : undefined}
                  className="inline-flex size-5 items-center justify-center"
                >
                  {dot}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      <span
        className={cn(
          "text-[12px] text-[color:var(--ink-2)] tabular-nums",
          !showLabel && "sr-only",
        )}
      >
        {labelText}
      </span>
    </div>
  );
}
