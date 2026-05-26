"use client";

/**
 * `useReviewInbox()` — Review Inbox list with polling for pending rows.
 *
 * `useDecideReview()` — exposes `decide(approvalId, decision, note?)`,
 *   which routes through the backend → Vera SDK → audit chain.
 *
 * The list polls every 3 seconds while the clinician is viewing it so
 * new arrivals (delivered via Vera's `review.requested` webhook) show
 * up without a manual refresh. The cadence is intentionally slow — the
 * EHR demo isn't a paging trader; a clinician looking at the inbox sees
 * it freshen within a heartbeat.
 */

import * as React from "react";

import { decideReview, listReviews } from "@/lib/api/reviews";
import type {
  DecideReviewInput,
  ReviewInboxItem,
  ReviewListFilter,
} from "@/lib/api/types";

const POLL_INTERVAL_MS = 3000;

export interface UseReviewInboxOptions {
  status?: ReviewListFilter;
}

export interface UseReviewInboxResult {
  items: ReviewInboxItem[];
  total: number;
  isLoading: boolean;
  error: Error | null;
  refetch(): Promise<void>;
}

export function useReviewInbox(
  options: UseReviewInboxOptions = {},
): UseReviewInboxResult {
  const status = options.status ?? "pending";
  const [state, setState] = React.useState<{
    items: ReviewInboxItem[];
    total: number;
    isLoading: boolean;
    error: Error | null;
  }>({ items: [], total: 0, isLoading: true, error: null });

  const fetchOnce = React.useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      try {
        const res = await listReviews({ status, signal });
        if (signal?.aborted) return;
        setState({
          items: res.items,
          total: res.total,
          isLoading: false,
          error: null,
        });
      } catch (err) {
        if (signal?.aborted) return;
        const e = err instanceof Error ? err : new Error(String(err));
        setState((prev) => ({ ...prev, isLoading: false, error: e }));
      }
    },
    [status],
  );

  React.useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const tick = async () => {
      if (stopped) return;
      await fetchOnce(controller.signal);
      if (stopped) return;
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    // Initial state already has isLoading=true; fetchOnce flips it false
    // on the first response (or surfaces an error). Avoid an additional
    // setState here that React 19's lint rule flags as a cascading
    // render.
    void tick();

    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [fetchOnce]);

  const refetch = React.useCallback(async (): Promise<void> => {
    await fetchOnce();
  }, [fetchOnce]);

  return {
    items: state.items,
    total: state.total,
    isLoading: state.isLoading,
    error: state.error,
    refetch,
  };
}


export interface UseDecideReviewResult {
  decide(
    approvalId: string,
    decision: "approve" | "reject",
    note?: string,
    reviewerRole?: string,
  ): Promise<ReviewInboxItem>;
  isDeciding: boolean;
  error: Error | null;
}

export function useDecideReview(): UseDecideReviewResult {
  const [isDeciding, setIsDeciding] = React.useState<boolean>(false);
  const [error, setError] = React.useState<Error | null>(null);

  const decide = React.useCallback(
    async (
      approvalId: string,
      decision: "approve" | "reject",
      note?: string,
      reviewerRole?: string,
    ): Promise<ReviewInboxItem> => {
      setIsDeciding(true);
      setError(null);
      try {
        const input: DecideReviewInput = {
          decision,
          note,
          reviewer_role: reviewerRole,
        };
        const updated = await decideReview(approvalId, input);
        return updated;
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setIsDeciding(false);
      }
    },
    [],
  );

  return { decide, isDeciding, error };
}
