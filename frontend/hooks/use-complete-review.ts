"use client";

/**
 * useCompleteReview — Wave 2D PR C2.
 *
 * React Query mutation wrapping the A4 endpoint
 * ``POST /v1/reviews/{review_id}/complete``. Invalidates the review-queue
 * cache on success so the row drops out of the listing immediately;
 * non-200s flow through as ``ApiError`` with the structured ``detail``
 * preserved (consumer narrows via ``isReviewerInsufficient`` /
 * ``isAlreadyDecided`` / ``isReviewExpired`` helpers below).
 *
 * The mutation does NOT toast on success/error directly — the form
 * owns the inline error surface (per dashboard-design-system.md voice
 * rule: critical errors render inline next to the action, not as a
 * disappearing toast). The caller can chain a sonner ``toast.success``
 * for the happy path.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { completeReview, ApiError } from "@/lib/api-client";
import type {
  CompleteReviewInput,
  CompleteReviewResponse,
  ReviewerInsufficientDetail,
  AttestationConflictResponse,
} from "@/lib/api-types";

export interface CompleteReviewVariables {
  review_id: string;
  input: CompleteReviewInput;
}

export function useCompleteReview() {
  const qc = useQueryClient();
  return useMutation<CompleteReviewResponse, ApiError, CompleteReviewVariables>(
    {
      mutationFn: ({ review_id, input }) => completeReview(review_id, input),
      onSuccess: () => {
        // Drop the row from the queue cache + nuke any detail caches.
        // Two distinct cache buckets to invalidate:
        //   1. ["reviews", "queue"] — the org-wide queue this page reads.
        //   2. ["approvals"]        — shared with the Home page's
        //      "Things that need you" tile + the existing
        //      /v1/approvals/{id}/decide hook so the count tick-down
        //      is visible without a page reload.
        qc.invalidateQueries({ queryKey: ["reviews", "queue"] });
        qc.invalidateQueries({ queryKey: ["approvals"] });
      },
    },
  );
}

// ── Error-shape narrowing helpers ─────────────────────────────────────
//
// The form maps each documented status to a distinct inline message
// (per the spec in pr-c2-review-queue.md). These helpers keep the
// shape-checking out of the JSX so the renderer stays declarative.

export function isReviewerInsufficient(
  err: unknown,
): err is ApiError & { detail: ReviewerInsufficientDetail } {
  if (!(err instanceof ApiError) || err.status !== 403) return false;
  const d = err.detail;
  return (
    !!d &&
    typeof d === "object" &&
    (d as { code?: unknown }).code === "reviewer_credentials_insufficient"
  );
}

export function isAlreadyDecided(err: unknown): err is ApiError {
  if (!(err instanceof ApiError)) return false;
  // 409 covers both "already resolved" and the Wave 2D A6 "attestation
  // conflict" case. Both surface the same user-facing message — the
  // detail blob is preserved on the ApiError for the audit trail.
  return err.status === 409;
}

export function isReviewExpired(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 410;
}

// 404 is a terminal state in the same sense as 409/410 — the review
// is no longer actionable from this client. Surfaces when a row was
// garbage-collected on the server between the queue fetch and the
// reviewer's click, or when the org_id scope check fails (rare —
// suggests the auth context drifted). UI treats it the same as
// "already decided" + auto-closes the panel.
export function isReviewMissing(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 404;
}

// Convenience guard for the Wave 2D A6 specific code, in case the UI
// later wants to distinguish "another reviewer beat you to it" from
// "you're trying to flip an already-recorded decision". Today both
// flow through ``isAlreadyDecided``.
export function isAttestationConflict(
  err: unknown,
): err is ApiError & { detail: AttestationConflictResponse } {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  const d = err.detail;
  return (
    !!d &&
    typeof d === "object" &&
    (d as { code?: unknown }).code === "attestation_conflict"
  );
}
