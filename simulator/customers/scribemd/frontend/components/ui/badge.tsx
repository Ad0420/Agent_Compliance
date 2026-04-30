/**
 * Badge — pill chip used for status, counts, and labels.
 *
 * ScribeMD badges are NOT all-caps tracking-widest like Vera's "regulatory"
 * pills. They use sentence-case, normal tracking, and soft-tinted backgrounds.
 * Different vocabulary, on purpose.
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
        cobalt:
          "bg-[var(--cobalt-soft)] text-[var(--cobalt-ink)] ring-1 ring-inset ring-[rgba(46,91,216,0.22)]",
        amber:
          "bg-[var(--amber-soft)] text-[var(--amber)] ring-1 ring-inset ring-[rgba(194,65,12,0.22)]",
        coral:
          "bg-[var(--coral-soft)] text-[var(--coral)] ring-1 ring-inset ring-[rgba(180,35,24,0.22)]",
        sage:
          "bg-[var(--sage-soft)] text-[var(--sage)] ring-1 ring-inset ring-[rgba(79,124,90,0.22)]",
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
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <span
      className={cn(badgeVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { badgeVariants };
