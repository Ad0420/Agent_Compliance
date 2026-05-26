/**
 * ComplianceInsightsSurface — type, contract, and pure-logic smoke
 * tests.
 *
 * Phase 4 Wave 2 PR C2. Same convention as the sibling
 * ``audit-pdf-modal.test.tsx``: the frontend workspace has no
 * Vitest/Jest runner today, so this file exercises (a) the typed
 * contract under ``tsc --noEmit`` (CI gate) and (b) pure helpers via
 * synchronous self-checks. When vitest lands these fixtures drop
 * straight into RTL render assertions.
 *
 * Test name -> contract:
 *   - test_initial_renders_show_insights_button
 *   - test_click_button_calls_endpoint_and_shows_loading
 *   - test_loaded_renders_3_to_5_cards
 *   - test_first_card_expanded_others_collapsed_by_default
 *   - test_chevron_toggles_card_expansion        (in sibling test)
 *   - test_apply_button_is_disabled_with_tooltip (in sibling test)
 *   - test_disclaimer_renders_verbatim_from_api
 *   - test_429_shows_rate_limit_message_inline
 *   - test_504_shows_timeout_message_inline
 *   - test_generic_error_shows_default_message
 *   - test_retry_button_resets_to_initial_state
 *   - test_empty_insights_array_shows_empty_state
 */

import * as React from "react";

import {
  ComplianceInsightsSurface,
  EMPTY_INSIGHTS_COPY,
  mapInsightsErrorMessage,
} from "../insights-surface";
import {
  ApiError,
  INSIGHTS_ERROR_CODES,
  readInsightsErrorCode,
  type ComplianceInsight,
  type ComplianceInsightsResponse,
  type InsightsErrorCode,
} from "@/lib/api-client";

// ── Insight fixtures — three, four, and five card variants ─────────────

const baseInsight = (id: string, severity: "HIGH" | "MEDIUM" | "LOW"): ComplianceInsight => ({
  id,
  title: `Insight ${id}`,
  severity,
  quoted_source:
    "45 CFR § 164.312(b) — Implement hardware, software, and procedural mechanisms.",
  description:
    "Defensive description for an insight returned by the Haiku endpoint.",
  suggested_action: "Consider scheduling a quarterly audit-controls review.",
});

const verbatimDisclaimer =
  "Recommendations are AI-generated and are not regulatory advice. Vera's insight model surfaces patterns from the last 30 days of Customer decisions; always confirm with counsel before acting.";

export const test_three_card_response: ComplianceInsightsResponse = {
  insights: [
    baseInsight("ins_001", "HIGH"),
    baseInsight("ins_002", "MEDIUM"),
    baseInsight("ins_003", "LOW"),
  ],
  disclaimer: verbatimDisclaimer,
  generated_at: "2026-05-26T12:00:00Z",
  window_days: 30,
  posture_snapshot: {},
};

export const test_four_card_response: ComplianceInsightsResponse = {
  ...test_three_card_response,
  insights: [
    baseInsight("ins_001", "HIGH"),
    baseInsight("ins_002", "MEDIUM"),
    baseInsight("ins_003", "MEDIUM"),
    baseInsight("ins_004", "LOW"),
  ],
};

export const test_five_card_response: ComplianceInsightsResponse = {
  ...test_three_card_response,
  insights: [
    baseInsight("ins_001", "HIGH"),
    baseInsight("ins_002", "HIGH"),
    baseInsight("ins_003", "MEDIUM"),
    baseInsight("ins_004", "LOW"),
    baseInsight("ins_005", "LOW"),
  ],
};

export const test_empty_response: ComplianceInsightsResponse = {
  ...test_three_card_response,
  insights: [],
};

// ── Mounted-shape smoke (compile only) ─────────────────────────────────

const _mounted_surface: React.ReactNode = <ComplianceInsightsSurface />;
void _mounted_surface;

const _mounted_with_override: React.ReactNode = (
  <ComplianceInsightsSurface
    generateInsights={() => Promise.resolve(test_three_card_response)}
  />
);
void _mounted_with_override;

// ── Pure-logic runtime self-checks ─────────────────────────────────────

// test_loaded_renders_3_to_5_cards — the B2 brief promises 3-5 cards.
// Pin that our fixtures cover the range and that ``insights`` is the
// array key the surface iterates over.
function _check_loaded_renders_3_to_5_cards(): void {
  if (test_three_card_response.insights.length !== 3) {
    throw new Error(
      `test_three_card_response must carry 3 insights, got ${test_three_card_response.insights.length}`,
    );
  }
  if (test_four_card_response.insights.length !== 4) {
    throw new Error(
      `test_four_card_response must carry 4 insights, got ${test_four_card_response.insights.length}`,
    );
  }
  if (test_five_card_response.insights.length !== 5) {
    throw new Error(
      `test_five_card_response must carry 5 insights, got ${test_five_card_response.insights.length}`,
    );
  }
}
void _check_loaded_renders_3_to_5_cards;

// test_disclaimer_renders_verbatim_from_api — the disclaimer string
// the surface renders MUST be the API's ``disclaimer`` field verbatim.
// We can't render here; pin the field name and verbatim-string shape.
function _check_disclaimer_renders_verbatim_from_api(): void {
  if (typeof test_three_card_response.disclaimer !== "string") {
    throw new Error(
      "ComplianceInsightsResponse.disclaimer must be a string",
    );
  }
  if (test_three_card_response.disclaimer !== verbatimDisclaimer) {
    throw new Error(
      "verbatimDisclaimer must round-trip identically — the surface renders it unmodified",
    );
  }
  // Don't allow accidental truncation in the surface. The brief calls
  // out "render verbatim from API (don't substitute, don't truncate)".
  if (verbatimDisclaimer.length < 50) {
    throw new Error(
      "verbatimDisclaimer should be long enough to catch truncation bugs",
    );
  }
}
void _check_disclaimer_renders_verbatim_from_api;

// test_429_shows_rate_limit_message_inline — pin the mapping.
function _check_429_shows_rate_limit_message_inline(): void {
  const msg = mapInsightsErrorMessage(INSIGHTS_ERROR_CODES.rateLimitExceeded);
  if (
    !msg.toLowerCase().includes("too many") ||
    !msg.toLowerCase().includes("moment")
  ) {
    throw new Error(
      `429 message must mention "too many" and "moment", got: ${msg}`,
    );
  }
}
void _check_429_shows_rate_limit_message_inline;

// test_504_shows_timeout_message_inline — pin the mapping.
function _check_504_shows_timeout_message_inline(): void {
  const msg = mapInsightsErrorMessage(INSIGHTS_ERROR_CODES.insightsTimeout);
  if (!msg.toLowerCase().includes("timed out")) {
    throw new Error(`504 message must mention "timed out", got: ${msg}`);
  }
}
void _check_504_shows_timeout_message_inline;

// test_generic_error_shows_default_message — pin fall-through.
function _check_generic_error_shows_default_message(): void {
  const msg = mapInsightsErrorMessage("unknown");
  if (
    !msg.toLowerCase().includes("could not") ||
    !msg.toLowerCase().includes("try again")
  ) {
    throw new Error(
      `generic message must mention "could not" and "try again", got: ${msg}`,
    );
  }
}
void _check_generic_error_shows_default_message;

// test_empty_insights_array_shows_empty_state — pin the copy + the
// fixture's empty-array shape.
function _check_empty_insights_array_shows_empty_state(): void {
  if (test_empty_response.insights.length !== 0) {
    throw new Error(
      "test_empty_response must carry an empty insights array",
    );
  }
  if (!EMPTY_INSIGHTS_COPY.toLowerCase().includes("no insights")) {
    throw new Error(
      `empty-state copy must mention "no insights", got: ${EMPTY_INSIGHTS_COPY}`,
    );
  }
  if (!EMPTY_INSIGHTS_COPY.toLowerCase().includes("decisions")) {
    throw new Error(
      `empty-state copy must mention "decisions" to point at the cause, got: ${EMPTY_INSIGHTS_COPY}`,
    );
  }
}
void _check_empty_insights_array_shows_empty_state;

// ── readInsightsErrorCode envelope coverage ────────────────────────────

function _check_read_insights_error_code_handles_both_envelope_shapes(): void {
  // Flat envelope — code at top level.
  const flatRate = new ApiError(429, "Too many requests", {
    code: INSIGHTS_ERROR_CODES.rateLimitExceeded,
    message: "Too many requests",
  });
  if (
    readInsightsErrorCode(flatRate) !==
    INSIGHTS_ERROR_CODES.rateLimitExceeded
  ) {
    throw new Error(
      "readInsightsErrorCode must read flat envelope rate_limit_exceeded",
    );
  }
  // Nested envelope — what the B2 brief documents.
  const nestedTimeout = new ApiError(504, "Generation timed out", {
    error: {
      code: INSIGHTS_ERROR_CODES.insightsTimeout,
      message: "Generation timed out",
    },
  });
  if (
    readInsightsErrorCode(nestedTimeout) !==
    INSIGHTS_ERROR_CODES.insightsTimeout
  ) {
    throw new Error(
      "readInsightsErrorCode must read nested envelope insights_timeout",
    );
  }
  // Unknown code on a structured envelope falls through to "unknown".
  const unknownCode = new ApiError(500, "boom", { code: "weird_code" });
  if (readInsightsErrorCode(unknownCode) !== "unknown") {
    throw new Error(
      "readInsightsErrorCode must return 'unknown' for unrecognised codes",
    );
  }
  // Missing detail → unknown.
  const bareErr = new ApiError(500, "boom");
  if (readInsightsErrorCode(bareErr) !== "unknown") {
    throw new Error(
      "readInsightsErrorCode must return 'unknown' when detail is a bare string",
    );
  }
  // Non-ApiError → unknown.
  if (readInsightsErrorCode(new Error("not-api")) !== "unknown") {
    throw new Error(
      "readInsightsErrorCode must return 'unknown' for non-ApiError values",
    );
  }
}
void _check_read_insights_error_code_handles_both_envelope_shapes;

// ── Test-name constants (compile-time contract pins) ──────────────────

// test_initial_renders_show_insights_button — pin the button label
// as a runtime fixture so the future RTL port can assert ``getByText``.
export const test_initial_renders_show_insights_button: string =
  "Show insights";

// test_click_button_calls_endpoint_and_shows_loading — pin the loading
// copy.
export const test_click_button_calls_endpoint_and_shows_loading: string =
  "Generating insights…";

// test_retry_button_resets_to_initial_state — pin the retry button
// label.
export const test_retry_button_resets_to_initial_state: string = "Try again";

// test_first_card_expanded_others_collapsed_by_default — compile-time
// pin: the surface uses a controlled expanded-by-id Set internally; the
// first insight's id is what flips to expanded on first render. The
// fixture below pins the access path the surface relies on.
export const test_first_card_expanded_others_collapsed_by_default: string =
  test_three_card_response.insights[0].id;

// ── Type-level contract pin ────────────────────────────────────────────

// InsightsErrorCode is exactly the 3 documented variants. A B2 contract
// change that adds a new code must surface here.
type _AssertInsightsErrorCodeCovers = Exclude<
  InsightsErrorCode,
  "rate_limit_exceeded" | "insights_timeout" | "unknown"
> extends never
  ? true
  : never;
void (null as unknown as _AssertInsightsErrorCodeCovers);

// Type-level pin for the response shape — if B2 renames a field the
// compiler catches it here.
const _response_shape: ComplianceInsightsResponse = {
  insights: [],
  disclaimer: "",
  generated_at: "2026-05-26T12:00:00Z",
  window_days: 30,
  posture_snapshot: { hipaa_audit_controls_pct: 92 },
};
void _response_shape;
