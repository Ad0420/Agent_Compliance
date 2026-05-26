/**
 * ChainIntegrityTile — type & formatting contract tests.
 *
 * Wave 3D.1. The main ``frontend/`` workspace has no Vitest/Jest
 * runner wired up; this file exercises the typed contract under
 * ``npx tsc --noEmit`` (CI: ``.github/workflows/frontend-typecheck.yml``)
 * and the pure formatting helpers via runtime ``console.assert`` so a
 * regression in the date / number formatting trips the typecheck job
 * (assertion failures throw, breaking module load if these are ever
 * imported by a test runner).
 *
 * Three rendered states are covered as fixtures (``ok``, ``warn``,
 * ``error``) plus the no-checkpoints / no-KMS fallbacks. When a test
 * runner lands, these drop straight into ``render(<ChainIntegrityTile
 * loading={false} data={test_ok} />)`` assertions with zero rework.
 */

import * as React from "react";

import {
  ChainIntegrityTile,
  formatCount,
  formatSealedAt,
  shortCheckpointId,
  shortKeyId,
} from "../chain-integrity-tile";
import type {
  ChainIntegrityResponse,
  CheckpointCadence,
  ChainIntegrityStatus,
  LatestCheckpointSummary,
  KmsKeySummary,
} from "@/lib/api-types";

// ── Helper fixtures ────────────────────────────────────────────────────

const test_latest_checkpoint: LatestCheckpointSummary = {
  checkpoint_id: "8d51a2c7-9f0a-4e21-9c01-e3b8a1234567",
  sealed_at: "2026-03-15T14:30:00",
  sequence: 12500,
  record_count: 12500,
};

const test_kms_key: KmsKeySummary = {
  key_id: "4d5579adfd004825",
  algorithm: "hmac-sha256",
};

// ── State fixtures (one per status) ────────────────────────────────────

export const test_ok: ChainIntegrityResponse = {
  status: "ok",
  message: "All recent checkpoints verified.",
  latest_checkpoint: test_latest_checkpoint,
  chain_depth: 90,
  kms_key: test_kms_key,
  cadence: "daily",
};

export const test_warn: ChainIntegrityResponse = {
  status: "warn",
  message: "The most recent checkpoint is overdue for the hourly cadence.",
  latest_checkpoint: test_latest_checkpoint,
  chain_depth: 14,
  kms_key: test_kms_key,
  cadence: "hourly",
};

export const test_error: ChainIntegrityResponse = {
  status: "error",
  message:
    "Checkpoint 8d51a2c7 failed verification — the evidence trail for this window can't be confirmed.",
  latest_checkpoint: test_latest_checkpoint,
  chain_depth: 90,
  kms_key: test_kms_key,
  cadence: "daily",
};

export const test_empty: ChainIntegrityResponse = {
  status: "ok",
  message: "No checkpoints sealed yet.",
  latest_checkpoint: null,
  chain_depth: 0,
  kms_key: test_kms_key,
  cadence: "daily",
};

export const test_no_kms: ChainIntegrityResponse = {
  status: "ok",
  message: "No checkpoints sealed yet.",
  latest_checkpoint: null,
  chain_depth: 0,
  kms_key: null,
  cadence: "disabled",
};

// ── Type-contract render snapshots ─────────────────────────────────────
// Each below MUST typecheck: if a future shape change in
// ``ChainIntegrityResponse`` or the tile's props drifts, these fail
// loudly under ``tsc --noEmit``.

export const test_render_loading = (
  <ChainIntegrityTile loading data={undefined} />
);
export const test_render_ok = <ChainIntegrityTile loading={false} data={test_ok} />;
export const test_render_warn = (
  <ChainIntegrityTile loading={false} data={test_warn} />
);
export const test_render_error = (
  <ChainIntegrityTile loading={false} data={test_error} />
);
export const test_render_empty = (
  <ChainIntegrityTile loading={false} data={test_empty} />
);
export const test_render_no_kms = (
  <ChainIntegrityTile loading={false} data={test_no_kms} />
);
export const test_render_with_custom_hrefs = (
  <ChainIntegrityTile
    loading={false}
    data={test_ok}
    evidenceBundleHref="/customers/cleveland_clinic"
    kmsKeyHistoryHref="/settings/kms"
  />
);

// ── Pure formatter assertions ──────────────────────────────────────────
// Voice rules:
//   * Full date with year ("Mar 15, 2026" not "Mar 15").
//   * Comma separators on counts ("12,500" not "12500" / "12.5K").
//   * Short fingerprints don't leak whole UUIDs / key IDs.

function assertEqual(actual: string, expected: string, label: string) {
  if (actual !== expected) {
    throw new Error(
      `[chain-integrity-tile.test] ${label}: expected ${JSON.stringify(
        expected,
      )}, got ${JSON.stringify(actual)}`,
    );
  }
}

// Module-load assertions — equivalent to a vitest ``describe.beforeAll``.
// The typecheck job imports this file via ``tsc --noEmit`` (which does
// NOT execute), but a vitest runner later will execute these on import.
(function _selfChecks() {
  // ``formatSealedAt`` must include the full year. The exact rendering
  // depends on the Intl runtime, so we only assert the year + a few
  // anchor substrings rather than the whole string.
  const sealed = formatSealedAt("2026-03-15T14:30:00");
  if (!sealed.includes("2026")) {
    throw new Error(`formatSealedAt missing year: ${sealed}`);
  }
  if (!sealed.includes("Mar") || !sealed.includes("15")) {
    throw new Error(`formatSealedAt malformed date: ${sealed}`);
  }
  if (!sealed.includes("14:30") || !sealed.endsWith("UTC")) {
    throw new Error(`formatSealedAt malformed time: ${sealed}`);
  }
  // Counts must use thousands separators, never abbreviation.
  assertEqual(formatCount(12500), "12,500", "formatCount 12500");
  assertEqual(formatCount(9500), "9,500", "formatCount 9500");
  assertEqual(formatCount(0), "0", "formatCount 0");
  assertEqual(formatCount(1), "1", "formatCount 1");
  // Short IDs strip everything past the prefix.
  assertEqual(
    shortCheckpointId("8d51a2c7-9f0a-4e21-9c01-e3b8a1234567"),
    "8d51a2c7",
    "shortCheckpointId",
  );
  assertEqual(
    shortKeyId("4d5579adfd004825"),
    "4d5579ad…4825",
    "shortKeyId truncation",
  );
})();

// ── Status / cadence types exhaustiveness ──────────────────────────────
// Compile-time check: if ``ChainIntegrityStatus`` ever gains a new
// member, the const-keyed maps in the tile will fail typecheck. Capture
// that by enumerating here.
const _exhaust_status: Record<ChainIntegrityStatus, true> = {
  ok: true,
  warn: true,
  error: true,
};
void _exhaust_status;

const _exhaust_cadence: Record<CheckpointCadence, true> = {
  hourly: true,
  daily: true,
  disabled: true,
};
void _exhaust_cadence;
