"use client";

/**
 * /compliance — Phase 4 Wave 2 PR C1.
 *
 * The Compliance Posture page renders org-wide runtime posture across
 * the six universal dimensions (artifact freshness, HITL completion,
 * reviewer integrity, notice delivery rate, chain integrity, workflow
 * timeliness) in an asymmetric layout — composite headline +
 * measured-dimension cards + collapsed awaiting-data row.
 *
 * Why asymmetric, not a 2x3 grid (Phase 4 gate decision #28): v1
 * reality is most orgs have only 1-3 measured dimensions in week 1.
 * A 2x3 grid would render four placeholder squares saying "insufficient
 * data" and that reads as a defect. Asymmetric foregrounds what's
 * actually measurable and collapses the rest honestly into a single
 * "X dimensions awaiting data" row.
 *
 * Data sources:
 *   - ``GET /v1/compliance/posture?window_days=N`` — six-dimension
 *     aggregate from Wave 1 PR B1.
 *   - ``GET /v1/customers`` ⨯ ``GET /v1/customers/{id}/agents`` —
 *     org-wide coverage roll-up computed client-side (no dedicated
 *     org-level endpoint in v1).
 *
 * The bottom of the page renders ``<ComplianceInsightsSurface />``
 * (Phase 4 Wave 2 PR C2) — the AI Insights surface holds its own
 * mutation against ``POST /v1/compliance/insights``; the page just
 * mounts it without further wiring.
 */

import * as React from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { CoverageSection } from "@/components/compliance/coverage-section";
import {
  CompositeHeadline,
  COMPLIANCE_WINDOW_OPTIONS,
  type ComplianceWindowDays,
} from "@/components/compliance/composite-headline";
import { MeasuredDimensionCard } from "@/components/compliance/measured-dimension-card";
import { AwaitingDataRow } from "@/components/compliance/awaiting-data-row";
import { ComplianceInsightsSurface } from "@/components/compliance/insights-surface";
import { useCompliancePosture } from "@/hooks/use-compliance-posture";
import { useOrgCoverage } from "@/hooks/use-org-coverage";

const DEFAULT_WINDOW: ComplianceWindowDays = 30;

/**
 * Full-date + time formatter for the footer "Generated …" line. Per
 * voice spec the year is mandatory and digits sit on ``tabular-nums``.
 * The Intl formatter below produces e.g. "Generated May 26 at 22:30 UTC"
 * with the year inlined by the format options.
 */
// copy-allow: docstring example year below is not user-facing copy.
// Output shape: "Generated May 26, 2026 at 22:30 UTC".
function formatGeneratedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const datePart = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(d);
  return `Generated ${datePart} at ${timePart} UTC`;
}

export default function CompliancePage() {
  const [windowDays, setWindowDays] =
    React.useState<ComplianceWindowDays>(DEFAULT_WINDOW);

  const posture = useCompliancePosture(windowDays);
  const coverage = useOrgCoverage();

  return (
    <div className="mx-auto max-w-6xl space-y-8 py-2">
      {/* Page title */}
      <header className="space-y-2">
        <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
          Compliance
        </h1>
        <p className="text-[14px] text-[color:var(--ink-2)]">
          Org-wide runtime posture across six dimensions.
        </p>
      </header>

      {/* Error banner — sits at the top so the rest of the page degrades
          gracefully if the posture fetch fails. */}
      {posture.isError && (
        <div
          role="alert"
          data-testid="compliance-error-banner"
          className="flex items-center justify-between gap-4 rounded-[10px] border border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)] px-4 py-3 text-[14px] text-[color:var(--ink)]"
        >
          <span>Could not load compliance posture. Try again.</span>
          <button
            type="button"
            onClick={() => posture.refetch()}
            className="rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-1 text-[13px] font-medium text-[color:var(--ink)] hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
          >
            Retry
          </button>
        </div>
      )}

      {/* Coverage section sits above the posture so the reader sees the
          denominator before any scores. */}
      {coverage.data && <CoverageSection coverage={coverage.data} />}

      {/* Composite headline + window selector. Always render so the
          window selector is reachable even while data refetches. */}
      <CompositeHeadline
        headline={
          posture.data?.composite_headline ?? "Runtime posture: — of 6 dimensions measured"
        }
        windowDays={windowDays}
        onWindowChange={setWindowDays}
      />

      {/* Loading skeleton — three placeholder rectangles per the brief. */}
      {posture.isLoading && (
        <div
          data-testid="compliance-loading-skeleton"
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36 w-full" />
          ))}
        </div>
      )}

      {/* Measured-dimension grid. Only renders when there is at least
          one measured dimension; otherwise the awaiting-data row sits
          directly under the headline (per the brief's "All
          ``not_yet_eligible``" state). */}
      {posture.data && posture.data.measured.length > 0 && (
        <div
          data-testid="measured-grid"
          className={
            posture.data.measured.length === 1
              ? "grid grid-cols-1 gap-4"
              : "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
          }
        >
          {posture.data.measured.map((d) => (
            <MeasuredDimensionCard key={d.name} dimension={d} />
          ))}
        </div>
      )}

      {/* Awaiting-data row — hidden entirely when all six dimensions
          are measured (per the brief). The component itself returns
          null when ``items`` is empty, so we just pass through. */}
      {posture.data && (
        <AwaitingDataRow items={posture.data.not_yet_eligible} />
      )}

      {/*
        AI Insights surface — Phase 4 Wave 2 PR C2 component, wired in
        post-merge via the C2↔C1 integration follow-up. The component
        owns its own ``useMutation`` against ``POST /v1/compliance/insights``
        and renders all five states (initial / loading / loaded / error /
        empty) internally — see ``frontend/components/compliance/insights-surface.tsx``.
      */}
      <ComplianceInsightsSurface />

      {/* Footer — generated_at timestamp. */}
      {posture.data && (
        <footer className="border-t border-[color:var(--ink-4)] pt-4 text-[12px] text-[color:var(--ink-3)] tabular-nums">
          {formatGeneratedAt(posture.data.computed_at)}
        </footer>
      )}
    </div>
  );
}

// Keep the supported window options exported on the page module so a
// type-level smoke test can pin the contract without re-importing the
// composite-headline module.
export { COMPLIANCE_WINDOW_OPTIONS };
