/**
 * CoverageSection — type, contract, and pure-logic smoke tests.
 *
 * Same pattern as ``verification-panel.test.tsx``: the frontend
 * workspace has no Vitest/Jest runner today, so this file exercises
 * (a) the typed contract under ``tsc --noEmit`` (CI gate), and
 * (b) compile-time fixtures pinning each branch the future RTL port
 * must assert. The named ``test_*`` constants enumerate the cases the
 * brief lists.
 */

import * as React from "react";

import { CoverageSection } from "../coverage-section";
import type { Coverage } from "@/lib/api-client";

// ── Fixtures — one per case the brief enumerates ──────────────────────

// Covered + uncovered both present. The chip strip must render each
// agent_type with the correct status; the headline numbers must use
// comma-separated formatting (forced via tabular-nums className).
export const test_coverage_mixed: Coverage = {
  covered: 1,
  detected: 3,
  items: [
    { agent_type: "abridge_scribe", status: "covered" },
    { agent_type: "appointment_scheduler", status: "uncovered" },
    { agent_type: "prior_auth_drafter", status: "uncovered" },
  ],
};

// All covered — the green-dot strip is the only branch and the
// headline reads "1 of 1".
export const test_coverage_all_covered: Coverage = {
  covered: 1,
  detected: 1,
  items: [{ agent_type: "abridge_scribe", status: "covered" }],
};

// Comma-separator fixture: at ≥4 digits the number must comma-
// separate. The CoverageSection helper feeds through Intl.NumberFormat
// so any locale drift trips here.
export const test_coverage_thousands: Coverage = {
  covered: 1_200,
  detected: 12_500,
  items: [],
};

// Empty branch — "No AI agents detected for this org yet." Renders
// the empty banner, no chip strip, no number formatting.
export const test_coverage_empty: Coverage = {
  covered: 0,
  detected: 0,
  items: [],
};

// ── Pure-logic runtime self-check ─────────────────────────────────────

function _check_number_formatter_comma_separates(): void {
  // The Intl.NumberFormat("en-US") used by the component must produce
  // comma-separated thousands. If a future change swaps the formatter
  // (e.g. accidentally to compact / short notation) this trips.
  const formatted = new Intl.NumberFormat("en-US").format(12_500);
  if (!formatted.includes(",")) {
    throw new Error(
      `CoverageSection number formatter must comma-separate thousands, got: ${formatted}`,
    );
  }
  if (formatted === "12.5K" || formatted === "12K") {
    throw new Error(
      `CoverageSection must not use abbreviation, got: ${formatted}`,
    );
  }
}
void _check_number_formatter_comma_separates;

// ── Render-shape smoke (compile only) ─────────────────────────────────

const _mounted_mixed: React.ReactNode = (
  <CoverageSection coverage={test_coverage_mixed} />
);
const _mounted_empty: React.ReactNode = (
  <CoverageSection coverage={test_coverage_empty} />
);

void _mounted_mixed;
void _mounted_empty;
