"use client";

/**
 * InsightCard — Phase 4 Wave 2 PR C2 (AI Insights surface).
 *
 * Single recommendation card rendered in the Compliance → AI Insights
 * surface. Header row carries the severity pill + dimension title +
 * chevron expand/collapse toggle. Body (when expanded) shows
 * description, quoted source block, and the suggested action.
 *
 * The "Apply recommendation" affordance was removed in the Phase 5
 * polish trust audit — surfacing a disabled button with a "Coming in
 * v1.1" tooltip violates the project rule against version-numbered
 * deferral language in user-facing copy. The action is still listed
 * verbatim under "Suggested action" so the operator knows what to do
 * manually.
 *
 * Per the C2 brief:
 *   - The Suggested action API field starts with "Consider" or
 *     "Recommended:" — render verbatim. Do not paraphrase.
 *   - Quoted source: paper-3 background, monospace, prefixed by a
 *     "Source:" label per the brief.
 *
 * The card supports controlled + uncontrolled expansion. The surface
 * passes ``expanded`` + ``onToggle`` to control the first-card-expanded
 * default. ``defaultExpanded`` is the uncontrolled fallback.
 */

import * as React from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

import type { ComplianceInsight } from "@/lib/api-client";

import { SeverityPill } from "./severity-pill";

/**
 * Kept as an empty-string export for backwards compatibility with the
 * insight-card test file (which still imports the symbol). The Apply
 * button itself has been removed in the Phase 5 polish trust audit.
 *
 * @deprecated The Apply affordance was removed. This constant exists
 *             only to keep external imports compiling.
 */
export const APPLY_TOOLTIP_TEXT = "";

export interface InsightCardProps {
  insight: ComplianceInsight;
  /**
   * Controlled expansion state. When provided, ``onToggle`` must drive
   * state changes. When ``undefined`` the card manages its own state
   * from ``defaultExpanded``.
   */
  expanded?: boolean;
  onToggle?: (next: boolean) => void;
  /** Default uncontrolled expansion. Surface defaults the first card on. */
  defaultExpanded?: boolean;
  className?: string;
}

export function InsightCard({
  insight,
  expanded: expandedProp,
  onToggle,
  defaultExpanded = false,
  className,
}: InsightCardProps) {
  const [internalExpanded, setInternalExpanded] =
    React.useState(defaultExpanded);
  const isControlled = expandedProp !== undefined;
  const expanded = isControlled ? expandedProp : internalExpanded;

  const detailsId = React.useId();

  const toggle = React.useCallback(() => {
    const next = !expanded;
    if (!isControlled) setInternalExpanded(next);
    onToggle?.(next);
  }, [expanded, isControlled, onToggle]);

  return (
    <article
      data-slot="insight-card"
      data-severity={insight.severity}
      data-expanded={expanded}
      data-testid={`insight-card-${insight.id}`}
      className={cn(
        "rounded-[14px] border bg-[color:var(--paper-2)] p-6",
        "border-[color:var(--ink-4)] shadow-[var(--shadow-1)]",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <SeverityPill
            severity={insight.severity}
            data-testid={`insight-card-${insight.id}-severity`}
          />
          <h3 className="text-[15px] font-medium leading-snug text-[color:var(--ink)]">
            {insight.title}
          </h3>
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={expanded ? "Collapse insight" : "Expand insight"}
          data-testid={`insight-card-${insight.id}-toggle`}
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
          {/* Description — 1-2 sentences in --ink body size. */}
          <p className="text-[14px] leading-relaxed text-[color:var(--ink)]">
            {insight.description}
          </p>

          {/* Quoted source — paper-3 background, monospace, "Source:" label. */}
          <div
            className={cn(
              "rounded-[8px] bg-[color:var(--paper-3)] px-3 py-3",
              "text-[13px] leading-relaxed text-[color:var(--ink)]",
            )}
            data-testid={`insight-card-${insight.id}-quoted-source`}
            data-paper-3="true"
          >
            <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
              Source:
            </p>
            <blockquote className="font-mono text-[13px] leading-relaxed text-[color:var(--ink)]">
              {insight.quoted_source}
            </blockquote>
          </div>

          {/* Suggested action — API enforces "Consider X" / "Recommended:"
              prefix; render verbatim per CLAUDE.md voice rule. */}
          <div className="rounded-[8px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-3 text-[14px] leading-relaxed text-[color:var(--ink)]">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
              Suggested action
            </p>
            <p data-testid={`insight-card-${insight.id}-suggested-action`}>
              {insight.suggested_action}
            </p>
          </div>

          {/* Apply affordance removed in Phase 5 polish trust audit —
              surfacing a disabled button with a version-numbered
              tooltip violates the project rule against deferral copy.
              The action is still listed verbatim under "Suggested
              action" above so the operator knows what to do manually. */}
        </div>
      ) : null}
    </article>
  );
}
