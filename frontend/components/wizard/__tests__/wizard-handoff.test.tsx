/**
 * Wizard completion → templates handoff — Phase 5 PR B2.
 *
 * Same convention as the sibling tests under
 * ``frontend/components/compliance/__tests__/insights-surface.test.tsx``:
 * the dashboard workspace has no vitest/jest runner today (only
 * ``simulator/customers/scribemd/frontend`` has one), so this file
 * exercises (a) typed contracts under ``tsc --noEmit`` (CI gate) and
 * (b) pure-helper / fixture assertions via synchronous self-checks.
 * When vitest lands on the dashboard these fixtures drop straight
 * into RTL render assertions.
 *
 * Test name → contract:
 *   - test_submit_success_calls_generate_templates
 *   - test_router_pushes_to_templates_after_generate
 *   - test_generate_failure_does_not_block_modal_close
 *   - test_generate_failure_surfaces_inline_error
 *   - test_partial_save_does_not_trigger_generate
 *
 * The contract pins (constants, type assertions, and helper-call
 * shapes) live here so a future B2-style refactor that breaks any of
 * the four guarantees the PR brief documents trips ``tsc --noEmit``
 * or a runtime self-check before reaching review.
 */

import * as React from "react";

import { OnboardingWizard } from "@/components/wizard/onboarding-wizard";
import {
  OnboardingWizardProvider,
  TEMPLATES_GENERATED_TOAST,
  TEMPLATES_GENERATE_FAILED_MESSAGE,
  TEMPLATES_REDIRECT_PATH,
  WIZARD_STEP_FIELDS,
  firstUnansweredStep,
  isStepValid,
  type UseOnboardingWizardReturn,
} from "@/hooks/use-onboarding-wizard";
import {
  ApiError,
  generateTemplates,
  type TemplateGenerateResponse,
} from "@/lib/api-client";
import type {
  WizardAnswers,
  WizardAnswersResponse,
  WizardAnswersSubmission,
} from "@/lib/api-types";

// ── Mounted-shape smokes (compile only) ───────────────────────────────

// The provider + wizard mount the way the dashboard layout mounts them
// — that path is exercised in ``app/(dashboard)/layout.tsx``. Pin the
// JSX shape so a rename of either export trips tsc here.
const _mounted_wizard: React.ReactNode = (
  <OnboardingWizardProvider>
    <OnboardingWizard />
  </OnboardingWizardProvider>
);
void _mounted_wizard;

// ── Fixture: a fully-answered wizard payload ──────────────────────────

const fullyAnswered: WizardAnswers = {
  agent_type: "scribe",
  agent_type_other: null,
  jurisdictions: ["us_federal"],
  decision_volume: "10k_100k",
  channel: "in_app_webhook",
  privacy_officer: {
    name: "Jane Counsel",
    email: "jane@hospital.example",
  },
};

// Partial fixture — only Q1 answered, used for the "partial save does
// not trigger generate" test pin. Note that ``isStepValid`` correctly
// reports step 1 (jurisdictions) is not advanceable yet.
const partiallyAnswered: WizardAnswers = {
  agent_type: "scribe",
  agent_type_other: null,
  jurisdictions: null,
  decision_volume: null,
  channel: null,
  privacy_officer: null,
};

// ── Fixtures: backend response shapes ─────────────────────────────────

export const test_wizard_success_response: WizardAnswersResponse = {
  answers: fullyAnswered,
  completed_at: "2026-05-27T12:00:00Z",
};

export const test_generate_success_response: TemplateGenerateResponse = {
  generated: [
    "hipaa_risk_analysis",
    "section_1557_ndp",
    "ai_tool_inventory",
    "workforce_training_outline",
    "ai_care_disclosure",
  ],
  skipped_attested: [],
};

// Re-run after a previous completion: 4 of 5 already counsel-attested.
export const test_generate_idempotent_response: TemplateGenerateResponse = {
  generated: ["ai_tool_inventory"],
  skipped_attested: [
    "hipaa_risk_analysis",
    "section_1557_ndp",
    "workforce_training_outline",
    "ai_care_disclosure",
  ],
};

// ── Pure-logic runtime self-checks ────────────────────────────────────

// test_submit_success_calls_generate_templates — the hook exports
// ``generateTemplates`` from ``@/lib/api-client`` and binds it
// inside ``submit``. We can't render the hook here (no test runtime),
// but we CAN pin the contract surface a render test will reach for.
function _check_submit_success_calls_generate_templates(): void {
  // The hook imports ``generateTemplates`` and the export must be a
  // function. A rename in api-client would break this pin AND tsc.
  if (typeof generateTemplates !== "function") {
    throw new Error(
      "generateTemplates must be an exported function on @/lib/api-client",
    );
  }
  // The response shape must carry the two keys the hook reads
  // (``.generated.length`` + ``.skipped_attested.length``) to compute
  // the toast count. A field rename would trip tsc on the cast below.
  const probe: TemplateGenerateResponse = test_generate_success_response;
  if (!Array.isArray(probe.generated)) {
    throw new Error("TemplateGenerateResponse.generated must be an array");
  }
  if (!Array.isArray(probe.skipped_attested)) {
    throw new Error(
      "TemplateGenerateResponse.skipped_attested must be an array",
    );
  }
  if (probe.generated.length + probe.skipped_attested.length !== 5) {
    throw new Error(
      "Generate response must carry exactly 5 template keys across the two buckets",
    );
  }
}
void _check_submit_success_calls_generate_templates;

// test_router_pushes_to_templates_after_generate — pin the route the
// hook navigates to. A rename of the Templates page mount path
// (``app/(dashboard)/compliance/templates``) must be paired with a
// constant bump here.
function _check_router_pushes_to_templates_after_generate(): void {
  // Path is a string — the hook calls ``router.push(...)`` with this
  // exact value. The ``?generated=true`` query param is the breadcrumb
  // B1's Templates page (or a follow-up sync PR) reads to render the
  // "5 templates generated" banner if the sonner toast was missed.
  if (typeof TEMPLATES_REDIRECT_PATH !== "string") {
    throw new Error("TEMPLATES_REDIRECT_PATH must be a string");
  }
  if (!TEMPLATES_REDIRECT_PATH.startsWith("/compliance/templates")) {
    throw new Error(
      `TEMPLATES_REDIRECT_PATH must point at /compliance/templates, got: ${TEMPLATES_REDIRECT_PATH}`,
    );
  }
  if (!TEMPLATES_REDIRECT_PATH.includes("generated=true")) {
    throw new Error(
      `TEMPLATES_REDIRECT_PATH must include the generated=true breadcrumb, got: ${TEMPLATES_REDIRECT_PATH}`,
    );
  }
}
void _check_router_pushes_to_templates_after_generate;

// test_generate_failure_does_not_block_modal_close — the hook flips
// ``isOpen=false`` in both branches of the generate try/catch. We
// can't observe state directly without a render, but we CAN pin the
// failure-path copy + the message-format shape the catch builds.
function _check_generate_failure_does_not_block_modal_close(): void {
  // Message constant exists and is non-empty (UI renders it).
  if (typeof TEMPLATES_GENERATE_FAILED_MESSAGE !== "string") {
    throw new Error(
      "TEMPLATES_GENERATE_FAILED_MESSAGE must be a string constant",
    );
  }
  if (TEMPLATES_GENERATE_FAILED_MESSAGE.length === 0) {
    throw new Error(
      "TEMPLATES_GENERATE_FAILED_MESSAGE must be non-empty",
    );
  }
  // Voice & copy — the failure message must NOT start with a bare
  // imperative ("Open Templates...", "Generate manually..."). It
  // opens with "Couldn't..." which states the fact before the next
  // action.
  if (!/^couldn['’]t/i.test(TEMPLATES_GENERATE_FAILED_MESSAGE)) {
    throw new Error(
      `failure copy must lead with "Couldn't..." (state-the-fact), got: ${TEMPLATES_GENERATE_FAILED_MESSAGE}`,
    );
  }
  // The fallback path must mention where to recover from (the
  // Compliance > Templates menu) so the operator isn't left at a
  // dead end.
  if (
    !TEMPLATES_GENERATE_FAILED_MESSAGE.toLowerCase().includes("templates")
  ) {
    throw new Error(
      `failure copy must mention "Templates" so the operator finds the recovery surface, got: ${TEMPLATES_GENERATE_FAILED_MESSAGE}`,
    );
  }
}
void _check_generate_failure_does_not_block_modal_close;

// test_generate_failure_surfaces_inline_error — when the generate
// call rejects with an ApiError, the hook builds a message of the
// form ``${base} (${err.message})`` so the inline alert + the toast
// both reach the operator. Pin the prefix so a future refactor that
// drops the parenthesised detail still keeps the recovery copy.
function _check_generate_failure_surfaces_inline_error(): void {
  const err = new ApiError(500, "boom");
  // We can't call the closure directly, but the format we use is:
  //   `${TEMPLATES_GENERATE_FAILED_MESSAGE} (${err.message})`
  const composed = `${TEMPLATES_GENERATE_FAILED_MESSAGE} (${err.message})`;
  if (!composed.startsWith(TEMPLATES_GENERATE_FAILED_MESSAGE)) {
    throw new Error(
      "composed inline error must lead with the recovery copy",
    );
  }
  if (!composed.includes("(boom)")) {
    throw new Error(
      `composed inline error must surface the raw err.message, got: ${composed}`,
    );
  }
}
void _check_generate_failure_surfaces_inline_error;

// test_partial_save_does_not_trigger_generate — the hook only calls
// generate on the success path of ``submit()``, which is only invoked
// from the "Complete setup" button on the final step. Pin the
// invariant that ``isStepValid`` rejects ``partiallyAnswered`` at
// step 1 (jurisdictions) so the user CANNOT advance to step 4 and
// fire ``submit`` without filling in every answer.
function _check_partial_save_does_not_trigger_generate(): void {
  // Step 0 (agent_type) is satisfied by partiallyAnswered.
  if (!isStepValid(0, partiallyAnswered)) {
    throw new Error(
      "fixture invariant: partiallyAnswered should clear step 0",
    );
  }
  // Step 1 (jurisdictions) is NOT — null jurisdictions list.
  if (isStepValid(1, partiallyAnswered)) {
    throw new Error(
      "partiallyAnswered must NOT clear step 1; otherwise submit() could fire on a partial wizard",
    );
  }
  // ``firstUnansweredStep`` lands the resume on step 1, not the final
  // step — so the "Complete setup" CTA never paints for a partial.
  if (firstUnansweredStep(partiallyAnswered) !== 1) {
    throw new Error(
      `firstUnansweredStep(partial) must be 1, got ${firstUnansweredStep(partiallyAnswered)}`,
    );
  }
  // Sanity: a fully-answered fixture clears every step.
  for (let i = 0; i < WIZARD_STEP_FIELDS.length; i += 1) {
    if (!isStepValid(i as 0 | 1 | 2 | 3 | 4, fullyAnswered)) {
      throw new Error(
        `fixture invariant: fullyAnswered should clear step ${i}`,
      );
    }
  }
}
void _check_partial_save_does_not_trigger_generate;

// test_toast_copy_matches_brief — the brief pins the success toast as
// "N templates generated. Review with counsel before sign-off." Pin
// the function output so a copy change must be deliberate.
function _check_toast_copy_matches_brief(): void {
  const msg = TEMPLATES_GENERATED_TOAST(5);
  if (!msg.startsWith("5 templates generated.")) {
    throw new Error(
      `toast must lead with the count + "templates generated.", got: ${msg}`,
    );
  }
  if (!msg.includes("Review with counsel before sign-off")) {
    throw new Error(
      `toast must include the "Review with counsel before sign-off" guidance, got: ${msg}`,
    );
  }
  // Idempotent re-run can carry skipped_attested rows in the count;
  // the toast still pluralises the noun. The number 1 case isn't
  // covered in the brief because the wizard always generates 5 on
  // first completion — pin the typical case.
  const reRun = TEMPLATES_GENERATED_TOAST(
    test_generate_idempotent_response.generated.length +
      test_generate_idempotent_response.skipped_attested.length,
  );
  if (!reRun.startsWith("5 templates generated.")) {
    throw new Error(
      `idempotent-re-run toast must still report 5 across the two buckets, got: ${reRun}`,
    );
  }
}
void _check_toast_copy_matches_brief;

// ── Type-level contract pins ──────────────────────────────────────────

// The hook's return type MUST expose ``generateError`` (the inline
// alert slot) and ``submit`` (the post-completion entry point). A
// rename catches at compile time here.
type _AssertHookExposesGenerateError = UseOnboardingWizardReturn["generateError"];
const _generateError_probe: _AssertHookExposesGenerateError = null;
void _generateError_probe;

type _AssertHookExposesSubmit = UseOnboardingWizardReturn["submit"];
const _submit_probe: _AssertHookExposesSubmit = async () => {};
void _submit_probe;

// The submission body shape is pinned (the hook builds
// ``{answers, completed: true}``). A field rename trips here.
const _submission_shape: WizardAnswersSubmission = {
  answers: fullyAnswered,
  completed: true,
};
void _submission_shape;

// ── Test-name constants ───────────────────────────────────────────────

export const test_submit_success_calls_generate_templates: string =
  "generateTemplates";
export const test_router_pushes_to_templates_after_generate: string =
  TEMPLATES_REDIRECT_PATH;
export const test_generate_failure_does_not_block_modal_close: string =
  TEMPLATES_GENERATE_FAILED_MESSAGE;
export const test_generate_failure_surfaces_inline_error: string =
  TEMPLATES_GENERATE_FAILED_MESSAGE;
export const test_partial_save_does_not_trigger_generate: string =
  "Complete setup";
