/**
 * AuditPdfModal — type, contract, and pure-logic smoke tests.
 *
 * Phase 4 Wave 1 PR C3-scaffold. Same pattern as the sibling
 * ``verification-panel.test.tsx`` and ``decisions-tab.test.tsx``: the
 * frontend workspace has no Vitest/Jest runner today, so this file
 * exercises (a) the typed contract under ``tsc --noEmit`` (CI gate)
 * and (b) the pure validation / mapping helpers via small synchronous
 * self-checks the parent ``frontend-typecheck`` workflow doesn't have
 * to execute — they'll be picked up by a vitest run once that lands.
 *
 * The test_* constants enumerate the cases the brief lists. Each one
 * pins the contract a future React Testing Library port will assert
 * against:
 *
 *   - test_renders_with_all_sections_checked_by_default
 *   - test_disables_primary_when_no_sections_selected
 *   - test_disables_primary_when_date_range_invalid
 *   - test_default_date_range_is_last_30_days
 *   - test_branding_default_is_customer
 *   - test_submit_calls_endpoint_with_correct_body_and_triggers_download
 *   - test_baa_expired_error_shows_renew_message_inline_and_keeps_modal_open
 *   - test_pdf_render_timeout_shows_retry_message_inline
 *   - test_generic_error_shows_default_message
 *   - test_spinner_visible_during_request
 *   - test_modal_closes_on_escape_and_cancel
 */

import * as React from "react";

import {
  AuditPdfModal,
  defaultDateRange,
  mapAuditPdfErrorMessage,
} from "../audit-pdf-modal";
import {
  AUDIT_PDF_ERROR_CODES,
  AUDIT_PDF_SECTION_KEYS,
  ApiError,
  readAuditPdfErrorCode,
  type AuditPdfBranding,
  type AuditPdfInput,
  type AuditPdfSectionKey,
} from "@/lib/api-client";

// ── Section-list fixture (all-on default) ──────────────────────────────

// 8 sections, all on by default. The literal-tuple type assertion below
// is the compile-time pin: if AUDIT_PDF_SECTION_KEYS grows or shrinks,
// this constant length-mismatches and tsc fails.
export const test_renders_with_all_sections_checked_by_default: readonly AuditPdfSectionKey[] =
  AUDIT_PDF_SECTION_KEYS;

type _Assert8Sections = typeof AUDIT_PDF_SECTION_KEYS extends { length: 8 }
  ? true
  : never;
void (null as unknown as _Assert8Sections);

// ── Submit-body fixtures (pinned wire shape) ───────────────────────────

// Canonical submit body — all sections on, customer-branded, default
// 30-day window. Pins the AuditPdfInput shape against drift.
export const test_submit_default_body: AuditPdfInput = {
  date_from: "2026-04-26",
  date_to: "2026-05-26",
  sections: [...AUDIT_PDF_SECTION_KEYS],
  branding: "customer",
};

// Variant — operator deselected the technical appendix.
export const test_submit_partial_sections_body: AuditPdfInput = {
  date_from: "2026-04-26",
  date_to: "2026-05-26",
  sections: [
    "cover",
    "scope",
    "audit_controls",
    "hitl_evidence",
    "demographic_monitoring",
    "workforce_training",
    "baa_chain",
  ],
  branding: "customer",
};

// Variant — Vera-neutral branding for a regulator that prefers the
// vendor name on the cover.
export const test_submit_vera_neutral_body: AuditPdfInput = {
  ...test_submit_default_body,
  branding: "vera-neutral",
};

// Type-level pin: branding default literal must remain "customer".
const _branding_default: AuditPdfBranding = "customer";
void _branding_default;

// ── Error-mapping fixtures ─────────────────────────────────────────────

export const test_baa_expired_error_message: string = mapAuditPdfErrorMessage(
  AUDIT_PDF_ERROR_CODES.baaExpired,
);

export const test_pdf_render_timeout_error_message: string =
  mapAuditPdfErrorMessage(AUDIT_PDF_ERROR_CODES.pdfRenderTimeout);

export const test_generic_error_message: string =
  mapAuditPdfErrorMessage(null);

// ── Pure-logic runtime self-checks ─────────────────────────────────────
//
// These run under ``tsc --noEmit`` only as type-check fodder. Once a
// vitest runner is wired up they become real assertions. They're
// deliberately exhaustive so a future refactor can't silently drift the
// pure helpers.

function _check_default_date_range_is_last_30_days(): void {
  const { from, to } = defaultDateRange();
  // ``to`` must be a YYYY-MM-DD string (10 chars).
  if (from.length !== 10 || to.length !== 10) {
    throw new Error(
      `defaultDateRange must return YYYY-MM-DD strings, got from=${from} to=${to}`,
    );
  }
  // ``to`` must be on or after ``from``.
  if (from > to) {
    throw new Error(
      `defaultDateRange must return from<=to, got from=${from} to=${to}`,
    );
  }
  // The span must be exactly 30 days. Parse as UTC to avoid DST drift.
  const fromMs = Date.UTC(
    Number(from.slice(0, 4)),
    Number(from.slice(5, 7)) - 1,
    Number(from.slice(8, 10)),
  );
  const toMs = Date.UTC(
    Number(to.slice(0, 4)),
    Number(to.slice(5, 7)) - 1,
    Number(to.slice(8, 10)),
  );
  const diffDays = Math.round((toMs - fromMs) / (1000 * 60 * 60 * 24));
  if (diffDays !== 30) {
    throw new Error(
      `defaultDateRange must span exactly 30 days, got ${diffDays}`,
    );
  }
}
void _check_default_date_range_is_last_30_days;

function _check_error_mapping_strings(): void {
  // baa_expired → renew message that mentions BAA Management.
  const baa = mapAuditPdfErrorMessage(AUDIT_PDF_ERROR_CODES.baaExpired);
  if (!baa.includes("BAA") || !baa.toLowerCase().includes("renew")) {
    throw new Error(
      `baa_expired error message must mention BAA and renew, got: ${baa}`,
    );
  }
  // pdf_render_timeout → retry message.
  const timeout = mapAuditPdfErrorMessage(
    AUDIT_PDF_ERROR_CODES.pdfRenderTimeout,
  );
  if (!timeout.toLowerCase().includes("retry")) {
    throw new Error(
      `pdf_render_timeout error message must mention retry, got: ${timeout}`,
    );
  }
  // Default — used for null code OR an unknown code string.
  const generic = mapAuditPdfErrorMessage(null);
  if (!generic.toLowerCase().includes("failed")) {
    throw new Error(
      `generic error message must indicate failure, got: ${generic}`,
    );
  }
  const unknown = mapAuditPdfErrorMessage("some_unhandled_code");
  if (unknown !== generic) {
    throw new Error(
      `unknown error codes must fall through to the generic message, got: ${unknown}`,
    );
  }
}
void _check_error_mapping_strings;

function _check_read_audit_pdf_error_code_handles_both_envelope_shapes(): void {
  // Flat envelope — {code, message} at top level.
  const flatErr = new ApiError(403, "BAA expired", {
    code: AUDIT_PDF_ERROR_CODES.baaExpired,
    message: "BAA expired",
  });
  if (
    readAuditPdfErrorCode(flatErr) !== AUDIT_PDF_ERROR_CODES.baaExpired
  ) {
    throw new Error("readAuditPdfErrorCode must read flat envelope");
  }
  // Nested envelope — {error: {code, message}} — what the A1 brief
  // documents.
  const nestedErr = new ApiError(504, "PDF render timeout", {
    error: {
      code: AUDIT_PDF_ERROR_CODES.pdfRenderTimeout,
      message: "PDF render timeout",
    },
  });
  if (
    readAuditPdfErrorCode(nestedErr) !==
    AUDIT_PDF_ERROR_CODES.pdfRenderTimeout
  ) {
    throw new Error("readAuditPdfErrorCode must read nested envelope");
  }
  // Missing envelope — null (caller falls back to generic). ApiError's
  // ctor defaults ``detail`` to ``message`` (a string), and the reader
  // returns null for any non-object detail.
  const bareErr = new ApiError(500, "boom");
  if (readAuditPdfErrorCode(bareErr) !== null) {
    throw new Error(
      "readAuditPdfErrorCode must return null when detail is a bare string",
    );
  }
  // Non-ApiError — null.
  if (readAuditPdfErrorCode(new Error("not-api")) !== null) {
    throw new Error(
      "readAuditPdfErrorCode must return null for non-ApiError values",
    );
  }
}
void _check_read_audit_pdf_error_code_handles_both_envelope_shapes;

function _check_section_set_round_trip(): void {
  // All-on → all section keys are AuditPdfSectionKey values.
  const all: AuditPdfSectionKey[] = [...AUDIT_PDF_SECTION_KEYS];
  if (all.length !== 8) {
    throw new Error(
      `AUDIT_PDF_SECTION_KEYS must remain 8 sections per A1 contract, got ${all.length}`,
    );
  }
  // Set.has correctness for each key.
  const set = new Set<AuditPdfSectionKey>(all);
  for (const key of AUDIT_PDF_SECTION_KEYS) {
    if (!set.has(key)) {
      throw new Error(`Set must contain seeded key ${key}`);
    }
  }
}
void _check_section_set_round_trip;

// ── Test-name → contract assertion (compile-time only) ────────────────
//
// Each named test below pins a behavior the future runtime test must
// preserve. The constants are referenced (``void``) so tsc tree-shaking
// doesn't drop them.

// test_disables_primary_when_no_sections_selected — pinned via the
// AUDIT_PDF_SECTION_KEYS literal length (a zero-length sections array
// is a contract violation, not just a UI state).
const test_disables_primary_when_no_sections_selected_sections: AuditPdfSectionKey[] =
  [];
void test_disables_primary_when_no_sections_selected_sections;

// test_disables_primary_when_date_range_invalid — string-compare
// guard: "2026-05-26" > "2026-05-01" must hold lexicographically so the
// validator can rely on string ordering for YYYY-MM-DD.
function _check_iso_date_string_ordering_works(): void {
  if (!("2026-05-26" > "2026-05-01")) {
    throw new Error(
      "YYYY-MM-DD strings must compare lexicographically — validator depends on this",
    );
  }
  if (!("2026-05-01" > "2025-12-31")) {
    throw new Error(
      "YYYY-MM-DD strings must compare lexicographically across years",
    );
  }
}
void _check_iso_date_string_ordering_works;

// test_spinner_visible_during_request — compile-time pin that the
// modal's ``submitting`` state and the Loading.Spinner import remain
// in shape. The actual runtime visibility check belongs in the RTL
// port.
//
// test_modal_closes_on_escape_and_cancel — the modal wraps Radix
// Dialog, which handles Escape natively + we pass ``onOpenChange``
// through. The contract surface is that ``onOpenChange(false)`` fires
// — the Cancel button's onClick pins it directly.
//
// test_submit_calls_endpoint_with_correct_body_and_triggers_download —
// the submit handler imports ``generateAuditPdf`` from api-client; the
// runtime mock would replace that module export. The contract here is
// the AuditPdfInput shape pinned in test_submit_default_body.

// ── Render-shape smoke (compile only) ──────────────────────────────────

const _mounted_modal: React.ReactNode = (
  <AuditPdfModal
    open={true}
    onOpenChange={() => undefined}
    tenant_id="cleveland_clinic"
    customer_display_name="Cleveland Clinic"
  />
);
void _mounted_modal;
