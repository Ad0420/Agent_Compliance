"use client";

/**
 * AI Coverage Matrix — Phase 1 PR 13 (Stream F item F4).
 *
 * Two variants via a single component (per the v1-implementation-plan):
 *
 *   - ``variant="full"`` — table used on the Customer detail page,
 *     above the Status section (Codex D1: Matrix above Status, not
 *     below). One row per CustomerAgent with the six spec columns.
 *
 *   - ``variant="compact"`` — single-line rollup used on the Customers
 *     list page ("3 of 3 agents", "1 of 3 agents · Scribe only",
 *     "0 of 0 agents"). Paired with a StatusDot so the colour signal
 *     matches the row-status pattern.
 *
 * The three "later phase" columns (HITL gates, PDF included, Posture
 * included) render as placeholders today with tooltips explaining when
 * the real values populate. Surfacing them now keeps the contract
 * stable across phases — only the data flips, not the columns.
 *
 * No pulse skeletons (Loading.Spinner only — PR #198 review feedback).
 */

import * as React from "react";
import { Check, X } from "lucide-react";

import {
  StatusDot,
  type StatusVariant,
} from "@/components/ui/status-indicator";
import { Loading } from "@/components/ui/loading";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  CustomerAgentCoverage,
  CustomerAgentCoverageLevel,
} from "@/lib/api-types";

const coverageVariant: Record<CustomerAgentCoverageLevel, StatusVariant> = {
  covered: "ok",
  partial: "warn",
  none: "muted",
};

const coverageLabel: Record<CustomerAgentCoverageLevel, string> = {
  covered: "Covered",
  partial: "Partial",
  none: "Not covered",
};

function formatDetectedDate(iso: string): string {
  // ISO8601 from the API; using built-in toLocaleDateString keeps the
  // format consistent with the dashboard's other date columns and avoids
  // an extra dependency.
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function humanAgentType(agent_type: string): string {
  // The auto-discovery service normalizes to lowercase ("scribe",
  // "prior_auth"). Display capitalises the first letter and converts
  // underscores to spaces so it reads naturally in the matrix.
  if (!agent_type) return "Unknown";
  return agent_type
    .split("_")
    .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : p))
    .join(" ");
}

// ─── Compact rollup ─────────────────────────────────────────────────────

interface CompactRollupProps {
  agents: CustomerAgentCoverage[];
  /** Optional class for the wrapper — useful inside table cells. */
  className?: string;
}

export function CoverageMatrixCompact({ agents, className }: CompactRollupProps) {
  const total = agents.length;
  const covered = agents.filter((a) => a.coverage === "covered").length;

  // StatusDot variant:
  //   total === 0  → muted ("0 of 0 agents")
  //   covered === total → ok ("3 of 3 agents")
  //   else → warn (partial coverage)
  const variant: StatusVariant =
    total === 0 ? "muted" : covered === total ? "ok" : "warn";

  let label = `${covered} of ${total} agents`;
  if (total > 0 && covered < total) {
    // Append the most-recently-seen covered agent's display name as the
    // "only" hint — matches the spec's "1 of 3 agents · Scribe only"
    // example. Sort by last_seen_at desc and pick the first covered row;
    // if none are covered, fall through to the count-only string.
    const sorted = [...agents]
      .filter((a) => a.coverage === "covered")
      .sort(
        (a, b) =>
          new Date(b.last_seen_at).getTime() -
          new Date(a.last_seen_at).getTime(),
      );
    if (sorted.length > 0) {
      label = `${covered} of ${total} agents · ${humanAgentType(sorted[0].agent_type)} only`;
    }
  }

  return <StatusDot variant={variant} label={label} className={className} />;
}

// ─── Full matrix table ───────────────────────────────────────────────────

interface FullMatrixProps {
  agents: CustomerAgentCoverage[];
  isLoading?: boolean;
  /** Optional className for the wrapper. */
  className?: string;
}

export function CoverageMatrixFull({ agents, isLoading, className }: FullMatrixProps) {
  if (isLoading) {
    return (
      <div
        aria-busy="true"
        className="flex justify-center py-6 text-[color:var(--ink-3)]"
        data-testid="coverage-matrix-loading"
      >
        <Loading.Spinner size={20} label="Loading coverage matrix" />
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <p className="text-[13px] text-[color:var(--ink-2)]" data-testid="coverage-matrix-empty">
        No agents detected yet. Each unique agent that calls the SDK for this
        customer will appear here.
      </p>
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div
        className={`overflow-hidden rounded-md border border-[color:var(--ink-4)] ${className ?? ""}`}
        data-testid="coverage-matrix-full"
      >
        <table className="w-full text-left text-[13px] [font-feature-settings:'tnum']">
          <thead className="bg-[color:var(--paper-2)] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
            <tr>
              <th scope="col" className="px-4 py-3">Agent</th>
              <th scope="col" className="px-4 py-3">Detected</th>
              <th scope="col" className="px-4 py-3">Vera coverage</th>
              <th scope="col" className="px-4 py-3">Capture</th>
              <th scope="col" className="px-4 py-3">HITL gates</th>
              <th scope="col" className="px-4 py-3">PDF included</th>
              <th scope="col" className="px-4 py-3">Posture included</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[color:var(--ink-4)]">
            {agents.map((agent) => (
              <tr key={agent.id}>
                <td className="px-4 py-3 font-medium text-[color:var(--ink)]">
                  {humanAgentType(agent.agent_type)}
                </td>
                <td className="px-4 py-3 text-[color:var(--ink-2)]">
                  {formatDetectedDate(agent.first_seen_at)}
                </td>
                <td className="px-4 py-3">
                  <StatusDot
                    variant={coverageVariant[agent.coverage]}
                    label={coverageLabel[agent.coverage]}
                  />
                </td>
                <td className="px-4 py-3">
                  <BooleanCell value={agent.has_capture} label="Capture" />
                </td>
                <td className="px-4 py-3">
                  <PlaceholderCell
                    text={String(agent.hitl_gate_count)}
                    tooltip="Populates in Phase 2 when gates ship."
                  />
                </td>
                <td className="px-4 py-3">
                  <PlaceholderCell
                    text={agent.pdf_included ? "Yes" : "—"}
                    tooltip="Populates in Phase 4 when the audit PDF generator ships."
                  />
                </td>
                <td className="px-4 py-3">
                  <PlaceholderCell
                    text={agent.posture_included ? "Yes" : "—"}
                    tooltip="Populates in Phase 4 when org posture compute ships."
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TooltipProvider>
  );
}

function BooleanCell({ value, label }: { value: boolean; label: string }) {
  if (value) {
    return (
      <span className="inline-flex items-center gap-1 text-[color:var(--olive)]">
        <Check className="size-3.5" aria-hidden="true" />
        <span className="sr-only">{label} yes</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[color:var(--ink-3)]">
      <X className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{label} no</span>
    </span>
  );
}

function PlaceholderCell({ text, tooltip }: { text: string; tooltip: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className="cursor-help text-[color:var(--ink-3)] underline decoration-dotted decoration-[color:var(--ink-4)] underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
        >
          {text}
        </span>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

// ─── Switchboard ─────────────────────────────────────────────────────────
// One default export that dispatches on `variant`, matching the call-site
// pattern in v1-implementation-plan. The dedicated helpers above are
// also exported so callers that already know which variant they want
// can skip the dispatch.

interface CoverageMatrixProps {
  agents: CustomerAgentCoverage[];
  variant: "full" | "compact";
  isLoading?: boolean;
  className?: string;
}

export function CoverageMatrix({ agents, variant, isLoading, className }: CoverageMatrixProps) {
  if (variant === "compact") {
    return <CoverageMatrixCompact agents={agents} className={className} />;
  }
  return <CoverageMatrixFull agents={agents} isLoading={isLoading} className={className} />;
}
