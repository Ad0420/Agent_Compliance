/**
 * Input — single-line text field with an inset shadow.
 *
 * The inset shadow is the visual distinguisher: instead of Vera's hairline
 * border on a flat field, ScribeMD inputs sit "into" the paper, like a form on
 * a clipboard. Cobalt focus ring instead of emerald.
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
          "shadow-[inset_0_1px_2px_rgba(27,26,23,0.06)]",
          "font-sans text-sm placeholder:text-[var(--ink-4)]",
          "transition-colors",
          "focus:outline-none focus:border-[var(--cobalt)]",
          "focus:ring-4 focus:ring-[rgba(46,91,216,0.16)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";
