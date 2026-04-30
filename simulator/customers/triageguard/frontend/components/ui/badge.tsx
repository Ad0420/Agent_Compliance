/**
 * Badge — pill chip used for status, counts, and labels.
 *
 * TriageGuard badges are sentence-case with a soft-tinted background — NOT
 * Vera's all-caps tracking-widest "regulator" pills. A leading dot is the
 * subtle TriageGuard tell (added by `withDot`).
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  [
    "inline-flex items-center gap-1.5 rounded-full font-sans font-medium",
    "transition-colors",
    "[&_svg]:size-3 [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        neutral:
          "bg-[var(--paper-2)] text-[var(--ink-2)] ring-1 ring-inset ring-[var(--hairline)]",
        teal:
          "bg-[var(--teal-soft)] text-[var(--teal-ink)] ring-1 ring-inset ring-[rgba(15,118,110,0.22)]",
        amber:
          "bg-[var(--amber-soft)] text-[var(--amber)] ring-1 ring-inset ring-[rgba(146,64,14,0.22)]",
        crimson:
          "bg-[var(--crimson-soft)] text-[var(--crimson)] ring-1 ring-inset ring-[rgba(185,28,28,0.22)]",
        moss:
          "bg-[var(--moss-soft)] text-[var(--moss)] ring-1 ring-inset ring-[rgba(47,106,61,0.22)]",
        outline:
          "bg-transparent text-[var(--ink-2)] ring-1 ring-inset ring-[var(--hairline)]",
      },
      size: {
        sm: "h-5 px-2 text-[11px]",
        md: "h-6 px-2.5 text-xs",
        lg: "h-7 px-3 text-sm",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "md",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  /** Render a leading status dot. Off by default; on when used as a queue marker. */
  withDot?: boolean;
}

const dotColor: Record<NonNullable<BadgeProps["variant"]>, string> = {
  neutral: "var(--ink-3)",
  teal: "var(--teal)",
  amber: "var(--amber)",
  crimson: "var(--crimson)",
  moss: "var(--moss)",
  outline: "var(--ink-3)",
};

export function Badge({
  className,
  variant,
  size,
  withDot,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(badgeVariants({ variant, size, className }))}
      {...props}
    >
      {withDot && (
        <span
          aria-hidden
          className="size-1.5 rounded-full"
          style={{ backgroundColor: dotColor[variant ?? "neutral"] }}
        />
      )}
      {children}
    </span>
  );
}

export { badgeVariants };
