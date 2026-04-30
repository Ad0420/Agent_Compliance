/**
 * Button — primary, secondary, ghost, destructive, escalate.
 *
 * TriageGuard buttons are pill-rounded (`rounded-xl`), use teal as the
 * primary accent, and pair a hairline border with a soft shadow on the
 * secondary variant — the "case file" treatment.
 *
 * The `escalate` variant is the signature CTA: filled crimson with a leading
 * arrow icon. Use it whenever the action sends a patient up the urgency
 * ladder (escalate to ER, escalate to virtual visit, hold for nurse review).
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "font-sans font-medium",
    "transition-all duration-150 ease-out",
    "disabled:pointer-events-none disabled:opacity-50",
    "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[rgba(15,118,110,0.22)]",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        primary: [
          "bg-[var(--teal)] text-white shadow-sm",
          "hover:bg-[var(--teal-deep)] hover:shadow-md",
          "active:translate-y-px active:shadow-sm",
        ].join(" "),
        secondary: [
          "bg-[var(--surface)] text-[var(--ink)] shadow-sm",
          "border border-[var(--hairline)]",
          "hover:bg-[var(--paper-2)] hover:shadow-md",
        ].join(" "),
        ghost: [
          "bg-transparent text-[var(--ink-2)]",
          "hover:bg-[var(--paper-2)] hover:text-[var(--ink)]",
        ].join(" "),
        destructive: [
          "bg-[var(--crimson)] text-white shadow-sm",
          "hover:bg-[var(--crimson-deep)] hover:shadow-md",
          "focus-visible:ring-[rgba(185,28,28,0.28)]",
        ].join(" "),
        escalate: [
          // The signature CTA. Filled crimson with a slightly heavier weight,
          // because escalation is the loudest event the product makes.
          "bg-[var(--crimson)] text-white font-semibold shadow-sm",
          "hover:bg-[var(--crimson-deep)] hover:shadow-md",
          "active:translate-y-px",
          "focus-visible:ring-[rgba(185,28,28,0.28)]",
        ].join(" "),
      },
      size: {
        sm: "h-8 px-3 text-sm rounded-lg [&_svg]:size-3.5",
        md: "h-10 px-4 text-sm rounded-xl [&_svg]:size-4",
        lg: "h-12 px-5 text-base rounded-xl [&_svg]:size-5",
        icon: "h-10 w-10 rounded-xl [&_svg]:size-4",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
