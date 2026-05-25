"use client";

/**
 * ReviewRecommendations — Wave 2D PR C4 scaffold.
 *
 * Per v1-implementation-plan.md Phase 2 line 122:
 *   "Recommendation card (AI Insights pattern) surfaces on the Review
 *    queue page when patterns appear ('3 decisions below review-time
 *    threshold from reviewer X in the last 7 days') — empty in this
 *    phase, wired up in Phase 4."
 *
 * Phase 2 (this PR) ships:
 *   - The typed component contract matching the Phase 4 AI Insights
 *     response shape (`ReviewRecommendationsResponse`).
 *   - A `loading | empty | populated` state machine so Phase 4 wiring
 *     just flips state, no rewrite.
 *   - Reuse of the existing `RecommendationCard` primitive (Phase 1
 *     PR 0b) — this component is a thin renderer, not a new visual.
 *   - "empty" state renders nothing visible (per the spec — no
 *     placeholder card chrome on quiet weeks).
 *
 * Phase 4 will:
 *   - Add `POST /v1/compliance/insights` (Haiku-class on-demand call).
 *   - Wire the Review queue page to fetch this on mount.
 *   - Implement `onApply` to create a counsel-review task (no
 *     auto-mutation of action records or posture math — see
 *     v1-test-plan.md Phase 4 row "AI Insights 'Apply' no-side-effect").
 *
 * Coordination with Wave 2D PR C2 (Review queue page): until both PRs
 * land, C2 may render a placeholder div with a TODO pointing here.
 * After both merge, C2 imports this component and passes
 * `state="empty"` until Phase 4 wires the fetch.
 */

import { Loading } from "@/components/ui/loading";
import { RecommendationCard } from "@/components/ui/recommendation-card";
import type { ReviewRecommendation } from "@/lib/api-types";

export type ReviewRecommendationsState = "loading" | "empty" | "populated";

export interface ReviewRecommendationsProps {
  /**
   * State machine for the scaffold:
   *   - `loading`: insights fetch in flight (Phase 4 only — Phase 2
   *     never enters this state because no fetch exists yet).
   *   - `empty`: no recommendations to show (no patterns detected, or
   *     Phase 2 default). Renders nothing visible.
   *   - `populated`: render one `RecommendationCard` per item in
   *     `recommendations`.
   */
  state: ReviewRecommendationsState;
  /**
   * Recommendations to render when `state === "populated"`. Ignored
   * (and may be omitted) for `loading` / `empty`. An empty array in
   * `populated` falls back to the empty render path.
   */
  recommendations?: ReviewRecommendation[];
  /**
   * Called when the user clicks "Apply recommendation" on a card.
   * Receives the recommendation `id` so the host can dispatch the
   * Phase 4 task-creation call. Phase 2: not invoked (no cards
   * render). Phase 4: host wires this to `POST /v1/tasks` or similar.
   *
   * Passing `undefined` hides the Apply button (per the primitive's
   * own contract).
   */
  onApply?: (recommendationId: string) => void;
}

/**
 * Map the wire-level `RecommendationSeverity` (`HIGH | MEDIUM | LOW
 * | INFO`) directly to the primitive's `Severity` — they're the same
 * vocabulary by design. Type identity is enforced at the call site
 * below.
 */
export function ReviewRecommendations({
  state,
  recommendations,
  onApply,
}: ReviewRecommendationsProps) {
  if (state === "loading") {
    return (
      <Loading.Spinner
        aria-label="Loading recommendations"
        // Inline next to whatever triggered the load (per
        // dashboard-design-system.md §Loading state — Spinner is
        // for the 200ms-2s action window).
      />
    );
  }

  if (
    state === "empty" ||
    !recommendations ||
    recommendations.length === 0
  ) {
    // Empty state: render nothing. Per the spec, a "no patterns
    // detected" placeholder card reads as noise on quiet weeks. The
    // Review queue is meaningful on its own; recommendations only
    // surface when there is something to say.
    return null;
  }

  return (
    <div
      data-slot="review-recommendations"
      className="flex flex-col gap-3"
      role="region"
      aria-label="AI Insights recommendations"
    >
      {recommendations.map((r) => (
        <RecommendationCard
          key={r.id}
          severity={r.severity}
          title={r.title}
          description={r.description}
          quotedSource={r.quoted_source}
          suggestedAction={r.suggested_action}
          onApply={onApply ? () => onApply(r.id) : undefined}
        />
      ))}
    </div>
  );
}
