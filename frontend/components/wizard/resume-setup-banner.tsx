"use client";

/**
 * ResumeSetupBanner — Phase 1 PR 14 (Stream F item F5).
 *
 * Renders above the Home page's "Needs your attention" section when:
 *   - the SDK has captured ≥1 action for this org (proves real wiring), AND
 *   - the 5-question wizard has been started but not completed.
 *
 * Hidden when:
 *   - the org has zero actions captured (would be a misleading "incomplete"
 *     prompt for a brand-new org that hasn't even installed the SDK yet),
 *   - the wizard is already completed.
 *
 * Per Codex D4 the copy is:
 *   "SDK connected · {N} decisions captured · setup incomplete"
 * with a "Continue setup" right-arrow CTA that opens the wizard at the
 * next-unanswered step.
 */

import * as React from "react";

import { useActions } from "@/hooks/use-actions";
import { useOnboardingWizard, firstUnansweredStep } from "@/hooks/use-onboarding-wizard";
import type { WizardAnswers } from "@/lib/api-types";
import { cn } from "@/lib/utils";

/** Same predicate the hook uses for "first unanswered" — count answered fields. */
function answeredCount(answers: WizardAnswers): number {
  let n = 0;
  if (answers.jurisdictions && answers.jurisdictions.length > 0) n += 1;
  if (answers.privacy_officer) n += 1;
  return n;
}

const TOTAL_QUESTIONS = 2;

export function ResumeSetupBanner() {
  const wizard = useOnboardingWizard();
  // We only need to know "is there ≥1 action?" — fetch the smallest
  // possible page so the banner doesn't drag a 100-row list along.
  const { data: actionsData, isLoading: actionsLoading } = useActions({ limit: 1 });

  const totalActions = actionsData?.total ?? actionsData?.records?.length ?? 0;
  const hasAnyActivity = totalActions > 0;
  const answered = answeredCount(wizard.answers);
  const isComplete = wizard.completedAt !== null;
  const hasStartedWizard = answered > 0;
  const isAllAnswered = answered === TOTAL_QUESTIONS;

  // Show only when: SDK has captured ≥1 action AND wizard is incomplete.
  // Per spec we suppress on brand-new orgs (zero actions) so the user's
  // first 60 seconds doesn't open with a chore.
  const shouldShow =
    !actionsLoading &&
    !wizard.isLoading &&
    !isComplete &&
    !isAllAnswered &&
    hasAnyActivity &&
    // Banner is for resume — if the operator hasn't touched the wizard
    // at all yet, leave them alone until they pick it up explicitly
    // from the customer detail "Complete setup" CTA (PR 13) or another
    // surface. This avoids the banner becoming a nag on day one.
    hasStartedWizard;

  if (!shouldShow) return null;

  const nextStep = firstUnansweredStep(wizard.answers);

  return (
    <section
      aria-label="Setup status"
      className={cn(
        "rounded-[10px] border border-[color:var(--ink-4)]",
        "bg-[color:var(--paper-2)]/40 px-4 py-3",
        "flex items-center justify-between gap-4",
      )}
      data-testid="resume-setup-banner"
    >
      <p className="text-[13px] text-[color:var(--ink)]">
        <span className="font-medium">SDK connected</span>
        <span className="mx-2 text-[color:var(--ink-3)]">·</span>
        <span className="tabular-nums">
          {totalActions.toLocaleString()} decision{totalActions === 1 ? "" : "s"} captured
        </span>
        <span className="mx-2 text-[color:var(--ink-3)]">·</span>
        <span className="text-[color:var(--ink-2)]">setup incomplete</span>
      </p>
      <button
        type="button"
        onClick={() => {
          // The hook's open() recomputes firstUnansweredStep, so we
          // don't pass nextStep explicitly — keeps a single source of
          // truth for "where the resume lands".
          wizard.open();
        }}
        // Keep the visible CTA copy short; the aria-label explains
        // exactly which step we'd land on for screen-reader users.
        aria-label={`Continue setup — opens wizard at question ${nextStep + 1} of ${TOTAL_QUESTIONS}`}
        className={cn(
          "shrink-0 text-[13px] font-medium text-[color:var(--ink)]",
          "hover:underline focus-visible:outline focus-visible:outline-2",
          "focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
        )}
      >
        Continue setup →
      </button>
    </section>
  );
}
