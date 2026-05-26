/**
 * Review Inbox API — W2.1 in-band HITL.
 *
 * The clinician's "Review Inbox" page calls these endpoints. The
 * Approve/Reject button on a row hits the backend's
 * `/api/reviews/{id}/decide`, which forwards through the audited Vera
 * SDK rather than a raw HTTP call.
 */

import { request } from "./client";
import type {
  DecideReviewInput,
  ReviewInboxItem,
  ReviewListFilter,
  ReviewListResponse,
} from "./types";

export interface ListReviewsOptions {
  /** Default `"pending"`. Use `"all"` to see resolved + expired rows. */
  status?: ReviewListFilter;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

/** List Review Inbox items. */
export async function listReviews(
  options: ListReviewsOptions = {},
): Promise<ReviewListResponse> {
  return request<ReviewListResponse>("/api/reviews", {
    method: "GET",
    query: {
      status: options.status,
      limit: options.limit,
      offset: options.offset,
    },
    signal: options.signal,
  });
}

/** Fetch a single Review Inbox item. */
export async function getReview(approvalId: string): Promise<ReviewInboxItem> {
  return request<ReviewInboxItem>(
    `/api/reviews/${encodeURIComponent(approvalId)}`,
    { method: "GET" },
  );
}

/**
 * Record the clinician's decision. The backend forwards to Vera via the
 * SDK's `complete_review` helper; Vera's `review.completed` webhook flips
 * the row to terminal once the audit chain has the canonical record.
 */
export async function decideReview(
  approvalId: string,
  input: DecideReviewInput,
): Promise<ReviewInboxItem> {
  return request<ReviewInboxItem>(
    `/api/reviews/${encodeURIComponent(approvalId)}/decide`,
    {
      method: "POST",
      body: {
        decision: input.decision,
        reviewer_role: input.reviewer_role ?? "attending_physician",
        note: input.note ?? null,
      },
    },
  );
}
