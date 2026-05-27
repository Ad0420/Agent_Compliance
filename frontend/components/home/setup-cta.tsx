"use client";

/**
 * SetupCta — Phase 5 follow-up: cold-sign-up launch surface for the
 * 5-question org onboarding wizard.
 *
 * Two render surfaces consume this component:
 *
 *   1. /home — the primary launch point. Renders ONLY when there is
 *      zero activity recorded (``actions == 0``) AND the wizard has
 *      never been completed. The existing ``ResumeSetupBanner`` covers
 *      the "SDK firing but wizard incomplete" case; this card covers
 *      the "fresh sign-up with nothing yet" case those gates skip.
 *
 *   2. /compliance/templates — secondary launch point. Renders when
 *      every template is in the ``not_started`` state AND the wizard
 *      is incomplete, so the operator doesn't have to click
 *      "Regenerate" first to discover the gate.
 *
 * Both surfaces gate the render upstream; this component is a dumb
 * presenter. It exposes its own props so the upstream gate decides
 * "show or not" and this component renders the same shell either way.
 *
 * Voice & copy notes:
 *   - "Set up your organization" — heading, not an imperative CTA.
 *   - "Start setup" is a one-word noun-action button label, not a
 *     bare imperative ("Click here", "Get started!").
 *   - "5 quick questions" is a count, not a duration claim.
 *   - "Customer" terminology is honoured downstream by the templates
 *     themselves; this card only references organisation-wide setup.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SetupCtaProps {
  /**
   * Fires when the operator clicks the primary CTA. The home / templates
   * surfaces wire this to ``useOnboardingWizard().open()`` so the modal
   * opens at the first unanswered step.
   */
  onStart: () => void;
  /**
   * Stable testid for the rendered button. Required because two
   * surfaces mount this component and the tests pin each one
   * separately (``home-setup-cta`` vs ``templates-proactive-setup-cta``).
   */
  testId: string;
  /** Optional className for the outer container. */
  className?: string;
}

export function SetupCta({ onStart, testId, className }: SetupCtaProps) {
  return (
    <section
      aria-label="Organization setup"
      className={cn(
        "rounded-[10px] border border-[color:var(--ink-4)]",
        "bg-[color:var(--paper-2)] px-6 py-6",
        "flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
      data-testid={`${testId}-card`}
    >
      <div className="space-y-2">
        <h2 className="font-display text-2xl font-normal leading-tight text-[color:var(--ink)]">
          Set up your organization
        </h2>
        <p className="text-[14px] text-[color:var(--ink-2)] leading-normal">
          Answer 5 quick questions to generate your HIPAA Risk Analysis,
          Section 1557 NDP, and three other compliance templates.
        </p>
      </div>
      <button
        type="button"
        onClick={onStart}
        data-testid={testId}
        className={cn(
          "shrink-0 inline-flex h-9 items-center justify-center",
          "rounded-[10px] border border-[color:var(--ink)] bg-[color:var(--ink)]",
          "px-4 text-[14px] font-medium text-[color:var(--paper)]",
          "transition-colors hover:bg-[color:var(--ink-2)]",
          "focus-visible:outline focus-visible:outline-2",
          "focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
        )}
      >
        Start setup →
      </button>
    </section>
  );
}
