"use client";

/**
 * usePendingApprovals — Wave 2D PR C2.
 *
 * Wraps ``GET /v1/approvals?status=pending`` for the org-wide Review
 * queue page (Compliance → Reviews). Auto-refreshes while at least one
 * pending review is in the list so reviewers see new items land without
 * a manual refresh.
 *
 * The hook does not filter client-side — the consumer (ReviewQueueTable)
 * applies the Customer / Gate / Required-role chips against the fetched
 * page. The page size is intentionally generous (100 default) because
 * the backend `/v1/approvals` endpoint hard-caps via its own ge/le
 * bounds and the list is naturally bounded by the org's active gate
 * volume — Phase 2's largest customer is unlikely to have >100 pending
 * reviews at a single point in time.
 */

import { useQuery } from "@tanstack/react-query";

import { getApprovals } from "@/lib/api-client";
import type {
  ApprovalListResponse,
  ApprovalQueryParams,
  RiskTier,
} from "@/lib/api-types";

export interface PendingApprovalsParams {
  /** Optional risk-tier server filter (low/medium/high/critical). */
  risk_tier?: RiskTier;
  /** Page size. Default 100; backend ge=1 le=500. */
  limit?: number;
  offset?: number;
}

export function usePendingApprovals(params?: PendingApprovalsParams) {
  const query: ApprovalQueryParams = {
    status: "pending",
    risk_tier: params?.risk_tier,
    limit: params?.limit ?? 100,
    offset: params?.offset ?? 0,
  };

  return useQuery<ApprovalListResponse>({
    queryKey: ["reviews", "queue", query],
    queryFn: () => getApprovals(query),
    staleTime: 10_000,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return false;
      // While the queue has any pending row, poll every 15s — keeps
      // expiry countdowns from drifting and new reviews surface within
      // one cadence. Idle when the queue is empty (reviewer cleared
      // everything) so we don't burn cycles on an inert page.
      const hasPending = data.approvals.some((a) => a.status === "pending");
      return hasPending ? 15_000 : false;
    },
  });
}
