"use client";

/**
 * StatusIndicator — Phase 1 PR 0b component primitive.
 *
 * The dashboard standard for showing entity state next to a name (customer,
 * decision, document, integration). Per `dashboard-design-system.md` §Status
 * indicator (dot + label), the dot is ALWAYS paired with a text label — never
 * colour alone — so the component is accessible by construction.
 *
 * Two presentations:
 *   - `StatusDot` (8px filled circle) — the default, used in rows + headers.
 *   - `StatusIcon` (24px filled circle with check/warn/x glyph) — used in
 *     compliance insights tables where a chunkier indicator is wanted.
 *
 * Tokens come from `.dashboard`-scoped CSS variables in `app/globals.css`
 * (`--olive`, `--amber`, `--brick`, `--olive-bg`, `--amber-bg`, `--brick-bg`,
 * `--ink-3`). Tailwind v4 requires the explicit `color:` cast on var-as-color
 * utilities; we follow that here.
 */

import * as React from "react";
import { Check, AlertTriangle, X, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type StatusVariant = "ok" | "warn" | "error" | "muted";

const dotColorByVariant: Record<StatusVariant, string> = {
  ok: "bg-[color:var(--olive)]",
  warn: "bg-[color:var(--amber)]",
  error: "bg-[color:var(--brick)]",
  muted: "bg-[color:var(--ink-3)]",
};

const iconBgByVariant: Record<StatusVariant, string> = {
  ok: "bg-[color:var(--olive-bg)] text-[color:var(--olive)]",
  warn: "bg-[color:var(--amber-bg)] text-[color:var(--amber)]",
  error: "bg-[color:var(--brick-bg)] text-[color:var(--brick)]",
  muted: "bg-[color:var(--ink-5)] text-[color:var(--ink-3)]",
};

const labelColorByVariant: Record<StatusVariant, string> = {
  ok: "text-[color:var(--ink)]",
  warn: "text-[color:var(--ink)]",
  error: "text-[color:var(--ink)]",
  muted: "text-[color:var(--ink-2)]",
};

const ariaLabelPrefixByVariant: Record<StatusVariant, string> = {
  ok: "OK",
  warn: "Warning",
  error: "Error",
  muted: "Inactive",
};

export interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant: StatusVariant;
  /**
   * Visible text label. Required for a11y. Use `srOnly` to keep the label
   * announced to screen readers but hidden visually (e.g., dense table cells
   * where the meaning is conveyed by the column header).
   */
  label: string;
  srOnly?: boolean;
}

export function StatusDot({
  variant,
  label,
  srOnly = false,
  className,
  ...rest
}: StatusDotProps) {
  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      {...rest}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block size-2 rounded-full",
          dotColorByVariant[variant],
        )}
      />
      <span
        className={cn(
          "text-[13px] leading-none",
          labelColorByVariant[variant],
          srOnly && "sr-only",
        )}
      >
        <span className="sr-only">{ariaLabelPrefixByVariant[variant]}: </span>
        {label}
      </span>
    </span>
  );
}

export interface StatusIconProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant: StatusVariant;
  label: string;
  srOnly?: boolean;
  /** Size of the surrounding circle in pixels. Default 24. */
  size?: 20 | 24 | 32;
}

const IconByVariant: Record<StatusVariant, LucideIcon> = {
  ok: Check,
  warn: AlertTriangle,
  error: X,
  muted: AlertTriangle,
};

export function StatusIcon({
  variant,
  label,
  srOnly = false,
  size = 24,
  className,
  ...rest
}: StatusIconProps) {
  const Glyph = IconByVariant[variant];
  // Inline px for circle size so we can match the spec (20 / 24 / 32). The
  // inner SVG sits at ~62.5% of the circle so a 24px circle gets a 15px icon.
  const px = `${size}px`;
  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      {...rest}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex items-center justify-center rounded-full",
          iconBgByVariant[variant],
        )}
        style={{ width: px, height: px }}
      >
        <Glyph
          className="size-3.5"
          aria-hidden="true"
          strokeWidth={2.25}
        />
      </span>
      <span
        className={cn(
          "text-[13px] leading-none",
          labelColorByVariant[variant],
          srOnly && "sr-only",
        )}
      >
        <span className="sr-only">{ariaLabelPrefixByVariant[variant]}: </span>
        {label}
      </span>
    </span>
  );
}

/**
 * Composite re-export so consumers can `import { StatusIndicator } from
 * "@/components/ui/status-indicator"` and access both presentations off the
 * same namespace, matching the design-system spec naming.
 */
export const StatusIndicator = {
  Dot: StatusDot,
  Icon: StatusIcon,
};
