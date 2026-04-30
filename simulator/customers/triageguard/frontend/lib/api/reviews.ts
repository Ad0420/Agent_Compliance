/**
 * Reviews endpoint — wakes a paused triage workflow with a nurse decision.
 */

import { request } from "./client";
import type { DecideReviewResponse } from "./types";

/**
 * Submit a HITL decision for a pending nurse review.
 *
 * The backend forwards the call into the simulator's `nurse_callback`,
 * which resumes `run_session`. The terminal event arrives shortly after
 * on the SSE stream — callers should not block on this returning to know
 * the workflow finished.
 *
 * `confirm` keeps the AI classifier's level. `escalate` adopts the
 * red-flag detector's `recommended_override` (typically ER).
 *
 * @param reviewId  Vera approval id surfaced via the `nurse_review_requested` SSE event.
 * @param decision  `"confirm"` (keep AI level) or `"escalate"` (use override).
 * @param nurse     Display name to attribute the decision to (defaults to the signed-in user).
 * @param note      Free-form nurse note. Optional.
 *
 * Throws `ApiError(404)` when the review has already been resolved or
 * never reached the gate.
 */
export async function decideReview(
  reviewId: string,
  decision: "confirm" | "escalate",
  nurse: string,
  note?: string,
): Promise<DecideReviewResponse> {
  return request<DecideReviewResponse>(
    `/api/reviews/${encodeURIComponent(reviewId)}/decide`,
    {
      method: "POST",
      body: {
        decision,
        nurse,
        note: note ?? null,
      },
    },
  );
}
