"use client";

/**
 * ComplianceInsightsSurface — Phase 4 Wave 2 PR C2.
 *
 * Mounted at the bottom of the Compliance page (C1). Five visible
 * states:
 *
 *   1. Initial — "Show insights" button.
 *   2. Loading — spinner + "Generating insights…".
 *   3. Loaded — 3-5 ``<InsightCard />`` rows + verbatim disclaimer
 *      footer. First card expanded by default; others collapsed.
 *   4. Error — inline banner mapped from the B2 error envelope +
 *      retry button. No auto-retry.
 *   5. Empty — defensive copy when the API returns 0 insights (B2
 *      clamps to 3+ but we render a friendly fallback if it doesn't).
 *
 * Self-contained: the surface holds its own ``useMutation`` against
 * ``generateComplianceInsights`` so any page that drops it in gets the
 * full lifecycle without further wiring.
 */

import * as React from "react";
import { useMutation } from "@tanstack/react-query";

import { cn } from "@/lib/utils";

import {
  generateComplianceInsights,
  INSIGHTS_ERROR_CODES,
  readInsightsErrorCode,
  type ComplianceInsight,
  type ComplianceInsightsResponse,
  type InsightsErrorCode,
} from "@/lib/api-client";

import { Loading } from "@/components/ui/loading";

import { InsightCard } from "./insight-card";

/**
 * Pure error-code → inline-banner copy mapping. Exported so the test
 * file can pin the contract — if a banner string changes the test
 * regresses.
 */
export function mapInsightsErrorMessage(code: InsightsErrorCode): string {
  if (code === INSIGHTS_ERROR_CODES.rateLimitExceeded) {
    return "Too many insight requests. Try again in a moment.";
  }
  if (code === INSIGHTS_ERROR_CODES.insightsTimeout) {
    return "Generation timed out. Try again.";
  }
  return "Could not generate insights. Try again.";
}

/** Empty-state copy — defensive, shown when API returns 0 insights. */
export const EMPTY_INSIGHTS_COPY =
  "No insights this window. Check back after more decisions are captured.";

interface InsightsLoadedViewProps {
  data: ComplianceInsightsResponse;
}

function InsightsLoadedView({ data }: InsightsLoadedViewProps) {
  // Track per-card expansion. The first card is expanded by default;
  // subsequent cards collapsed. Keyed by insight.id so re-fetching with
  // different IDs resets the state correctly.
  const [expandedIds, setExpandedIds] = React.useState<Set<string>>(() => {
    const initial = new Set<string>();
    if (data.insights.length > 0) initial.add(data.insights[0].id);
    return initial;
  });

  // If the data prop changes (a fresh fetch), reset expansion to the
  // new first card.
  const lastFirstId = React.useRef<string | null>(
    data.insights[0]?.id ?? null,
  );
  React.useEffect(() => {
    const firstId = data.insights[0]?.id ?? null;
    if (firstId !== lastFirstId.current) {
      lastFirstId.current = firstId;
      setExpandedIds(firstId ? new Set([firstId]) : new Set());
    }
  }, [data.insights]);

  const toggleCard = React.useCallback(
    (id: string, next: boolean) => {
      setExpandedIds((prev) => {
        const updated = new Set(prev);
        if (next) {
          updated.add(id);
        } else {
          updated.delete(id);
        }
        return updated;
      });
    },
    [],
  );

  if (data.insights.length === 0) {
    return (
      <div
        className="rounded-[14px] border border-dashed border-[color:var(--ink-4)] bg-[color:var(--paper-2)] px-6 py-10 text-center text-[14px] text-[color:var(--ink-2)]"
        data-testid="insights-empty"
      >
        {EMPTY_INSIGHTS_COPY}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="insights-loaded">
      <div
        className="flex flex-col gap-3"
        data-testid="insights-cards"
        role="list"
      >
        {data.insights.map((insight: ComplianceInsight) => (
          <div key={insight.id} role="listitem">
            <InsightCard
              insight={insight}
              expanded={expandedIds.has(insight.id)}
              onToggle={(next) => toggleCard(insight.id, next)}
            />
          </div>
        ))}
      </div>
      <p
        className="mt-2 text-[12px] leading-relaxed text-[color:var(--ink-2)]"
        data-testid="insights-disclaimer"
      >
        {data.disclaimer}
      </p>
    </div>
  );
}

interface InsightsErrorViewProps {
  message: string;
  onRetry: () => void;
}

function InsightsErrorView({ message, onRetry }: InsightsErrorViewProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-[14px] border border-[color:var(--brick)]/30 bg-[color:var(--paper-2)] px-6 py-5"
      data-testid="insights-error"
    >
      <p className="text-[14px] text-[color:var(--brick)]">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className={cn(
          "inline-flex h-9 items-center justify-center rounded-[10px] px-4",
          "border border-[color:var(--ink)] bg-[color:var(--ink)]",
          "text-[14px] font-medium text-[color:var(--paper)]",
          "transition-colors hover:bg-[color:var(--ink-hover,var(--ink-2))]",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-[color:var(--ink)]",
        )}
        data-testid="insights-retry"
      >
        Try again
      </button>
    </div>
  );
}

export interface ComplianceInsightsSurfaceProps {
  /**
   * Override the underlying mutation function — only used by tests to
   * inject a fake without touching the global ``fetch`` mock. Defaults
   * to the real ``generateComplianceInsights`` api-client call.
   */
  generateInsights?: () => Promise<ComplianceInsightsResponse>;
  className?: string;
}

export function ComplianceInsightsSurface({
  generateInsights = generateComplianceInsights,
  className,
}: ComplianceInsightsSurfaceProps = {}) {
  const mutation = useMutation<ComplianceInsightsResponse, unknown, void>({
    mutationFn: () => generateInsights(),
  });

  const onShowInsights = React.useCallback(() => {
    mutation.mutate();
  }, [mutation]);

  const onRetry = React.useCallback(() => {
    mutation.reset();
  }, [mutation]);

  // Initial — no data, no error, not loading. Render the button.
  const isInitial =
    !mutation.isPending && !mutation.isError && !mutation.data;

  return (
    <section
      data-slot="compliance-insights-surface"
      data-testid="compliance-insights-surface"
      className={cn("flex flex-col gap-4", className)}
    >
      {isInitial ? (
        <div>
          <button
            type="button"
            onClick={onShowInsights}
            className={cn(
              "inline-flex h-9 items-center justify-center rounded-[10px] px-4",
              "border border-[color:var(--ink)] bg-[color:var(--ink)]",
              "text-[14px] font-medium text-[color:var(--paper)]",
              "transition-colors hover:bg-[color:var(--ink-hover,var(--ink-2))]",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-[color:var(--ink)]",
            )}
            data-testid="show-insights-button"
          >
            Show insights
          </button>
        </div>
      ) : null}

      {mutation.isPending ? (
        <div
          className="flex items-center gap-2 text-[14px] text-[color:var(--ink-2)]"
          data-testid="insights-loading"
        >
          <Loading.Spinner
            size={14}
            label="Generating insights"
            className="text-[color:var(--ink)]"
          />
          <span>Generating insights…</span>
        </div>
      ) : null}

      {mutation.isError ? (
        <InsightsErrorView
          message={mapInsightsErrorMessage(
            readInsightsErrorCode(mutation.error),
          )}
          onRetry={onRetry}
        />
      ) : null}

      {!mutation.isPending && !mutation.isError && mutation.data ? (
        <InsightsLoadedView data={mutation.data} />
      ) : null}
    </section>
  );
}
