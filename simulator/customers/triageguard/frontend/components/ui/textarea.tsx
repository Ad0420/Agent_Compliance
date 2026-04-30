/**
 * Textarea — multi-line text field. Same visual rules as Input.
 *
 * Used for symptom-history capture, nurse rationale, and patient summary
 * edits. Defaults to 5 rows so a typical triage note fits without scroll.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, rows = 5, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        rows={rows}
        className={cn(
          "flex w-full rounded-xl px-3.5 py-3",
          "bg-[var(--surface)] text-[var(--ink)]",
          "border border-[var(--hairline)]",
          "shadow-[inset_0_1px_2px_rgba(14,26,26,0.06)]",
          "font-sans text-sm leading-relaxed placeholder:text-[var(--ink-4)]",
          "transition-colors resize-y",
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
Textarea.displayName = "Textarea";
