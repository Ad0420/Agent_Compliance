"use client";

/**
 * EmptyState — Phase 1 PR 0b component primitive.
 *
 * Used on every list/page with no content yet. Per
 * `dashboard-design-system.md` §Empty state and `v1-implementation-plan.md`
 * (Phase 1 §Empty states audit): title + optional subtitle + optional primary
 * CTA. NO illustrations, NO icons, NO emoji.
 *
 * The CTA is rendered as a `<button>` by default; pass `ctaHref` to render
 * an `<a>` instead so it works as a navigation target with semantic
 * highlighting in Next.js. The right-pointing arrow is appended via a `→`
 * glyph to match the design-system example ("Generate your first PDF →").
 */

import * as React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateBaseProps {
  title: string;
  subtitle?: string;
  /** Label for the primary CTA. Omit to render with no CTA. */
  ctaLabel?: string;
  /** Optional className for the outer container. */
  className?: string;
}

interface EmptyStateAsButtonProps extends EmptyStateBaseProps {
  ctaHref?: undefined;
  onCtaClick?: () => void;
}

interface EmptyStateAsLinkProps extends EmptyStateBaseProps {
  ctaHref: string;
  onCtaClick?: undefined;
}

export type EmptyStateProps = EmptyStateAsButtonProps | EmptyStateAsLinkProps;

export function EmptyState(props: EmptyStateProps) {
  const { title, subtitle, ctaLabel, className } = props;

  return (
    <div
      data-slot="empty-state"
      className={cn(
        "mx-auto flex w-full max-w-md flex-col items-center justify-center gap-4",
        "px-6 py-16 text-center",
        className,
      )}
    >
      <p className="text-[18px] font-medium text-[color:var(--ink)] leading-snug">
        {title}
      </p>
      {subtitle ? (
        <p className="text-[14px] text-[color:var(--ink-2)] leading-normal">
          {subtitle}
        </p>
      ) : null}
      {ctaLabel ? (
        "ctaHref" in props && props.ctaHref ? (
          <Link
            href={props.ctaHref}
            className={emptyStateCtaClasses}
            data-slot="empty-state-cta"
          >
            <span>{ctaLabel}</span>
            <ArrowRight aria-hidden="true" className="size-4" />
          </Link>
        ) : (
          <button
            type="button"
            onClick={"onCtaClick" in props ? props.onCtaClick : undefined}
            className={emptyStateCtaClasses}
            data-slot="empty-state-cta"
          >
            <span>{ctaLabel}</span>
            <ArrowRight aria-hidden="true" className="size-4" />
          </button>
        )
      ) : null}
    </div>
  );
}

// Primary-button shape, per `dashboard-design-system.md` §Button. Ink bg,
// paper text, 10px radius, 36px tall, 16px horizontal padding, 14px text.
// Focus ring is the spec-mandated 2px ink outline at 2px offset.
const emptyStateCtaClasses = cn(
  "mt-2 inline-flex h-9 items-center gap-2 rounded-[10px] px-4",
  "bg-[color:var(--ink)] text-[14px] font-medium text-[color:var(--paper)]",
  "transition-colors hover:bg-[color:#2A1D14]",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
  "focus-visible:outline-[color:var(--ink)]",
  "disabled:cursor-not-allowed disabled:opacity-50",
);
