"use client";

/**
 * RadioGroup + RadioOption — Phase 1 PR 0b component primitive.
 *
 * Per `dashboard-design-system.md` §Radio / Checkbox: 16px circle, 1px ink-4
 * border, paper-2 inner, 6px ink dot when selected. In option lists (PDF
 * modal Branding choice, 5-question wizard path choice) each option is a
 * row with a bold first-line label, ink-2 second-line description, 36px
 * minimum hit target, and a subtle `--paper-2` background when selected.
 *
 * The implementation uses native `<input type="radio">` for first-class
 * keyboard handling (arrow keys move selection within a `name` group,
 * space toggles) and full AT support. Visual radio is rendered as a sibling
 * `<span>` driven by CSS `peer-checked:`.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

interface RadioGroupContextValue {
  name: string;
  value: string | undefined;
  onChange: (next: string) => void;
  disabled?: boolean;
}

const RadioGroupContext = React.createContext<RadioGroupContextValue | null>(
  null,
);

export interface RadioGroupProps {
  /**
   * Stable name attribute shared by all options. Used by the browser to
   * group the radios for keyboard navigation.
   */
  name: string;
  value: string | undefined;
  onChange: (next: string) => void;
  disabled?: boolean;
  /** Accessible group label. Rendered as a visible heading by default. */
  label?: string;
  ariaLabel?: string;
  className?: string;
  children: React.ReactNode;
}

export function RadioGroup({
  name,
  value,
  onChange,
  disabled,
  label,
  ariaLabel,
  className,
  children,
}: RadioGroupProps) {
  const ctx = React.useMemo<RadioGroupContextValue>(
    () => ({ name, value, onChange, disabled }),
    [name, value, onChange, disabled],
  );

  return (
    <RadioGroupContext.Provider value={ctx}>
      <div
        role="radiogroup"
        aria-label={ariaLabel ?? label}
        className={cn("flex flex-col gap-1", className)}
      >
        {label ? (
          <p className="mb-1 text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
            {label}
          </p>
        ) : null}
        {children}
      </div>
    </RadioGroupContext.Provider>
  );
}

export interface RadioOptionProps {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
  className?: string;
}

export function RadioOption({
  value,
  label,
  description,
  disabled,
  className,
}: RadioOptionProps) {
  const ctx = React.useContext(RadioGroupContext);
  if (!ctx) {
    throw new Error("RadioOption must be rendered inside a <RadioGroup>");
  }
  const id = React.useId();
  const checked = ctx.value === value;
  const isDisabled = disabled || ctx.disabled;
  const descriptionId = description ? `${id}-description` : undefined;

  return (
    <label
      htmlFor={id}
      data-slot="radio-option"
      data-state={checked ? "checked" : "unchecked"}
      className={cn(
        "group relative flex min-h-9 cursor-pointer items-start gap-3 rounded-[10px]",
        "px-4 py-3 transition-colors",
        "hover:bg-[color:var(--paper-2)]/60",
        checked && "bg-[color:var(--paper-2)]",
        isDisabled && "cursor-not-allowed opacity-50 hover:bg-transparent",
        className,
      )}
    >
      <input
        type="radio"
        id={id}
        name={ctx.name}
        value={value}
        checked={checked}
        disabled={isDisabled}
        onChange={() => ctx.onChange(value)}
        aria-describedby={descriptionId}
        className={cn(
          "peer sr-only",
          "focus-visible:outline-none",
        )}
      />
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full",
          "border bg-[color:var(--paper-2)] transition-colors",
          checked
            ? "border-[color:var(--ink)]"
            : "border-[color:var(--ink-4)]",
          "peer-focus-visible:outline peer-focus-visible:outline-2",
          "peer-focus-visible:outline-offset-2",
          "peer-focus-visible:outline-[color:var(--ink)]",
        )}
      >
        {checked ? (
          <span className="block size-[6px] rounded-full bg-[color:var(--ink)]" />
        ) : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium text-[color:var(--ink)] leading-tight">
          {label}
        </span>
        {description ? (
          <span
            id={descriptionId}
            className="mt-1 block text-[13px] text-[color:var(--ink-2)] leading-snug"
          >
            {description}
          </span>
        ) : null}
      </span>
    </label>
  );
}
