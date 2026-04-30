/**
 * Textarea — multi-line text field. Same visual rules as Input.
 *
 * The clinical encounter UI uses these for transcript previews and chart-entry
 * edits. Defaults to 5 rows so a typical SOAP note section fits without scroll.
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
          "shadow-[inset_0_1px_2px_rgba(27,26,23,0.06)]",
          "font-sans text-sm leading-relaxed placeholder:text-[var(--ink-4)]",
          "transition-colors resize-y",
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
Textarea.displayName = "Textarea";
