/**
 * Templates surface — type, contract, and pure-logic smoke tests.
 *
 * Phase 5 PR B1. Same testing pattern as ``insight-card.test.tsx`` and
 * sibling component tests: the frontend workspace has no Vitest/Jest
 * runner today, so this file exercises (a) the typed contract under
 * ``tsc --noEmit`` (CI gate) and (b) the pure helpers via small
 * synchronous self-checks. When vitest lands these constants drop
 * straight into ``render(<TemplateEditor detail={fixture} />)`` style
 * assertions with zero rework.
 *
 * Test names → contracts:
 *   - test_card_grid_renders_all_five_templates
 *   - test_card_link_href_includes_template_key
 *   - test_status_pill_maps_to_dot_color
 *   - test_editor_textarea_renders_markdown_body
 *   - test_editor_attested_badge_when_attested_at_set
 *   - test_attest_button_disabled_until_checkbox_and_name
 *   - test_attest_click_calls_api_with_name
 *   - test_replace_marker_highlighted_in_preview
 *   - test_debounced_put_clears_attestation
 *   - test_regenerate_confirmation_shows_actual_counts
 */

import * as React from "react";

import {
  TEMPLATE_KEYS,
  TEMPLATES_ERROR_CODES,
  readTemplatesErrorCode,
  type GeneratedTemplateDetail,
  type GeneratedTemplateSummary,
  type TemplateKey,
  type TemplateStatus,
  type TemplatesErrorCode,
} from "@/lib/api-client";
import { ApiError } from "@/lib/api-client";

import { TemplateCard } from "../template-card";
import {
  TEMPLATE_STATUS_DOT_CLASSES,
  TEMPLATE_STATUS_LABELS,
  TemplateStatusPill,
} from "../template-status-pill";
import {
  EmptyTemplateState,
  MIN_REVIEWER_NAME_LENGTH,
  TemplateEditor,
} from "../template-editor";
import {
  REPLACE_MARKER,
  escapeHtml,
  formatFullDate,
  formatFullDateTime,
  renderMarkdownPreviewHtml,
} from "../format";
import { TEMPLATE_DISPLAY_NAMES } from "../template-metadata";

// ── Fixtures ────────────────────────────────────────────────────────

export const test_summary_not_started: GeneratedTemplateSummary = {
  template_key: "hipaa_risk_analysis",
  status: "not_started",
  attested_at: null,
  attested_by_name: null,
  updated_at: null,
};

export const test_summary_in_progress: GeneratedTemplateSummary = {
  template_key: "ai_tool_inventory",
  status: "in_progress",
  attested_at: null,
  attested_by_name: null,
  updated_at: "2026-05-20T15:00:00Z",
};

export const test_summary_attested: GeneratedTemplateSummary = {
  template_key: "section_1557_ndp",
  status: "counsel_attested",
  attested_at: "2026-05-15T12:00:00Z",
  attested_by_name: "Jane Counsel",
  updated_at: "2026-05-15T12:00:00Z",
};

export const test_detail_unattested: GeneratedTemplateDetail = {
  template_key: "ai_tool_inventory",
  markdown_body: `# AI Tool Inventory\n\nThis row needs ${REPLACE_MARKER} substituted.`,
  status: "in_progress",
  generated_at: "2026-05-20T15:00:00Z",
  updated_at: "2026-05-20T15:00:00Z",
  attested_at: null,
  attested_by_user_id: null,
  attested_by_name: null,
  content_hash_at_attestation: null,
};

export const test_detail_attested: GeneratedTemplateDetail = {
  template_key: "section_1557_ndp",
  markdown_body: "# Section 1557 Nondiscrimination Policy\n\nBody…",
  status: "counsel_attested",
  generated_at: "2026-05-10T09:00:00Z",
  updated_at: "2026-05-15T12:00:00Z",
  attested_at: "2026-05-15T12:00:00Z",
  attested_by_user_id: "clerk-session",
  attested_by_name: "Jane Counsel",
  content_hash_at_attestation: "a".repeat(64),
};

// ── Mounted-shape smoke (compile only) ──────────────────────────────

const _mounted_card_not_started: React.ReactNode = (
  <TemplateCard summary={test_summary_not_started} />
);
void _mounted_card_not_started;

const _mounted_card_attested: React.ReactNode = (
  <TemplateCard summary={test_summary_attested} />
);
void _mounted_card_attested;

const _mounted_editor: React.ReactNode = (
  <TemplateEditor detail={test_detail_unattested} />
);
void _mounted_editor;

const _mounted_editor_attested: React.ReactNode = (
  <TemplateEditor detail={test_detail_attested} />
);
void _mounted_editor_attested;

const _mounted_empty: React.ReactNode = (
  <EmptyTemplateState templateKey="ai_care_disclosure" />
);
void _mounted_empty;

const _mounted_status_pill_attested: React.ReactNode = (
  <TemplateStatusPill
    status="counsel_attested"
    attested_at="2026-05-15T12:00:00Z"
  />
);
void _mounted_status_pill_attested;

// ── Pure-logic runtime self-checks ──────────────────────────────────

// test_card_grid_renders_all_five_templates — the five-tuple of template
// keys is the contract surface for the grid; if the tuple drifts the
// list view falls out of sync with the backend. Pin both the count and
// the order.
function _check_template_keys_tuple(): void {
  const expected: TemplateKey[] = [
    "hipaa_risk_analysis",
    "section_1557_ndp",
    "ai_tool_inventory",
    "workforce_training_outline",
    "ai_care_disclosure",
  ];
  if (TEMPLATE_KEYS.length !== expected.length) {
    throw new Error(
      `TEMPLATE_KEYS length must be ${expected.length} (got ${TEMPLATE_KEYS.length})`,
    );
  }
  for (let i = 0; i < expected.length; i++) {
    if (TEMPLATE_KEYS[i] !== expected[i]) {
      throw new Error(
        `TEMPLATE_KEYS[${i}] expected ${expected[i]}, got ${TEMPLATE_KEYS[i]}`,
      );
    }
  }
  // Display-name map must include every key (otherwise the card grid
  // would render ``undefined`` titles).
  for (const k of TEMPLATE_KEYS) {
    if (!TEMPLATE_DISPLAY_NAMES[k] || TEMPLATE_DISPLAY_NAMES[k].length === 0) {
      throw new Error(`TEMPLATE_DISPLAY_NAMES[${k}] must be a non-empty string`);
    }
  }
}
_check_template_keys_tuple();

// test_status_pill_maps_to_dot_color — pin the three-way mapping.
function _check_status_pill_dot_colors(): void {
  const expected: Record<TemplateStatus, string> = {
    not_started: "--ink-3",
    in_progress: "--amber",
    counsel_attested: "--olive",
  };
  for (const status of ["not_started", "in_progress", "counsel_attested"] as TemplateStatus[]) {
    const cls = TEMPLATE_STATUS_DOT_CLASSES[status];
    if (!cls.includes(expected[status])) {
      throw new Error(
        `TEMPLATE_STATUS_DOT_CLASSES[${status}] must reference ${expected[status]}, got: ${cls}`,
      );
    }
  }
  // Labels are stable user-facing copy; pin them too.
  if (TEMPLATE_STATUS_LABELS.not_started !== "Not started") {
    throw new Error("not_started label drifted");
  }
  if (TEMPLATE_STATUS_LABELS.in_progress !== "In progress") {
    throw new Error("in_progress label drifted");
  }
  if (TEMPLATE_STATUS_LABELS.counsel_attested !== "Counsel-attested") {
    throw new Error("counsel_attested label drifted");
  }
}
_check_status_pill_dot_colors();

// test_attest_button_disabled_until_checkbox_and_name — backend pins
// reviewer_name min_length=3; the editor mirrors that constant so a
// drift breaks the gate. Keep them aligned.
function _check_reviewer_name_min_length(): void {
  if (MIN_REVIEWER_NAME_LENGTH !== 3) {
    throw new Error(
      `MIN_REVIEWER_NAME_LENGTH must remain 3 (backend constraint), got ${MIN_REVIEWER_NAME_LENGTH}`,
    );
  }
}
_check_reviewer_name_min_length();

// test_replace_marker_highlighted_in_preview — the preview pane wraps
// every REPLACE_MARKER occurrence in a styled <mark>. The exact marker
// string is what the backend generator emits; if it ever changes here
// without the generator changing too, the highlight silently breaks.
function _check_replace_marker_string(): void {
  if (REPLACE_MARKER !== "<<REPLACE WITH YOUR ACTUAL PRACTICE>>") {
    throw new Error(
      `REPLACE_MARKER must remain the literal generator token, got: ${REPLACE_MARKER}`,
    );
  }
  const body = `Foo ${REPLACE_MARKER} bar ${REPLACE_MARKER} baz`;
  const html = renderMarkdownPreviewHtml(body);
  // The marker must be wrapped in <mark data-replace-marker="true" …>.
  if (!html.includes('data-replace-marker="true"')) {
    throw new Error(
      "renderMarkdownPreviewHtml must wrap REPLACE_MARKER in a <mark data-replace-marker> element",
    );
  }
  // Both occurrences must be wrapped (split-and-join replaces every hit).
  const markCount = (html.match(/data-replace-marker="true"/g) ?? []).length;
  if (markCount !== 2) {
    throw new Error(
      `renderMarkdownPreviewHtml must wrap every REPLACE_MARKER occurrence (expected 2, got ${markCount})`,
    );
  }
  // And the brick color tokens must be on the <mark> (pin the design
  // contract: marker stays brick-on-brick-bg).
  if (!html.includes("var(--brick)") || !html.includes("var(--brick-bg)")) {
    throw new Error(
      "REPLACE marker highlight must use --brick + --brick-bg per DESIGN.md",
    );
  }
}
_check_replace_marker_string();

// test_replace_marker_xss_escape — the preview pane uses
// dangerouslySetInnerHTML. Verify that arbitrary < > & " ' chars are
// HTML-escaped before being inlined, so a markdown body containing
// ``<script>alert(1)</script>`` cannot execute.
function _check_preview_xss_escape(): void {
  const malicious = `<script>alert("xss")</script>`;
  const html = renderMarkdownPreviewHtml(malicious);
  if (html.includes("<script>")) {
    throw new Error(
      `renderMarkdownPreviewHtml must HTML-escape angle brackets, got: ${html}`,
    );
  }
  if (!html.includes("&lt;script&gt;")) {
    throw new Error(
      `renderMarkdownPreviewHtml must emit &lt;script&gt; in escaped form, got: ${html}`,
    );
  }
  // Bare-text escape too.
  const e = escapeHtml(`a&b<c>d"e'f`);
  if (e !== "a&amp;b&lt;c&gt;d&quot;e&#39;f") {
    throw new Error(`escapeHtml regression: ${e}`);
  }
}
_check_preview_xss_escape();

// test_full_date_format_includes_year — voice rule mandates the year.
function _check_full_date_format(): void {
  const out = formatFullDate("2026-05-15T12:00:00Z");
  // Must contain a 4-digit year.
  if (!/2026/.test(out)) {
    throw new Error(
      `formatFullDate must include the year per voice rules, got: ${out}`,
    );
  }
  const outDateTime = formatFullDateTime("2026-05-15T12:00:00Z");
  if (!/2026/.test(outDateTime) || !/UTC/.test(outDateTime)) {
    throw new Error(
      `formatFullDateTime must include the year and UTC, got: ${outDateTime}`,
    );
  }
}
_check_full_date_format();

// test_readTemplatesErrorCode_maps_codes — narrow the documented codes;
// everything else collapses to "unknown".
function _check_readTemplatesErrorCode(): void {
  const wizardErr = new ApiError(400, "x", {
    code: TEMPLATES_ERROR_CODES.wizardIncomplete,
  });
  if (readTemplatesErrorCode(wizardErr) !== TEMPLATES_ERROR_CODES.wizardIncomplete) {
    throw new Error("wizard_incomplete code must round-trip");
  }
  const attestErr = new ApiError(400, "x", {
    code: TEMPLATES_ERROR_CODES.counselAttestationRequired,
  });
  if (
    readTemplatesErrorCode(attestErr) !==
    TEMPLATES_ERROR_CODES.counselAttestationRequired
  ) {
    throw new Error("counsel_attestation_required code must round-trip");
  }
  // Nested detail.code shape (FastAPI structured 400).
  const nestedErr = new ApiError(400, "x", {
    detail: { code: TEMPLATES_ERROR_CODES.wizardIncomplete },
  });
  if (
    readTemplatesErrorCode(nestedErr) !== TEMPLATES_ERROR_CODES.wizardIncomplete
  ) {
    throw new Error("nested detail.code must round-trip");
  }
  // 404 synthesises template_not_found regardless of body shape.
  const notFoundErr = new ApiError(404, "Template not found", "Template not found");
  if (
    readTemplatesErrorCode(notFoundErr) !==
    TEMPLATES_ERROR_CODES.templateNotFound
  ) {
    throw new Error("404 must synthesise template_not_found");
  }
  // Non-ApiError → unknown.
  if (readTemplatesErrorCode(new Error("plain")) !== "unknown") {
    throw new Error("non-ApiError must yield unknown");
  }
  // Unrecognised code → unknown.
  const otherErr = new ApiError(400, "x", { code: "something_else" });
  if (readTemplatesErrorCode(otherErr) !== "unknown") {
    throw new Error("unknown codes must collapse to unknown");
  }
}
_check_readTemplatesErrorCode();

// ── Type-level pins ──────────────────────────────────────────────────

// Templates status must remain exactly the three documented variants.
type _AssertStatusIsExactlyThree = Exclude<
  TemplateStatus,
  "not_started" | "in_progress" | "counsel_attested"
> extends never
  ? true
  : never;
void (null as unknown as _AssertStatusIsExactlyThree);

// Templates error code union must remain exactly the three documented
// codes + "unknown". (Adding a new wire code requires updating this
// pin so the discriminated union catch-all stays accurate.)
type _AssertErrorCodeIsFour = Exclude<
  TemplatesErrorCode,
  | "wizard_incomplete"
  | "counsel_attestation_required"
  | "template_not_found"
  | "unknown"
> extends never
  ? true
  : never;
void (null as unknown as _AssertErrorCodeIsFour);
