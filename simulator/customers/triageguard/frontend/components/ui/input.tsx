/**
 * Input — single-line text field with an inset shadow + teal focus ring.
 *
 * The hairline border + inset shadow combination is the TriageGuard "case
 * file" treatment — the field reads as a slot pressed into a worksheet, not
 * a floating control.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => {
    return (
      <input
        ref={ref}
        type={type}
        className={cn(
          "flex h-10 w-full rounded-xl px-3.5 py-2",
          "bg-[var(--surface)] text-[var(--ink)]",
          "border border-[var(--hairline)]",
          "shadow-[inset_0_1px_2px_rgba(14,26,26,0.06)]",
          "font-sans text-sm placeholder:text-[var(--ink-4)]",
          "transition-colors",
          "focus:outline-none focus:border-[var(--teal)]",
          "focus:ring-4 focus:ring-[rgba(15,118,110,0.18)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";
