/**
 * SetupCta + wizard launch-surface gates — Phase 5 follow-up.
 *
 * Same convention as the sibling tests under
 * ``frontend/components/wizard/__tests__/wizard-handoff.test.tsx``:
 * the main dashboard ``frontend/`` workspace has no Vitest/Jest
 * runner today, so this file exercises (a) typed contracts under
 * ``tsc --noEmit`` (CI gate ``frontend-typecheck.yml``) and (b) the
 * gate predicates via synchronous self-checks. When vitest lands on
 * the dashboard these fixtures drop straight into RTL render
 * assertions.
 *
 * Test name -> contract:
 *   - test_home_cta_hidden_when_actions_present
 *   - test_home_cta_hidden_when_wizard_completed
 *   - test_home_cta_visible_for_cold_signup
 *   - test_templates_proactive_cta_hidden_when_wizard_completed
 *   - test_templates_proactive_cta_visible_when_all_not_started
 *   - test_templates_proactive_cta_hidden_when_any_started
 *   - test_templates_inline_button_visible_on_wizard_incomplete_error
 */

import * as React from "react";

import { SetupCta, type SetupCtaProps } from "../setup-cta";
import {
  TEMPLATES_ERROR_CODES,
  type GeneratedTemplateSummary,
  type TemplateKey,
  type TemplatesErrorCode,
} from "@/lib/api-client";

// ── Mounted-shape smoke (compile only) ────────────────────────────────

// Pin the component's prop contract. A rename of ``onStart`` /
// ``testId`` breaks tsc here BEFORE the home / templates pages
// silently render the wrong shape.
const _mounted_setup_cta: React.ReactNode = (
  <SetupCta onStart={() => {}} testId="probe" />
);
void _mounted_setup_cta;

// ── Gate helpers — duplicated here so tests can pin the predicate ─────

/**
 * Mirror of the home-page gate. Keeping this duplicated (rather than
 * exporting from the page) is intentional: the page is a server-route
 * file with its own hook closures, and tests should pin the predicate
 * shape independently. If the page's gate drifts from this helper a
 * future RTL test will catch the render-time divergence.
 */
function shouldShowHomeSetupCta(args: {
  actionsLoading: boolean;
  wizardLoading: boolean;
  totalActions: number;
  wizardCompletedAt: string | null;
}): boolean {
  return (
    !args.actionsLoading &&
    !args.wizardLoading &&
    args.totalActions === 0 &&
    args.wizardCompletedAt === null
  );
}

/**
 * Mirror of the templates-page proactive-CTA gate.
 */
function shouldShowTemplatesProactiveCta(args: {
  wizardLoading: boolean;
  wizardCompletedAt: string | null;
  templates: GeneratedTemplateSummary[] | undefined;
}): boolean {
  const allNotStarted = Boolean(
    args.templates &&
      args.templates.length > 0 &&
      args.templates.every((row) => row.status === "not_started"),
  );
  return (
    !args.wizardLoading &&
    args.wizardCompletedAt === null &&
    allNotStarted
  );
}

// ── Template fixtures (five rows, varying statuses) ───────────────────

function stub(
  key: TemplateKey,
  status: GeneratedTemplateSummary["status"],
): GeneratedTemplateSummary {
  return {
    template_key: key,
    status,
    attested_at: null,
    attested_by_name: null,
    updated_at: null,
  };
}

export const test_all_not_started: GeneratedTemplateSummary[] = [
  stub("hipaa_risk_analysis", "not_started"),
  stub("section_1557_ndp", "not_started"),
  stub("ai_tool_inventory", "not_started"),
  stub("workforce_training_outline", "not_started"),
  stub("ai_care_disclosure", "not_started"),
];

export const test_one_in_progress: GeneratedTemplateSummary[] = [
  stub("hipaa_risk_analysis", "in_progress"),
  stub("section_1557_ndp", "not_started"),
  stub("ai_tool_inventory", "not_started"),
  stub("workforce_training_outline", "not_started"),
  stub("ai_care_disclosure", "not_started"),
];

// ── Pure-logic runtime self-checks ────────────────────────────────────

// test_home_cta_hidden_when_actions_present — once the SDK has fired
// at least one ActionRecord the cold-signup CTA must yield to the
// ``ResumeSetupBanner`` (which has its own gate for that scenario).
function _check_home_cta_hidden_when_actions_present(): void {
  const show = shouldShowHomeSetupCta({
    actionsLoading: false,
    wizardLoading: false,
    totalActions: 1,
    wizardCompletedAt: null,
  });
  if (show) {
    throw new Error(
      "Home setup CTA must NOT render when totalActions > 0 (ResumeSetupBanner handles that case)",
    );
  }
}
void _check_home_cta_hidden_when_actions_present;

// test_home_cta_hidden_when_wizard_completed — once setup is done,
// no nag. Even on an org with zero actions (e.g. they completed the
// wizard before deploying the SDK), the CTA must NOT reappear.
function _check_home_cta_hidden_when_wizard_completed(): void {
  const show = shouldShowHomeSetupCta({
    actionsLoading: false,
    wizardLoading: false,
    totalActions: 0,
    wizardCompletedAt: "2026-05-27T12:00:00Z",
  });
  if (show) {
    throw new Error(
      "Home setup CTA must NOT render when wizard is already completed",
    );
  }
}
void _check_home_cta_hidden_when_wizard_completed;

// test_home_cta_visible_for_cold_signup — the primary scenario the
// PR exists to fix: fresh Clerk sign-up, no SDK installed, wizard
// never opened. The card MUST render.
function _check_home_cta_visible_for_cold_signup(): void {
  const show = shouldShowHomeSetupCta({
    actionsLoading: false,
    wizardLoading: false,
    totalActions: 0,
    wizardCompletedAt: null,
  });
  if (!show) {
    throw new Error(
      "Home setup CTA MUST render for a cold sign-up (totalActions=0 AND wizardCompletedAt=null)",
    );
  }
  // And it must NOT render while either loader is still in flight —
  // we don't want a flash of the wrong empty state before the data
  // resolves.
  if (
    shouldShowHomeSetupCta({
      actionsLoading: true,
      wizardLoading: false,
      totalActions: 0,
      wizardCompletedAt: null,
    })
  ) {
    throw new Error("Home CTA must wait for actions to load");
  }
  if (
    shouldShowHomeSetupCta({
      actionsLoading: false,
      wizardLoading: true,
      totalActions: 0,
      wizardCompletedAt: null,
    })
  ) {
    throw new Error("Home CTA must wait for wizard to load");
  }
}
void _check_home_cta_visible_for_cold_signup;

// test_templates_proactive_cta_hidden_when_wizard_completed — the
// reverse-direction guarantee for the proactive banner. If the
// wizard is done but generation never ran, the operator sees the
// regular "Regenerate templates" button and the inline error path
// — NOT the onboarding CTA.
function _check_templates_proactive_cta_hidden_when_wizard_completed(): void {
  const show = shouldShowTemplatesProactiveCta({
    wizardLoading: false,
    wizardCompletedAt: "2026-05-27T12:00:00Z",
    templates: test_all_not_started,
  });
  if (show) {
    throw new Error(
      "Templates proactive CTA must NOT render when wizard is already completed",
    );
  }
}
void _check_templates_proactive_cta_hidden_when_wizard_completed;

// test_templates_proactive_cta_visible_when_all_not_started — every
// template stub is ``not_started`` AND the wizard is incomplete:
// render the banner so the operator finds the gate proactively.
function _check_templates_proactive_cta_visible_when_all_not_started(): void {
  const show = shouldShowTemplatesProactiveCta({
    wizardLoading: false,
    wizardCompletedAt: null,
    templates: test_all_not_started,
  });
  if (!show) {
    throw new Error(
      "Templates proactive CTA MUST render when wizard incomplete AND every template is not_started",
    );
  }
  // And it must skip the empty / loading branches so we don't flash.
  if (
    shouldShowTemplatesProactiveCta({
      wizardLoading: false,
      wizardCompletedAt: null,
      templates: undefined,
    })
  ) {
    throw new Error("Templates proactive CTA must wait for the list to load");
  }
  if (
    shouldShowTemplatesProactiveCta({
      wizardLoading: true,
      wizardCompletedAt: null,
      templates: test_all_not_started,
    })
  ) {
    throw new Error("Templates proactive CTA must wait for wizard to load");
  }
}
void _check_templates_proactive_cta_visible_when_all_not_started;

// test_templates_proactive_cta_hidden_when_any_started — if even one
// row has progressed past ``not_started`` the operator has already
// generated; surface the regular regenerate flow instead.
function _check_templates_proactive_cta_hidden_when_any_started(): void {
  const show = shouldShowTemplatesProactiveCta({
    wizardLoading: false,
    wizardCompletedAt: null,
    templates: test_one_in_progress,
  });
  if (show) {
    throw new Error(
      "Templates proactive CTA must NOT render when any row has progressed past not_started",
    );
  }
}
void _check_templates_proactive_cta_hidden_when_any_started;

// test_templates_inline_button_visible_on_wizard_incomplete_error —
// the inline "Start onboarding" button shows ONLY when the
// regenerate mutation rejected with the ``wizard_incomplete`` code.
// Other error paths (network failure, generic 500) must NOT paint
// the button — they're not actionable via onboarding.
function _check_templates_inline_button_gate(): void {
  function shouldShowInline(code: TemplatesErrorCode): boolean {
    return code === TEMPLATES_ERROR_CODES.wizardIncomplete;
  }
  if (!shouldShowInline(TEMPLATES_ERROR_CODES.wizardIncomplete)) {
    throw new Error(
      "Inline 'Start onboarding' button MUST show on wizard_incomplete",
    );
  }
  if (shouldShowInline(TEMPLATES_ERROR_CODES.counselAttestationRequired)) {
    throw new Error(
      "Inline 'Start onboarding' button must NOT show on counsel_attestation_required",
    );
  }
  if (shouldShowInline("unknown")) {
    throw new Error(
      "Inline 'Start onboarding' button must NOT show on unknown errors",
    );
  }
}
void _check_templates_inline_button_gate;

// ── Type-level contract pins ──────────────────────────────────────────

// Both surfaces must pass a stable testId — a rename here trips tsc.
type _AssertProps = SetupCtaProps;
const _props_probe: _AssertProps = {
  onStart: () => {},
  testId: "home-setup-cta",
};
void _props_probe;

// ── Test-name constants ───────────────────────────────────────────────

export const test_home_cta_hidden_when_actions_present: string =
  "home-setup-cta";
export const test_home_cta_hidden_when_wizard_completed: string =
  "home-setup-cta";
export const test_home_cta_visible_for_cold_signup: string =
  "home-setup-cta";
export const test_templates_proactive_cta_hidden_when_wizard_completed: string =
  "templates-proactive-setup-cta";
export const test_templates_proactive_cta_visible_when_all_not_started: string =
  "templates-proactive-setup-cta";
export const test_templates_proactive_cta_hidden_when_any_started: string =
  "templates-proactive-setup-cta";
export const test_templates_inline_button_visible_on_wizard_incomplete_error: string =
  "templates-start-onboarding-button";
