/**
 * ReviewRecommendations — type & contract smoke tests.
 *
 * Wave 2D PR C4. Same pattern as
 * `frontend/components/customers/__tests__/decision-row.test.tsx` —
 * the main `frontend/` workspace has no Vitest/Jest runner yet, so this
 * file exercises the typed contract under `npx tsc --noEmit` (which CI
 * runs via `.github/workflows/frontend-typecheck.yml`).
 *
 * Each `test_*` fixture constructs a realistic `ReviewRecommendation`
 * (or response envelope) so:
 *
 *   1. Any future shape change in `ReviewRecommendation` /
 *      `ReviewRecommendationsResponse` / `RecommendationSeverity` fails
 *      the typecheck loudly here, not silently when Phase 4 wires the
 *      endpoint.
 *   2. When the test runner lands, these fixtures drop straight into
 *      `render(<ReviewRecommendations state="populated" recommendations={...} />)`
 *      assertions with zero rework.
 *
 * Three states are covered (`loading`, `empty`, `populated`), plus the
 * `onApply` callback wiring shape.
 */

import * as React from "react";

import { ReviewRecommendations } from "../review-recommendations";
import type {
  RecommendationSeverity,
  ReviewRecommendation,
  ReviewRecommendationsResponse,
} from "@/lib/api-types";

// ── Recommendation fixtures (one per non-INFO severity) ────────────────

export const test_rec_high: ReviewRecommendation = {
  id: "rec-1",
  severity: "HIGH",
  title: "Reviewer credentials gap on 3 of last 7 days",
  description:
    "Reviewer dr-jane@example.org attested 5 DEA-gate decisions with MD-only credentials. Vera correctly rejected each, but the pattern suggests roster misconfiguration.",
  quoted_source:
    "21 CFR 1306.04 — Only a practitioner registered with DEA may issue prescriptions for controlled substances.",
  suggested_action:
    "Open a counsel-review task on the Cleveland Clinic reviewer roster to confirm DEA registration coverage.",
  apply_action: "create_task:reviewer_roster_audit",
};

export const test_rec_medium: ReviewRecommendation = {
  id: "rec-2",
  severity: "MEDIUM",
  title: "3 decisions below review-time threshold from reviewer X",
  description:
    "Reviewer dr-smith decided 3 HITL reviews in <30s each over the last 7 days, below the configured 60s integrity floor.",
  quoted_source:
    "HIPAA § 164.312(b) — Audit controls. Implement hardware, software, and procedural mechanisms that record and examine activity in information systems.",
  suggested_action:
    "Open a counsel-review task documenting the integrity-floor pattern for next quarterly compliance review.",
  apply_action: "create_task:reviewer_integrity_review",
};

export const test_rec_low: ReviewRecommendation = {
  id: "rec-3",
  severity: "LOW",
  title: "Webhook retry rate drifting up",
  description:
    "Webhook subscription health: 4% retry rate over the last 24h, up from 0.8% baseline. No deliveries aborted.",
  quoted_source:
    "Internal SLO: webhook retry rate < 2% sustained over 24h triggers an integrations-health investigation.",
  suggested_action:
    "Open a task to check the customer's webhook receiver health page.",
  apply_action: "create_task:webhook_health_check",
};

export const test_rec_info: ReviewRecommendation = {
  id: "rec-4",
  severity: "INFO",
  title: "Pattern detection ran with no findings",
  description:
    "AI Insights ran against the last 7 days of decisions and surfaced no actionable patterns. This card is informational; no task created.",
  quoted_source:
    "Vera Compliance Posture — AI Insights are advisory and never constitute regulatory advice.",
  suggested_action: "No action required. Recommendations will refresh hourly.",
  apply_action: "noop",
};

// ── Response envelope fixture (what Phase 4 endpoint returns) ──────────

export const test_recommendations_response: ReviewRecommendationsResponse = {
  recommendations: [test_rec_high, test_rec_medium, test_rec_low],
  generated_at: "2026-05-24T14:00:00.000Z",
  model: "claude-haiku-4.x",
};

export const test_recommendations_response_empty: ReviewRecommendationsResponse = {
  recommendations: [],
  generated_at: "2026-05-24T14:00:00.000Z",
  model: "claude-haiku-4.x",
};

// ── Render-shape smoke (validates props compile for every state) ───────
//
// Each entry below is a JSX expression — TS will reject any future
// signature change that breaks the call site. Nothing is mounted; this
// is a contract test, not a behavior test.

// "loading" state — no recommendations prop required.
const _loading_node: React.ReactNode = (
  <ReviewRecommendations state="loading" />
);

// "empty" state — Phase 2 default; explicit and via undefined list.
const _empty_explicit_node: React.ReactNode = (
  <ReviewRecommendations state="empty" />
);
const _empty_via_undefined_node: React.ReactNode = (
  <ReviewRecommendations state="populated" />
);
const _empty_via_zero_node: React.ReactNode = (
  <ReviewRecommendations state="populated" recommendations={[]} />
);

// "populated" state — multi-severity + onApply wiring.
let _apply_invoked_with: string | null = null;
const _populated_node: React.ReactNode = (
  <ReviewRecommendations
    state="populated"
    recommendations={test_recommendations_response.recommendations}
    onApply={(id) => {
      // Phase 2 host: no-op. Phase 4 host: dispatch task creation.
      _apply_invoked_with = id;
    }}
  />
);

// "populated" state — no onApply (Apply button hidden per primitive).
const _populated_no_apply_node: React.ReactNode = (
  <ReviewRecommendations
    state="populated"
    recommendations={[test_rec_info]}
  />
);

// Mark intentionally-unused locals so ESLint doesn't strip them.
void _loading_node;
void _empty_explicit_node;
void _empty_via_undefined_node;
void _empty_via_zero_node;
void _populated_node;
void _populated_no_apply_node;
void _apply_invoked_with;

// ── Exhaustiveness assertion ───────────────────────────────────────────
//
// If a new RecommendationSeverity is added to api-types without a
// corresponding update here, the switch fallthrough below stops being
// exhaustive and TS errors out. Mirrors the Phase 4 contract surface.

function _exhaust_severity(s: RecommendationSeverity): string {
  switch (s) {
    case "HIGH":
      return "brick";
    case "MEDIUM":
      return "amber";
    case "LOW":
      return "olive";
    case "INFO":
      return "ink-2";
  }
}

void _exhaust_severity;
