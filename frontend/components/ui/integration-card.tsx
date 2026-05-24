"use client";

/**
 * IntegrationCard — Phase 1 PR 0b component primitive.
 *
 * Settings → Integrations grid card. Per `dashboard-design-system.md`
 * §Integration card (specific pattern):
 *   - 40×40 coloured logo (the ONE place coloured icon backgrounds are
 *     allowed — these are external product brands, not Vera chrome)
 *   - Top-right domain link with `↗` external-link suffix, 12px ink-3
 *   - Name (16px Inter 600) + description (13px ink-2, 2-3 lines clamped)
 *   - Bottom row: Settings ghost button + Toggle (or any consumer-provided
 *     controls slot)
 *   - 24px padding, 220px min-height for grid evenness, 1px ink-4 border
 *
 * The visual treatment intentionally mirrors `chain-status-card.tsx` (which
 * was the existing reference pattern in Phase 0).
 */

import * as React from "react";
import { ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";

import { StatusDot, type StatusVariant } from "./status-indicator";

export interface IntegrationCardProps {
  name: string;
  /**
   * Brand-coloured logo node. Consumers pass their own ReactNode here
   * (typically an `<img>` or inline SVG with the integration's brand
   * background colour). The 40×40 sizing is enforced by the wrapper.
   */
  logo: React.ReactNode;
  /** Plain-prose description, 2-3 lines max — will be `line-clamp-3`-ed. */
  description?: string;
  /**
   * Status indicator pair (variant + label) shown above the description.
   * Use `{ variant: 'ok', label: 'Connected' }` for healthy integrations,
   * `{ variant: 'warn', label: 'Delivery failing — 12% in last 24h' }` for
   * degraded, `{ variant: 'error', label: 'Disabled' }` etc.
   */
  status?: { variant: StatusVariant; label: string };
  /**
   * Top-right domain link. Renders the domain with an `↗` external-link
   * suffix. Pass `href` to make it clickable; otherwise it's text-only.
   */
  domain?: { label: string; href?: string };
  /**
   * Bottom-row controls slot. Consumers typically pass a Settings ghost
   * button + a Toggle switch. Layout is flex with `justify-between` so
   * a single child sticks to the right; pass an explicit wrapper for
   * multi-child layouts.
   */
  controls?: React.ReactNode;
  className?: string;
}

export function IntegrationCard({
  name,
  logo,
  description,
  status,
  domain,
  controls,
  className,
}: IntegrationCardProps) {
  return (
    <article
      data-slot="integration-card"
      className={cn(
        "flex min-h-[220px] flex-col gap-4 rounded-[14px] border p-6",
        "border-[color:var(--ink-4)] bg-[color:var(--paper-2)]",
        "shadow-[var(--shadow-1)]",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div
          aria-hidden="true"
          className={cn(
            "flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-[8px]",
            "bg-[color:var(--paper-3)]",
          )}
        >
          {logo}
        </div>
        {domain ? (
          domain.href ? (
            <a
              href={domain.href}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                "inline-flex items-center gap-1 text-[12px] font-medium text-[color:var(--ink-3)]",
                "transition-colors hover:text-[color:var(--ink)]",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                "focus-visible:outline-[color:var(--ink)]",
                "rounded-sm",
              )}
            >
              {domain.label}
              <ArrowUpRight aria-hidden="true" className="size-3" />
            </a>
          ) : (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[color:var(--ink-3)]">
              {domain.label}
              <ArrowUpRight aria-hidden="true" className="size-3" />
            </span>
          )
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <h3 className="text-[16px] font-semibold text-[color:var(--ink)] leading-tight">
          {name}
        </h3>
        {status ? (
          <StatusDot variant={status.variant} label={status.label} />
        ) : null}
        {description ? (
          <p className="line-clamp-3 text-[13px] text-[color:var(--ink-2)] leading-snug">
            {description}
          </p>
        ) : null}
      </div>

      {controls ? (
        <footer className="flex items-center justify-between gap-3 border-t border-[color:var(--ink-4)] pt-4">
          {controls}
        </footer>
      ) : null}
    </article>
  );
}
