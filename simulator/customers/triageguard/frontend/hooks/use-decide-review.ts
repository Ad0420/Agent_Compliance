"use client";

/**
 * `useDecideReview()` — submit a HITL decision for a pending review.
 *
 * The nurse name is sourced from the auth provider; the view layer just
 * supplies the review id, the decision (`confirm` or `escalate`), and an
 * optional note.
 */

import * as React from "react";

import { decideReview } from "@/lib/api/reviews";
import { useAuth } from "./use-auth";

interface UseDecideReviewResult {
  decide(
    reviewId: string,
    decision: "confirm" | "escalate",
    note?: string,
  ): Promise<void>;
  isDeciding: boolean;
  error: Error | null;
}

export function useDecideReview(): UseDecideReviewResult {
  const { signedInAs } = useAuth();
  const [isDeciding, setIsDeciding] = React.useState<boolean>(false);
  const [error, setError] = React.useState<Error | null>(null);

  const decide = React.useCallback(
    async (
      reviewId: string,
      decision: "confirm" | "escalate",
      note?: string,
    ) => {
      setIsDeciding(true);
      setError(null);
      try {
        // Fall back to a generic label if the user isn't fully resolved
        // — the backend requires `nurse`, and an empty string would
        // fail schema validation.
        const nurse = signedInAs ?? "TriageGuard User";
        await decideReview(reviewId, decision, nurse, note);
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setIsDeciding(false);
      }
    },
    [signedInAs],
  );

  return { decide, isDeciding, error };
}
