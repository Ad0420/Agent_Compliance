"use client";

/**
 * Compliance → Reviews
 *
 * Wave 2D PR C2 — org-wide Review queue page. Surfaces every decision in
 * PENDING_REVIEW state across the org so a reviewer can complete HITL
 * approvals from the dashboard as the alt channel when the customer
 * hasn't wired (or has lost connectivity to) their in-app webhook.
 *
 * Citations
 * =========
 *  - v1-implementation-plan.md §Phase 2 "Dashboard" line 120
 *    "Review queue page (under Compliance → Reviews): table of all
 *     decisions in PENDING_REVIEW state across the org. Filter by
 *     customer, by gate, by role. Click row → Pattern B layout."
 *  - v1-implementation-plan.md §Phase 2 "Test gate" line 127
 *    "Use the Review queue UI as the alt channel: complete one pending
 *     review entirely through the dashboard without the customer's
 *     webhook — confirm the chain still extends correctly."
 *  - dashboard-design-system.md §Layout patterns / Pattern B
 *    (sidebar + content + right panel split work surface, 360-420px panel).
 *
 * Coordination with PR C4 (RecommendationCard scaffold)
 * =====================================================
 * v1-implementation-plan.md line 122 calls for a Recommendation card
 * placeholder above the queue ("empty in this phase, wired up in
 * Phase 4"). PR C4 owns the dedicated scaffold component; until that
 * lands we render a plain placeholder with a TODO comment pointing at
 * C4 so we don't duplicate its work.
 */

import * as React from "react";

import { ReviewQueueTable } from "@/components/reviews/review-queue-table";
import { ReviewDetailPanel } from "@/components/reviews/review-detail-panel";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { useCustomers } from "@/hooks/use-customers";
import type { Approval, Customer } from "@/lib/api-types";

export default function ReviewsPage() {
  const { data, isLoading, isError, error } = usePendingApprovals();
  // Customer lookup is best-effort — the page still functions if the
  // customer fetch fails (rows fall back to raw data_subject_id).
  const customersQuery = useCustomers({ limit: 200 });

  const customersByTenantId = React.useMemo(() => {
    const map: Record<string, Customer> = {};
    for (const c of customersQuery.data?.items ?? []) {
      map[c.tenant_id] = c;
    }
    return map;
  }, [customersQuery.data]);

  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  // Auto-clear selection if the row drops out of the queue (e.g. it was
  // approved by another reviewer or expired between fetches). Prevents
  // the right panel from referencing stale data.
  React.useEffect(() => {
    if (!selectedId) return;
    const stillThere = data?.approvals.some((a) => a.id === selectedId);
    if (!stillThere) setSelectedId(null);
  }, [selectedId, data]);

  const selected = data?.approvals.find((a) => a.id === selectedId) ?? null;

  const handleSelect = (a: Approval) => setSelectedId(a.id);
  const handleClose = () => setSelectedId(null);

  return (
    <div className="space-y-6">
      <Header
        total={data?.total ?? 0}
        loading={isLoading && !data}
      />

      {/*
        AI Recommendation card placeholder per v1-implementation-plan.md
        line 122 — "empty in this phase, wired up in Phase 4". PR C4 owns
        the scaffold component; this placeholder renders the spec-mandated
        slot above the queue without duplicating C4's work. Replace with
        <RecommendationCardScaffold /> once C4 lands on main.

        TODO(c4): swap for the dedicated scaffold component.
      */}
      <div
        data-testid="reviews-page-recommendation-placeholder"
        aria-hidden="true"
        className="hidden"
      />

      <div
        className={
          selected
            ? "grid gap-6 lg:grid-cols-[1fr_380px]"
            : "grid gap-6"
        }
      >
        <ReviewQueueTable
          approvals={data?.approvals ?? []}
          customersByTenantId={customersByTenantId}
          selectedReviewId={selectedId}
          onSelect={handleSelect}
          total={data?.total ?? 0}
          isLoading={isLoading}
          isError={isError}
          error={error as Error | null}
        />
        {selected ? (
          <div className="lg:sticky lg:top-20 lg:h-[calc(100vh-6rem)]">
            <ReviewDetailPanel
              approval={selected}
              onClose={handleClose}
              customerDisplayName={
                selected.data_subject_id
                  ? customersByTenantId[selected.data_subject_id]?.display_name
                  : null
              }
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

interface HeaderProps {
  total: number;
  loading: boolean;
}
function Header({ total, loading }: HeaderProps) {
  return (
    <div>
      <h1 className="text-[22px] font-medium tracking-tight text-[color:var(--ink)]">
        Reviews
      </h1>
      <p className="mt-1 text-[13px] text-[color:var(--ink-2)]">
        {loading
          ? "Loading pending reviews…"
          : total === 0
            ? "No pending reviews. When agents need human approval, they'll appear here."
            : `${total.toLocaleString()} pending review${total === 1 ? "" : "s"} across the org.`}
      </p>
    </div>
  );
}
