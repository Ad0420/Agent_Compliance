"use client";

/**
 * RecommendationCard — Phase 1 PR 0b component primitive.
 *
 * Compliance → AI Insights card. Per `dashboard-design-system.md`
 * §Recommendation card (AI Insights):
 *   - Title (Inter 500, 15px) + SeverityBadge in the header
 *   - Quoted source rendered with `--paper-3` background, italic optional
 *   - Issue description prefixed by amber ⚠ glyph, 13px ink-2
 *   - "Apply recommendation" primary button at the bottom
 *   - Expand/collapse caret on the right; default collapsed (title + badge
 *     only)
 *
 * Per spec voice rules (CLAUDE.md): the word "regulator-ready" is preferred
 * over "court-admissible". The footer line "Recommendations are AI-generated
 * and are not regulatory advice." reinforces that boundary on every card.
 */

import * as React from "react";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

import { SeverityBadge, type Severity } from "./severity-badge";

export interface RecommendationCardProps {
  severity: Severity;
  title: string;
  /**
   * The quoted source text the recommendation refers to (e.g., a regulation
   * passage, a contract clause). Rendered in a `--paper-3` block.
   */
  quotedSource?: React.ReactNode;
  description: React.ReactNode;
  /** Suggested fix copy shown beneath the description. */
  suggestedAction?: React.ReactNode;
  /** Controlled `expanded` state. Pair with `onToggle` for full control. */
  expanded?: boolean;
  onToggle?: (next: boolean) => void;
  /** Default expanded state when uncontrolled. Default `false`. */
  defaultExpanded?: boolean;
  /** Callback when the Apply button is clicked. */
  onApply?: () => void;
  /** Disable the Apply button (e.g., during in-flight requests). */
  applyDisabled?: boolean;
  /** Override the Apply button label. Default "Apply recommendation". */
  applyLabel?: string;
  className?: string;
}

export function RecommendationCard({
  severity,
  title,
  quotedSource,
  description,
  suggestedAction,
  expanded: expandedProp,
  onToggle,
  defaultExpanded = false,
  onApply,
  applyDisabled = false,
  applyLabel = "Apply recommendation",
  className,
}: RecommendationCardProps) {
  const [internalExpanded, setInternalExpanded] = React.useState(defaultExpanded);
  const isControlled = expandedProp !== undefined;
  const expanded = isControlled ? expandedProp : internalExpanded;

  const toggle = () => {
    const next = !expanded;
    if (!isControlled) setInternalExpanded(next);
    onToggle?.(next);
  };

  const detailsId = React.useId();

  return (
    <article
      data-slot="recommendation-card"
      data-severity={severity}
      data-expanded={expanded}
      className={cn(
        "rounded-[14px] border bg-[color:var(--paper-2)] p-6",
        "border-[color:var(--ink-4)] shadow-[var(--shadow-1)]",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <h3 className="text-[15px] font-medium text-[color:var(--ink)] leading-snug">
            {title}
          </h3>
          <SeverityBadge severity={severity} />
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={expanded ? "Collapse recommendation" : "Expand recommendation"}
          className={cn(
            "inline-flex size-7 shrink-0 items-center justify-center rounded-[6px]",
            "text-[color:var(--ink-2)] transition-colors",
            "hover:bg-[color:var(--paper-3)] hover:text-[color:var(--ink)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
            "focus-visible:outline-[color:var(--ink)]",
          )}
        >
          {expanded ? (
            <ChevronUp aria-hidden="true" className="size-4" />
          ) : (
            <ChevronDown aria-hidden="true" className="size-4" />
          )}
        </button>
      </header>

      {expanded ? (
        <div id={detailsId} className="mt-4 flex flex-col gap-4">
          {quotedSource ? (
            <blockquote
              className={cn(
                "rounded-[8px] bg-[color:var(--paper-3)] px-3 py-3",
                "text-[13px] italic text-[color:var(--ink)] leading-relaxed",
              )}
            >
              {quotedSource}
            </blockquote>
          ) : null}
          <p className="flex items-start gap-2 text-[13px] text-[color:var(--ink-2)] leading-relaxed">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-[color:var(--amber)]"
            />
            <span>{description}</span>
          </p>
          {suggestedAction ? (
            <div className="rounded-[8px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-3 text-[13px] text-[color:var(--ink)] leading-relaxed">
              <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
                Suggested action
              </p>
              {suggestedAction}
            </div>
          ) : null}
          {onApply ? (
            <button
              type="button"
              onClick={onApply}
              disabled={applyDisabled}
              className={cn(
                "inline-flex h-9 w-full items-center justify-center rounded-[10px] px-4",
                "bg-[color:var(--ink)] text-[14px] font-medium text-[color:var(--paper)]",
                "transition-colors hover:bg-[color:var(--ink-hover)]",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                "focus-visible:outline-[color:var(--ink)]",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {applyLabel}
            </button>
          ) : null}
        </div>
      ) : null}

      <p className="mt-4 border-t border-[color:var(--ink-4)] pt-3 text-[11px] text-[color:var(--ink-3)]">
        Recommendations are AI-generated and are not regulatory advice.
      </p>
    </article>
  );
}
