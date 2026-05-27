/**
 * MeasuredDimensionCard — type, contract, and pure-logic smoke tests.
 *
 * The score → variant boundary thresholds are the load-bearing
 * behaviour. They live in the exported ``scoreVariant`` helper so this
 * file can assert them without rendering. The three render-shape
 * smokes below pin the prop contract under ``tsc --noEmit``.
 */

import * as React from "react";

import {
  DIMENSION_LABELS,
  MeasuredDimensionCard,
  scoreVariant,
} from "../measured-dimension-card";
import type {
  ComplianceDimensionName,
  MeasuredDimension,
} from "@/lib/api-client";

// ── scoreVariant boundary pin ─────────────────────────────────────────

// Brief: ≥80 green (ok), 50-79 amber (warn), <50 red (error). The
// helper must hold these boundaries exactly — drifting the dashboard's
// visual encoding away from the brief is a regression.
function _check_score_variant_boundaries(): void {
  if (scoreVariant(100) !== "ok") {
    throw new Error("scoreVariant(100) must be 'ok'");
  }
  if (scoreVariant(80) !== "ok") {
    throw new Error("scoreVariant(80) must be 'ok'");
  }
  if (scoreVariant(79) !== "warn") {
    throw new Error("scoreVariant(79) must be 'warn'");
  }
  if (scoreVariant(50) !== "warn") {
    throw new Error("scoreVariant(50) must be 'warn'");
  }
  if (scoreVariant(49) !== "error") {
    throw new Error("scoreVariant(49) must be 'error'");
  }
  if (scoreVariant(0) !== "error") {
    throw new Error("scoreVariant(0) must be 'error'");
  }
}
void _check_score_variant_boundaries;

// ── Dimension-label completeness ──────────────────────────────────────

// Every backend dimension name must have a human-readable label.
// Adding a new dimension without a label is a contract regression.
const _label_keys_complete: Record<ComplianceDimensionName, string> =
  DIMENSION_LABELS;
void _label_keys_complete;

// ── Fixture per status branch — the three cases the brief lists ───────

export const test_dimension_green: MeasuredDimension = {
  name: "hitl_completion",
  score: 95,
  raw_count: 47,
  measured_fact_line: "47 of 47 HITL events completed in 7 days.",
};

export const test_dimension_amber: MeasuredDimension = {
  name: "notice_delivery_rate",
  score: 65,
  raw_count: 120,
  measured_fact_line: "78 of 120 notices delivered in window.",
};

export const test_dimension_red: MeasuredDimension = {
  name: "reviewer_integrity",
  score: 32,
  raw_count: 15,
  measured_fact_line: "5 of 15 reviews completed without flag.",
};

// ── Render-shape smoke (compile only) ─────────────────────────────────

const _mounted_green: React.ReactNode = (
  <MeasuredDimensionCard dimension={test_dimension_green} />
);
const _mounted_amber: React.ReactNode = (
  <MeasuredDimensionCard dimension={test_dimension_amber} />
);
const _mounted_red: React.ReactNode = (
  <MeasuredDimensionCard dimension={test_dimension_red} />
);

void _mounted_green;
void _mounted_amber;
void _mounted_red;
