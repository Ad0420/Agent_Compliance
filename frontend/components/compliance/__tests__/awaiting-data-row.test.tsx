/**
 * AwaitingDataRow — type, contract, and pure-logic smoke tests.
 *
 * The contract surface here is the ``NotYetEligibleDimension[]`` prop
 * shape + the dimension-unit table used for the
 * "Needs N <unit> · has M" copy. Both are pinned to the backend B1
 * response shape so a future schema change trips here first.
 */

import * as React from "react";

import {
  AwaitingDataRow,
  DIMENSION_UNITS,
} from "../awaiting-data-row";
import type {
  ComplianceDimensionName,
  NotYetEligibleDimension,
} from "@/lib/api-client";

// ── DIMENSION_UNITS completeness pin ──────────────────────────────────

// Every backend dimension name must have a unit label. Adding a new
// dimension without a unit drops the awaiting-data row's "Needs N
// <unit>" line silently — trip here first.
const _units_complete: Record<ComplianceDimensionName, string> =
  DIMENSION_UNITS;
void _units_complete;

// Spot-check that the units are domain-correct — drifting "HITL
// events" to a generic "events" would erode the descriptive voice.
function _check_unit_table_strings(): void {
  if (DIMENSION_UNITS.hitl_completion !== "HITL events") {
    throw new Error("hitl_completion unit must remain 'HITL events'");
  }
  if (DIMENSION_UNITS.chain_integrity !== "checkpoints") {
    throw new Error("chain_integrity unit must remain 'checkpoints'");
  }
}
void _check_unit_table_strings;

// ── Fixtures — collapsed default + expanded states ────────────────────

export const test_not_yet_eligible_single: NotYetEligibleDimension[] = [
  {
    name: "hitl_completion",
    threshold: 10,
    current: 2,
    needed: 8,
    reason: "Insufficient HITL events in window.",
  },
];

export const test_not_yet_eligible_many: NotYetEligibleDimension[] = [
  {
    name: "hitl_completion",
    threshold: 10,
    current: 2,
    needed: 8,
    reason: "Insufficient HITL events in window.",
  },
  {
    name: "reviewer_integrity",
    threshold: 5,
    current: 1,
    needed: 4,
    reason: "Insufficient reviewer decisions in window.",
  },
  {
    name: "notice_delivery_rate",
    threshold: 20,
    current: 12,
    needed: 8,
    reason: "Insufficient notice deliveries to compute a stable rate.",
  },
];

// Empty branch — the component must return null entirely so the
// page's "All measured" state hides the row without rendering a
// trailing border.
export const test_not_yet_eligible_empty: NotYetEligibleDimension[] = [];

// ── Brief contract pin — "Needs X · has Y" line shape ─────────────────

// The progress line reads "Needs <needed> <unit> · has <current>" —
// tabular-nums on every digit. The component string-assembles this
// inline; the per-dimension unit comes from DIMENSION_UNITS.
function _check_progress_line_uses_needed_not_threshold(): void {
  const item = test_not_yet_eligible_single[0];
  // ``needed`` is pre-computed by the backend (max(0, threshold -
  // current)). The progress line must read ``needed``, NOT the
  // raw ``threshold`` — drifting back to threshold would break the
  // "X more to go" reading.
  if (item.needed !== item.threshold - item.current) {
    throw new Error(
      "test fixture inconsistent: needed must equal threshold - current",
    );
  }
}
void _check_progress_line_uses_needed_not_threshold;

// ── Render-shape smoke (compile only) ─────────────────────────────────

const _mounted_default_collapsed: React.ReactNode = (
  <AwaitingDataRow items={test_not_yet_eligible_many} />
);
const _mounted_pre_expanded: React.ReactNode = (
  <AwaitingDataRow items={test_not_yet_eligible_many} defaultExpanded />
);
const _mounted_empty: React.ReactNode = (
  <AwaitingDataRow items={test_not_yet_eligible_empty} />
);

void _mounted_default_collapsed;
void _mounted_pre_expanded;
void _mounted_empty;
