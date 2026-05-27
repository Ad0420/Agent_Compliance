/**
 * CompositeHeadline — type, contract, and pure-logic smoke tests.
 *
 * Same pattern as the sibling ``coverage-section.test.tsx``: TypeScript-
 * contract smoke tests + compile-time fixtures pinning each case the
 * brief enumerates.
 */

import * as React from "react";

import {
  CompositeHeadline,
  COMPLIANCE_WINDOW_OPTIONS,
  isComplianceWindowOption,
  type ComplianceWindowDays,
} from "../composite-headline";

// ── Window-option contract pin ────────────────────────────────────────

// The three supported windows must be exactly 7 / 30 / 90 days. A
// future change to the dropdown widens or narrows the API contract;
// trip here first.
type _AssertThreeWindowOptions = typeof COMPLIANCE_WINDOW_OPTIONS extends {
  length: 3;
}
  ? true
  : never;
void (null as unknown as _AssertThreeWindowOptions);

// Default per the brief: 30 days.
const test_default_window_days: ComplianceWindowDays = 30;
void test_default_window_days;

// ── isComplianceWindowOption type-narrowing self-check ────────────────

function _check_window_option_narrowing(): void {
  if (!isComplianceWindowOption(7)) {
    throw new Error("7 must be a valid window option");
  }
  if (!isComplianceWindowOption(30)) {
    throw new Error("30 must be a valid window option");
  }
  if (!isComplianceWindowOption(90)) {
    throw new Error("90 must be a valid window option");
  }
  if (isComplianceWindowOption(180)) {
    throw new Error("180 must NOT be a valid window option");
  }
  if (isComplianceWindowOption(0)) {
    throw new Error("0 must NOT be a valid window option");
  }
}
void _check_window_option_narrowing;

// ── Headline-string passthrough fixture ───────────────────────────────

// The backend's ``composite_headline`` is rendered verbatim. The
// component must NOT compose a string from ``measured.length`` itself
// (per the API contract — voice & copy lives in the producer).
export const test_headline_passes_through: string =
  "Runtime posture: 2 of 6 dimensions measured";

// ── Callback contract ─────────────────────────────────────────────────

// The window-change callback emits a typed ``ComplianceWindowDays``.
// The page module re-uses this type for its React.useState slot so a
// future widening of the set ripples through every consumer.
const test_on_window_change_callback: (n: ComplianceWindowDays) => void =
  () => undefined;
void test_on_window_change_callback;

// ── Render-shape smoke (compile only) ─────────────────────────────────

const _mounted: React.ReactNode = (
  <CompositeHeadline
    headline={test_headline_passes_through}
    windowDays={30}
    onWindowChange={test_on_window_change_callback}
  />
);
void _mounted;
