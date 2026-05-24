"use client";

/**
 * Textarea — Phase 1 PR 0b component primitive.
 *
 * Per `dashboard-design-system.md` §Input field: same shape as the standard
 * Input — paper background, 1px ink-4 border, 8px radius, 14px Inter 400,
 * ink-3 placeholder, focus narrows to a 1px ink border + a subtle paper-2
 * inner fill. Textarea is at least 100px tall and renders a character
 * counter at bottom-right when `maxLength` is set.
 *
 * The component composes a label + textarea + (optional) help text + error
 * message + character counter, mirroring the design-system's anatomy block.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface TextareaProps
  extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "size"> {
  label?: string;
  /** Optional helper text shown under the textarea in ink-3. */
  helpText?: string;
  /** Error message — replaces helpText and applies the brick border. */
  error?: string;
  /** Hide the visible label but still wire it for AT (use with placeholder). */
  hideLabel?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    {
      label,
      helpText,
      error,
      hideLabel,
      className,
      id,
      maxLength,
      defaultValue,
      value,
      onChange,
      rows = 4,
      ...rest
    },
    ref,
  ) {
    const generatedId = React.useId();
    const fieldId = id ?? generatedId;
    const helpId = helpText ? `${fieldId}-help` : undefined;
    const errorId = error ? `${fieldId}-error` : undefined;
    const counterId = maxLength ? `${fieldId}-counter` : undefined;

    const [internalLength, setInternalLength] = React.useState(() => {
      if (typeof value === "string") return value.length;
      if (typeof defaultValue === "string") return defaultValue.length;
      return 0;
    });

    React.useEffect(() => {
      if (typeof value === "string") {
        setInternalLength(value.length);
      }
    }, [value]);

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      if (typeof value !== "string") {
        setInternalLength(e.target.value.length);
      }
      onChange?.(e);
    };

    return (
      <div className="w-full">
        {label ? (
          <label
            htmlFor={fieldId}
            className={cn(
              "mb-1.5 block text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]",
              hideLabel && "sr-only",
            )}
          >
            {label}
          </label>
        ) : null}
        <textarea
          ref={ref}
          id={fieldId}
          rows={rows}
          value={value}
          defaultValue={defaultValue}
          onChange={handleChange}
          maxLength={maxLength}
          aria-invalid={error ? true : undefined}
          aria-describedby={
            [helpId, errorId, counterId].filter(Boolean).join(" ") || undefined
          }
          className={cn(
            "block w-full min-h-[100px] resize-y rounded-[8px] border px-3 py-2",
            "bg-[color:var(--paper)] text-[14px] text-[color:var(--ink)] leading-snug",
            "placeholder:text-[color:var(--ink-3)]",
            "transition-colors",
            error
              ? "border-[color:var(--brick)]"
              : "border-[color:var(--ink-4)]",
            "focus-visible:outline-none focus-visible:border-[color:var(--ink)]",
            "focus-visible:bg-[color:var(--paper-2)]/40",
            "disabled:cursor-not-allowed disabled:bg-[color:var(--paper-3)] disabled:text-[color:var(--ink-3)]",
            className,
          )}
          {...rest}
        />
        <div className="mt-1.5 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {error ? (
              <p
                id={errorId}
                className="text-[12px] text-[color:var(--brick)]"
              >
                {error}
              </p>
            ) : helpText ? (
              <p
                id={helpId}
                className="text-[12px] text-[color:var(--ink-3)]"
              >
                {helpText}
              </p>
            ) : null}
          </div>
          {maxLength ? (
            <p
              id={counterId}
              className={cn(
                "shrink-0 text-[12px] tabular-nums text-[color:var(--ink-3)]",
                internalLength >= maxLength && "text-[color:var(--brick)]",
              )}
            >
              {internalLength}/{maxLength}
            </p>
          ) : null}
        </div>
      </div>
    );
  },
);
