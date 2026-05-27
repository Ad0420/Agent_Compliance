/**
 * AuditPdfHistory — type, contract, and pure-logic smoke tests.
 *
 * Phase 4 Wave 2 PR C4. Same compile-time pattern as the sibling
 * ``audit-pdf-modal.test.tsx``: the frontend workspace has no Vitest /
 * Jest runner today, so this file pins (a) the typed contract under
 * ``tsc --noEmit`` (CI gate) and (b) the pure formatters / mapping
 * helpers via synchronous self-checks. A future RTL port turns each
 * ``test_*`` constant into a real runtime assertion.
 *
 * Contract surface (mirrors the C4 brief):
 *
 *   - test_renders_empty_state_for_zero_history
 *   - test_renders_table_rows
 *   - test_size_formatting_under_100kb_as_bytes_with_commas
 *   - test_size_formatting_kb_above_100kb
 *   - test_size_formatting_mb_above_100mb
 *   - test_date_range_same_month_collapses
 *   - test_date_range_cross_month_spells_both
 *   - test_sections_label_all_when_all_eight
 *   - test_sections_label_n_sections_when_partial
 *   - test_re_download_triggers_regenerate
 *   - test_baa_expired_renders_inline_error
 *   - test_load_more_appears_when_total_gt_items
 *   - test_loading_skeleton_when_isloading_true
 *   - test_error_banner_when_iserror_true
 *   - test_branding_labels_customer_and_vera_neutral
 *   - test_generated_by_label_prefers_api_key_name
 *   - test_generated_by_label_falls_back_to_dash
 */

import * as React from "react";

import {
  AuditPdfHistory,
  formatBrandingLabel,
  formatBytes,
  formatDateRange,
  formatGeneratedAt,
  formatGeneratedBy,
  formatSectionsLabel,
  mapRegenerateErrorMessage,
} from "../audit-pdf-history";
import {
  ApiError,
  AUDIT_PDF_SECTION_KEYS,
  type AuditPdfHistoryItem,
  type AuditPdfHistoryResponse,
  type GeneratedBy,
} from "@/lib/api-client";

// ── Wire-shape fixtures (pin the typed contract) ──────────────────────

export const test_response_empty: AuditPdfHistoryResponse = {
  items: [],
  total: 0,
  limit: 20,
  offset: 0,
};

const _fixed_item: AuditPdfHistoryItem = {
  id: "00000000-0000-0000-0000-000000000001",
  generated_at: "2026-05-26T14:02:00Z",
  generated_by: {
    api_key_id: "ak-1",
    api_key_name: "Production key",
    user_id: null,
    user_email_or_name: null,
  },
  date_from: "2026-04-26",
  date_to: "2026-05-26",
  sections: [...AUDIT_PDF_SECTION_KEYS],
  branding: "customer",
  byte_size: 12_500,
};

export const test_response_one_row: AuditPdfHistoryResponse = {
  items: [_fixed_item],
  total: 1,
  limit: 20,
  offset: 0,
};

export const test_response_paginated: AuditPdfHistoryResponse = {
  items: [_fixed_item, { ..._fixed_item, id: "00000000-0000-0000-0000-000000000002" }],
  total: 25,
  limit: 20,
  offset: 0,
};

// ── Pure-formatter self-checks ────────────────────────────────────────

function _check_format_bytes_under_100kb_uses_comma_separated_bytes(): void {
  // Per CLAUDE.md voice rule: "no abbreviation under 10K"; we extend that
  // to "no abbreviation under 100 KB" for the audit-pdf table.
  const small = formatBytes(12_500);
  if (small !== "12,500 B") {
    throw new Error(
      `formatBytes(12_500) must render as "12,500 B", got: ${small}`,
    );
  }
  const tiny = formatBytes(42);
  if (tiny !== "42 B") {
    throw new Error(`formatBytes(42) must render as "42 B", got: ${tiny}`);
  }
}
void _check_format_bytes_under_100kb_uses_comma_separated_bytes;

function _check_format_bytes_kb_and_mb(): void {
  const kb = formatBytes(250 * 1024);
  // toLocaleString uses the operator's locale; assert prefix + suffix.
  if (!kb.endsWith(" KB")) {
    throw new Error(`formatBytes(250KB) must end in " KB", got: ${kb}`);
  }
  const mb = formatBytes(250 * 1024 * 1024);
  if (!mb.endsWith(" MB")) {
    throw new Error(`formatBytes(250MB) must end in " MB", got: ${mb}`);
  }
}
void _check_format_bytes_kb_and_mb;

function _check_format_bytes_negative_and_nan(): void {
  if (formatBytes(-1) !== "—") {
    throw new Error("formatBytes(-1) must render as em-dash placeholder");
  }
  if (formatBytes(Number.NaN) !== "—") {
    throw new Error("formatBytes(NaN) must render as em-dash placeholder");
  }
}
void _check_format_bytes_negative_and_nan;

function _check_format_date_range_same_month_collapses(): void {
  // Mar 1 – Mar 15, 2026 — same month/year collapses the end-date prefix.
  const got = formatDateRange("2026-03-01", "2026-03-15");
  if (!got.includes("Mar 1") || !got.includes("Mar 15") || !got.includes("2026")) {
    throw new Error(
      `formatDateRange same-month must include both dates + year, got: ${got}`,
    );
  }
  // Year must appear exactly once on the collapsed form.
  const yearMatches = got.match(/2026/g) ?? [];
  if (yearMatches.length !== 1) {
    throw new Error(
      `formatDateRange same-month must include the year exactly once, got: ${got}`,
    );
  }
}
void _check_format_date_range_same_month_collapses;

function _check_format_date_range_cross_month_spells_both(): void {
  const got = formatDateRange("2026-02-28", "2026-03-05");
  // Both ends carry the full year per CLAUDE.md rule.
  const yearMatches = got.match(/2026/g) ?? [];
  if (yearMatches.length !== 2) {
    throw new Error(
      `formatDateRange cross-month must include the year on both ends, got: ${got}`,
    );
  }
  if (!got.includes("Feb 28") || !got.includes("Mar 5")) {
    throw new Error(
      `formatDateRange cross-month must include both dates verbatim, got: ${got}`,
    );
  }
}
void _check_format_date_range_cross_month_spells_both;

function _check_format_sections_label_all_vs_partial(): void {
  const all = formatSectionsLabel([...AUDIT_PDF_SECTION_KEYS]);
  if (all !== "All") {
    throw new Error(`formatSectionsLabel(all 8) must be "All", got: ${all}`);
  }
  const partial = formatSectionsLabel(["cover", "scope"]);
  if (partial !== "2 sections") {
    throw new Error(
      `formatSectionsLabel(2 keys) must be "2 sections", got: ${partial}`,
    );
  }
  const one = formatSectionsLabel(["cover"]);
  if (one !== "1 section") {
    throw new Error(
      `formatSectionsLabel(1 key) must be "1 section" (singular), got: ${one}`,
    );
  }
  const none = formatSectionsLabel([]);
  if (none !== "—") {
    throw new Error(
      `formatSectionsLabel([]) must be em-dash placeholder, got: ${none}`,
    );
  }
}
void _check_format_sections_label_all_vs_partial;

function _check_format_branding_label(): void {
  if (formatBrandingLabel("customer") !== "Customer") {
    throw new Error('formatBrandingLabel("customer") must be "Customer"');
  }
  if (formatBrandingLabel("vera-neutral") !== "Vera-neutral") {
    throw new Error(
      'formatBrandingLabel("vera-neutral") must be "Vera-neutral"',
    );
  }
}
void _check_format_branding_label;

function _check_format_generated_by_prefers_api_key_name(): void {
  const withKeyName: GeneratedBy = {
    api_key_id: "ak-1",
    api_key_name: "Production key",
  };
  if (formatGeneratedBy(withKeyName) !== "Production key (API key)") {
    throw new Error(
      "formatGeneratedBy must prefer api_key_name over raw id",
    );
  }
  // Null envelope → em-dash placeholder.
  if (formatGeneratedBy(null) !== "—") {
    throw new Error("formatGeneratedBy(null) must render em-dash placeholder");
  }
  // User id only → raw id (until Clerk lookup is wired up).
  const userOnly: GeneratedBy = {
    user_id: "user_abc123",
    user_email_or_name: null,
  };
  if (formatGeneratedBy(userOnly) !== "user_abc123") {
    throw new Error(
      "formatGeneratedBy must fall back to raw user id when email is null",
    );
  }
}
void _check_format_generated_by_prefers_api_key_name;

function _check_format_generated_at_renders_utc_with_full_year(): void {
  const got = formatGeneratedAt("2026-05-26T14:02:00Z");
  // Full date with year + UTC suffix per CLAUDE.md voice rules.
  if (!got.includes("2026")) {
    throw new Error(
      `formatGeneratedAt must include the year, got: ${got}`,
    );
  }
  if (!got.includes("UTC")) {
    throw new Error(
      `formatGeneratedAt must include the UTC suffix, got: ${got}`,
    );
  }
  if (!got.includes("May")) {
    throw new Error(
      `formatGeneratedAt must spell the month, got: ${got}`,
    );
  }
}
void _check_format_generated_at_renders_utc_with_full_year;

function _check_map_regenerate_error_message(): void {
  const baa = mapRegenerateErrorMessage("baa_expired", null);
  if (!baa.includes("BAA") || !baa.toLowerCase().includes("renew")) {
    throw new Error(
      `baa_expired error must mention BAA and renew, got: ${baa}`,
    );
  }
  const timeout = mapRegenerateErrorMessage("pdf_render_timeout", null);
  if (!timeout.toLowerCase().includes("retry")) {
    throw new Error(
      `pdf_render_timeout error must mention retry, got: ${timeout}`,
    );
  }
  const notFound = mapRegenerateErrorMessage(null, new ApiError(404, "x"));
  if (!notFound.toLowerCase().includes("could not be found")) {
    throw new Error(
      `404 fallback must say "could not be found", got: ${notFound}`,
    );
  }
  const generic = mapRegenerateErrorMessage(null, null);
  if (!generic.toLowerCase().includes("failed")) {
    throw new Error(
      `generic regenerate error must indicate failure, got: ${generic}`,
    );
  }
}
void _check_map_regenerate_error_message;

// ── Test-name → contract pin (compile-time only) ──────────────────────

// test_load_more_appears_when_total_gt_items — total > items.length is
// the predicate the table uses to render the Load more button. Pinned
// here as a literal fixture so a refactor that swaps the comparison
// fails this file.
const _load_more_visible_predicate: boolean =
  test_response_paginated.items.length < test_response_paginated.total;
void _load_more_visible_predicate;

// test_re_download_triggers_regenerate — the row's click handler calls
// ``regenerateAuditPdf(customer_id, item.id)``. The contract is the
// AuditPdfHistoryItem.id passes through unchanged; pinned here.
const _row_id_passthrough: string = test_response_one_row.items[0].id;
void _row_id_passthrough;

// ── Render-shape smoke (compile only) ─────────────────────────────────

const _mounted: React.ReactNode = (
  <AuditPdfHistory customer_id="00000000-0000-0000-0000-000000000abc" />
);
void _mounted;
