"use client";

/**
 * Toggle (switch) — Phase 1 PR 0b component primitive.
 *
 * The Integrations / Settings / per-row enable-disable control, per
 * `dashboard-design-system.md` §Toggle (switch):
 *   - Track 36×20, 10px radius
 *   - Thumb 16px white circle with soft shadow
 *   - Off: track = `--paper-3`, On: track = `--ink`
 *   - 120ms ease-out transition
 *   - Disabled: track 50% opacity, pointer-events none
 *
 * Implemented as a `role="switch"` button so it is keyboard-toggleable via
 * Space / Enter (default `<button>` behaviour) and announced correctly by
 * AT. Pair it with an associated `<label>` via the visible label slot.
 *
 * Named `ToggleSwitch` because the existing shadcn dropdown-menu file already
 * exports a `Toggle` symbol and we want to avoid collisions; the design
 * system "Toggle" terminology is still surfaced in the component file path.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface ToggleSwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /**
   * Visible label rendered to the left of the switch. Required for a11y
   * unless `ariaLabel` is provided (icon-only / dense rows).
   */
  label?: string;
  /** Optional secondary description shown under the label in ink-2. */
  description?: string;
  /** SR-only accessible name when no visible `label` is rendered. */
  ariaLabel?: string;
  className?: string;
  id?: string;
}

export function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
  label,
  description,
  ariaLabel,
  className,
  id,
}: ToggleSwitchProps) {
  const generatedId = React.useId();
  const switchId = id ?? generatedId;
  const labelId = label ? `${switchId}-label` : undefined;
  const descriptionId = description ? `${switchId}-description` : undefined;

  const handleClick = () => {
    if (disabled) return;
    onChange(!checked);
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4",
        disabled && "opacity-50",
        className,
      )}
    >
      {(label || description) && (
        <div className="min-w-0 flex-1">
          {label ? (
            <label
              id={labelId}
              htmlFor={switchId}
              className="block cursor-pointer text-[14px] font-medium text-[color:var(--ink)]"
            >
              {label}
            </label>
          ) : null}
          {description ? (
            <p
              id={descriptionId}
              className="mt-0.5 text-[13px] text-[color:var(--ink-2)]"
            >
              {description}
            </p>
          ) : null}
        </div>
      )}
      <button
        type="button"
        role="switch"
        id={switchId}
        aria-checked={checked}
        aria-disabled={disabled || undefined}
        aria-label={ariaLabel ?? (label ? undefined : "Toggle")}
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        disabled={disabled}
        onClick={handleClick}
        data-slot="toggle-switch"
        data-state={checked ? "on" : "off"}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-[10px]",
          "transition-colors duration-[120ms] ease-out",
          checked
            ? "bg-[color:var(--ink)]"
            : "bg-[color:var(--paper-3)]",
          disabled && "cursor-not-allowed",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-[color:var(--ink)]",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none inline-block size-4 transform rounded-full bg-white",
            "shadow-[0_1px_2px_rgba(31,22,16,0.18)] transition-transform duration-[120ms] ease-out",
            checked ? "translate-x-[18px]" : "translate-x-[2px]",
          )}
        />
      </button>
    </div>
  );
}
