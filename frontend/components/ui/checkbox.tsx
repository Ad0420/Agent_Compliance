"use client";

/**
 * Checkbox + AttestationCheckbox — Phase 1 PR 0b component primitive.
 *
 * Per `dashboard-design-system.md` §Radio / Checkbox: 16px square, 4px
 * radius, 1px ink-4 border, selected fills with ink and shows a white check.
 * Native `<input type="checkbox">` is used for first-class keyboard handling
 * (Space toggles) and AT support; the visual square is rendered as a
 * sibling `<span>` driven by `peer-checked:`.
 *
 * `AttestationCheckbox` is the red-banner attestation variant referenced by
 * Phase 1 PR 14 (5-question wizard) and Phase 4 (audit PDF "I am authorised
 * to attest to the compliance posture below"). It wraps the regular checkbox
 * in a brick-bordered banner with sticky positioning support — the consumer
 * is responsible for wrapping the banner in a sticky container if they want
 * it to remain visible while the user scrolls a long attestation document.
 */

import * as React from "react";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label?: React.ReactNode;
  description?: React.ReactNode;
  /** Apply error styling (brick border + brick text). */
  error?: boolean;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  function Checkbox(
    { label, description, error, className, id, disabled, ...rest },
    ref,
  ) {
    const generatedId = React.useId();
    const inputId = id ?? generatedId;
    const descriptionId = description ? `${inputId}-description` : undefined;

    return (
      <label
        htmlFor={inputId}
        data-slot="checkbox-row"
        className={cn(
          "group flex min-h-9 cursor-pointer items-start gap-3",
          disabled && "cursor-not-allowed opacity-50",
          className,
        )}
      >
        <span className="relative mt-0.5 inline-flex shrink-0">
          <input
            ref={ref}
            id={inputId}
            type="checkbox"
            disabled={disabled}
            aria-describedby={descriptionId}
            className="peer sr-only"
            {...rest}
          />
          <span
            aria-hidden="true"
            className={cn(
              "flex size-4 items-center justify-center rounded-[4px] border bg-[color:var(--paper-2)]",
              "transition-colors",
              error
                ? "border-[color:var(--brick)]"
                : "border-[color:var(--ink-4)]",
              "peer-checked:border-[color:var(--ink)] peer-checked:bg-[color:var(--ink)]",
              "peer-focus-visible:outline peer-focus-visible:outline-2",
              "peer-focus-visible:outline-offset-2",
              "peer-focus-visible:outline-[color:var(--ink)]",
            )}
          >
            <Check
              className={cn(
                "size-3 text-[color:var(--paper)] opacity-0 transition-opacity",
                // The check icon is a CHILD of the styled span, not a peer
                // sibling of the input, so `peer-checked:` doesn't reach
                // it. We mirror checked state via `:has(input:checked)` on
                // the outer label (Tailwind v4 `group-has-[...]` variant).
                "group-has-[input:checked]:opacity-100",
              )}
              aria-hidden="true"
              strokeWidth={3}
            />
          </span>
        </span>
        {(label || description) && (
          <span className="min-w-0 flex-1">
            {label ? (
              <span
                className={cn(
                  "block text-[14px] leading-tight",
                  error
                    ? "text-[color:var(--brick)]"
                    : "text-[color:var(--ink)]",
                )}
              >
                {label}
              </span>
            ) : null}
            {description ? (
              <span
                id={descriptionId}
                className="mt-1 block text-[13px] text-[color:var(--ink-2)] leading-snug"
              >
                {description}
              </span>
            ) : null}
          </span>
        )}
      </label>
    );
  },
);

export interface AttestationCheckboxProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /**
   * The attestation copy the user is asserting (e.g., "I am authorised to
   * attest that the compliance posture below accurately reflects this
   * deployment as of today's date."). Renders as the checkbox label.
   */
  attestation: React.ReactNode;
  /**
   * Optional supporting copy — additional context, name + role of the
   * attestor, timestamp the attestation was generated, etc.
   */
  context?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
}

/**
 * Sticky-friendly attestation banner with a brick border. Consumers wrap
 * this in a `<div className="sticky bottom-0">` (or similar) when they
 * want it pinned while the user scrolls the document being attested to.
 *
 * The banner is intentionally NOT sticky by default — sticky positioning
 * has too many context-dependent gotchas (z-index stacking, parent
 * `overflow`) to encode in the primitive.
 */
export function AttestationCheckbox({
  checked,
  onChange,
  attestation,
  context,
  disabled,
  className,
  id,
}: AttestationCheckboxProps) {
  return (
    <div
      data-slot="attestation-checkbox"
      className={cn(
        "rounded-[10px] border-2 p-4",
        "border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)]/30",
        className,
      )}
    >
      <Checkbox
        id={id}
        checked={checked}
        onChange={(e) => onChange((e.target as HTMLInputElement).checked)}
        disabled={disabled}
        label={
          <span className="font-medium text-[color:var(--ink)]">
            {attestation}
          </span>
        }
        description={context}
      />
    </div>
  );
}
