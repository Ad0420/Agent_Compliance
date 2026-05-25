"use client";

/**
 * DecisionsTab — Wave 2C PR C1.
 *
 * Content of the Customer detail → Decisions tab. Renders the recent
 * stream of agent decisions for one customer, each with its gate Ruling
 * and webhook delivery status (see ``DecisionRow``).
 *
 * Data source: ``useCustomerDecisions(tenant_id)`` — wraps
 * ``GET /v1/actions?tenant_id=<id>`` (Phase 1 PR 13 already supports the
 * per-tenant filter) and projects each ActionRecord into the
 * ``CustomerDecision`` shape with Ruling + delivery extracted from
 * ``reasoning``. Wave 2D will replace the adapter with a dedicated
 * `/v1/customers/{tenant_id}/decisions` endpoint when the client-side
 * shaping becomes hot enough to warrant a backend join.
 *
 * States
 * ======
 * - loading  → Loading.Spinner + aria-busy (NO skeletons, per spec)
 * - error    → inline error message with retry hint
 * - empty    → EmptyState primitive with the design-system copy
 * - loaded   → list of <DecisionRow /> + footer count
 *
 * Auto-refresh: enabled by ``useCustomerDecisions`` while at least one
 * webhook delivery is non-terminal (pending/retrying). Idle once every
 * row reaches delivered/aborted — keeps the tab responsive without
 * burning polling cycles on a stable list.
 */

import * as React from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import { DecisionRow } from "./decision-row";
import { useCustomerDecisions } from "@/hooks/use-customers";
import type { CustomerDecision } from "@/lib/api-types";

interface DecisionsTabProps {
  tenant_id: string;
  /**
   * When false, suppresses the network fetch (e.g. the tab is mounted
   * but the user hasn't selected it). The component still mounts so
   * Radix Tabs can preserve focus state — only the data layer is gated.
   */
  enabled?: boolean;
  /** Page size. Default 50 — matches the underlying ActionRecord cap. */
  limit?: number;
}

export function DecisionsTab({
  tenant_id,
  enabled = true,
  limit = 50,
}: DecisionsTabProps) {
  const { data, isLoading, isError, error } = useCustomerDecisions(
    tenant_id,
    { limit },
    enabled,
  );

  if (isLoading || !data) {
    return (
      <div
        aria-busy={isLoading || undefined}
        className="flex justify-center py-10 text-[color:var(--ink-3)]"
        data-testid="decisions-tab-loading"
      >
        <Loading.Spinner size={20} label="Loading decisions" />
      </div>
    );
  }

  if (isError) {
    return (
      <div
        role="alert"
        className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--brick-bg)] px-5 py-4 text-[14px] text-[color:var(--ink)]"
        data-testid="decisions-tab-error"
      >
        <p className="font-medium">Decisions could not be loaded.</p>
        <p className="mt-1 text-[13px] text-[color:var(--ink-2)]">
          {error?.message ??
            "Refresh the page. If the problem persists, contact support."}
        </p>
      </div>
    );
  }

  const decisions: CustomerDecision[] = data.decisions;

  if (decisions.length === 0) {
    return (
      <div data-testid="decisions-tab-empty">
        <EmptyState
          title="No decisions yet"
          subtitle="When agents make decisions for this customer, they'll appear here."
        />
      </div>
    );
  }

  return (
    <section
      aria-label="Recent decisions"
      data-testid="decisions-tab-loaded"
      className="space-y-3"
    >
      <div className="flex items-baseline justify-between">
        <p className="text-[12px] text-[color:var(--ink-3)] tabular-nums">
          Showing {decisions.length.toLocaleString()} of{" "}
          {data.total.toLocaleString()} decision
          {data.total === 1 ? "" : "s"}
        </p>
      </div>
      <ul
        role="list"
        className="overflow-hidden rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)]"
      >
        {decisions.map((d) => (
          <DecisionRow key={d.id} decision={d} />
        ))}
      </ul>
    </section>
  );
}
