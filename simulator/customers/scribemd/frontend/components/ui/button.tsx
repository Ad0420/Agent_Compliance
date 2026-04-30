/**
 * Button — primary, secondary, ghost, destructive.
 *
 * ScribeMD buttons are pill-rounded (`rounded-xl`), use cobalt as the primary
 * accent, and reach for soft shadows over hairline borders. The tone is
 * deliberately calmer than Vera's emerald-glow CTAs — this is software you use
 * in a clinic, not a marketing landing page.
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
    "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[rgba(46,91,216,0.22)]",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        primary: [
          "bg-[var(--cobalt)] text-white shadow-sm",
          "hover:bg-[var(--cobalt-deep)] hover:shadow-md",
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
          "bg-[var(--coral)] text-white shadow-sm",
          "hover:bg-[#9A1F14] hover:shadow-md",
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
