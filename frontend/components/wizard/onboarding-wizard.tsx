"use client";

/**
 * OnboardingWizard — Phase 1 PR 14 (Stream F item F5).
 *
 * Pattern C modal sequence (see `dashboard-design.md`) rendering the
 * 5-question onboarding flow defined in `policy-engine-mvp.md` Appendix A.
 * Each step is its own DialogContent — single component, conditional
 * body. The dot indicator at the top is `WizardProgress` from the PR #193
 * primitive set.
 *
 * Anatomy:
 *   ┌────────────────────────────────────────────────┐
 *   │  ⬤ ⬤ ●  ◯ ◯    Question 3 of 5                │  ← header
 *   │                                                │
 *   │  How many AI decisions per month, roughly?     │  ← prompt
 *   │  ◯ < 10,000        Starter                     │  ← input
 *   │  ⬤ 10K – 100K      Growth                      │
 *   │  ◯ 100K – 1M       Scale                       │
 *   │  ◯ > 1M            Enterprise                  │
 *   │                                                │
 *   │                       [Back]  [Next]            │  ← footer
 *   └────────────────────────────────────────────────┘
 *
 * State lives in `useOnboardingWizard()`. The component is dumb plumbing:
 * it reads the hook and renders.
 */

import * as React from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioOption } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { WizardProgress } from "@/components/ui/wizard-progress";
import { Loading } from "@/components/ui/loading";
import { useOnboardingWizard, type WizardStep } from "@/hooks/use-onboarding-wizard";
import {
  AGENT_TYPE_CHOICES,
  DECISION_VOLUME_CHOICES,
  JURISDICTION_CHOICES,
  QUESTION_PROMPTS,
  REVIEW_CHANNEL_CHOICES,
  TOTAL_STEPS,
} from "@/components/wizard/questions";
import { cn } from "@/lib/utils";

export function OnboardingWizard() {
  const wizard = useOnboardingWizard();

  // Radix Dialog drives focus trap + escape-to-close + restore-focus
  // automatically. Pass onOpenChange so the X / overlay click also routes
  // through our close() (which clears submitError).
  return (
    <Dialog
      open={wizard.isOpen}
      onOpenChange={(open) => {
        if (!open) wizard.close();
      }}
    >
      <DialogContent
        className={cn(
          // Pattern C: 600px wide centred modal on warm paper.
          "sm:max-w-[600px] bg-[color:var(--paper)] border-[color:var(--ink-4)]",
          "gap-0 p-0",
        )}
        aria-labelledby="onboarding-wizard-title"
        aria-describedby="onboarding-wizard-prompt"
      >
        <WizardHeader step={wizard.currentStep} />
        <div className="px-6 pt-2 pb-6">
          <WizardBody />
          {wizard.submitError ? (
            <p
              role="alert"
              className="mt-4 text-[13px] text-[color:var(--brick)]"
            >
              {wizard.submitError}
            </p>
          ) : null}
          {/* Phase 5 PR B2 — surface a failure of the post-completion
              POST /v1/templates/generate handoff inline. The wizard
              itself saved cleanly; the modal still closes shortly
              after this paints (the submit flow flips ``isOpen=false``
              on the generate error path too). A sonner toast backs
              this up for the case where the operator has already
              clicked through to the dashboard before noticing. */}
          {wizard.generateError ? (
            <p
              role="alert"
              className="mt-4 text-[13px] text-[color:var(--brick)]"
            >
              {wizard.generateError}
            </p>
          ) : null}
        </div>
        <WizardFooter />
      </DialogContent>
    </Dialog>
  );
}

// ── Header ──────────────────────────────────────────────────────────

function WizardHeader({ step }: { step: WizardStep }) {
  return (
    <DialogHeader className="border-b border-[color:var(--ink-4)] px-6 pt-6 pb-4">
      <div className="flex items-center justify-between gap-4">
        <WizardProgress totalSteps={TOTAL_STEPS} currentStep={step} />
        <span className="text-[12px] text-[color:var(--ink-2)] tabular-nums">
          Question {step + 1} of {TOTAL_STEPS}
        </span>
      </div>
      <DialogTitle
        id="onboarding-wizard-title"
        className="mt-3 font-display text-[20px] font-normal leading-tight text-[color:var(--ink)]"
      >
        Set up your Vera deployment
      </DialogTitle>
      {/* Per dashboard-design.md voice rules: no "Welcome", no marketing
          chrome. The DialogDescription doubles as a subtle screen-reader
          context line; sighted users see it as the small below-title note. */}
      <DialogDescription className="text-[13px] text-[color:var(--ink-2)]">
        Five questions. We use these to scope your evidence trail and
        generate the right templates.
      </DialogDescription>
    </DialogHeader>
  );
}

// ── Body — switches on currentStep ─────────────────────────────────

function WizardBody() {
  const wizard = useOnboardingWizard();
  const step = wizard.currentStep;

  if (wizard.isLoading) {
    return (
      <div className="flex justify-center py-8 text-[color:var(--ink-3)]">
        <Loading.Spinner size={20} label="Loading wizard" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p
        id="onboarding-wizard-prompt"
        className="text-[14px] font-medium text-[color:var(--ink)] leading-snug"
      >
        {step === 0 && QUESTION_PROMPTS.agent_type}
        {step === 1 && QUESTION_PROMPTS.jurisdictions}
        {step === 2 && QUESTION_PROMPTS.decision_volume}
        {step === 3 && QUESTION_PROMPTS.channel}
        {step === 4 && QUESTION_PROMPTS.privacy_officer}
      </p>
      {step === 0 && <Step1AgentType />}
      {step === 1 && <Step2Jurisdictions />}
      {step === 2 && <Step3DecisionVolume />}
      {step === 3 && <Step4Channel />}
      {step === 4 && <Step5PrivacyOfficer />}
    </div>
  );
}

// ── Step 1 — Agent type ────────────────────────────────────────────

function Step1AgentType() {
  const wizard = useOnboardingWizard();
  return (
    <div className="space-y-3">
      <RadioGroup
        name="wizard-agent-type"
        value={wizard.answers.agent_type ?? undefined}
        onChange={(v) => wizard.setAgentType(v as never)}
        ariaLabel={QUESTION_PROMPTS.agent_type}
      >
        {AGENT_TYPE_CHOICES.map((c) => (
          <RadioOption
            key={c.value}
            value={c.value}
            label={c.label}
            description={c.description}
          />
        ))}
      </RadioGroup>
      {wizard.answers.agent_type === "other" ? (
        <Textarea
          label="Describe your AI agent"
          rows={2}
          maxLength={200}
          placeholder="e.g. AI clinical-trial recruiter"
          value={wizard.answers.agent_type_other ?? ""}
          onChange={(e) => wizard.setAgentTypeOther(e.target.value)}
        />
      ) : null}
    </div>
  );
}

// ── Step 2 — Jurisdictions ─────────────────────────────────────────

function Step2Jurisdictions() {
  const wizard = useOnboardingWizard();
  const selected = wizard.answers.jurisdictions ?? [];
  return (
    <div className="space-y-2" role="group" aria-label={QUESTION_PROMPTS.jurisdictions}>
      {JURISDICTION_CHOICES.map((c) => {
        const checked = c.required || selected.includes(c.value);
        return (
          <Checkbox
            key={c.value}
            checked={checked}
            disabled={c.required}
            onChange={() => wizard.toggleJurisdiction(c.value)}
            label={c.label}
            description={c.description}
          />
        );
      })}
    </div>
  );
}

// ── Step 3 — Decision volume ───────────────────────────────────────

function Step3DecisionVolume() {
  const wizard = useOnboardingWizard();
  return (
    <RadioGroup
      name="wizard-decision-volume"
      value={wizard.answers.decision_volume ?? undefined}
      onChange={(v) => wizard.setDecisionVolume(v as never)}
      ariaLabel={QUESTION_PROMPTS.decision_volume}
    >
      {DECISION_VOLUME_CHOICES.map((c) => (
        <RadioOption
          key={c.value}
          value={c.value}
          label={c.label}
          description={c.description}
        />
      ))}
    </RadioGroup>
  );
}

// ── Step 4 — Channel ───────────────────────────────────────────────

function Step4Channel() {
  const wizard = useOnboardingWizard();
  return (
    <RadioGroup
      name="wizard-channel"
      value={wizard.answers.channel ?? undefined}
      onChange={(v) => wizard.setChannel(v as never)}
      ariaLabel={QUESTION_PROMPTS.channel}
    >
      {REVIEW_CHANNEL_CHOICES.map((c) => (
        <RadioOption
          key={c.value}
          value={c.value}
          label={c.label}
          description={c.description}
        />
      ))}
    </RadioGroup>
  );
}

// ── Step 5 — Privacy Officer ───────────────────────────────────────

function Step5PrivacyOfficer() {
  const wizard = useOnboardingWizard();
  const po = wizard.answers.privacy_officer ?? { name: "", email: "" };
  return (
    <div className="space-y-3">
      <div>
        <label
          htmlFor="wizard-po-name"
          className="mb-1.5 block text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]"
        >
          Name
        </label>
        <Input
          id="wizard-po-name"
          value={po.name}
          onChange={(e) =>
            wizard.setPrivacyOfficer({ ...po, name: e.target.value })
          }
          autoComplete="name"
          maxLength={200}
        />
      </div>
      <div>
        <label
          htmlFor="wizard-po-email"
          className="mb-1.5 block text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]"
        >
          Email
        </label>
        <Input
          id="wizard-po-email"
          type="email"
          value={po.email}
          onChange={(e) =>
            wizard.setPrivacyOfficer({ ...po, email: e.target.value })
          }
          autoComplete="email"
          maxLength={320}
        />
        {/* Privacy disclosure: PII does not touch the browser's local
            store. The reassurance is small but real for security-minded
            buyers (counsel, compliance leads). */}
        <p className="mt-1.5 text-[12px] text-[color:var(--ink-3)]">
          We store this on your organization only. It is never written to
          your browser&apos;s local storage.
        </p>
      </div>
    </div>
  );
}

// ── Footer — Back / Next or Complete setup ─────────────────────────

function WizardFooter() {
  const wizard = useOnboardingWizard();
  const isLast = wizard.currentStep === TOTAL_STEPS - 1;
  return (
    <DialogFooter
      className={cn(
        "border-t border-[color:var(--ink-4)] px-6 py-4 sm:justify-between",
      )}
    >
      <Button
        variant="ghost"
        onClick={wizard.back}
        disabled={wizard.currentStep === 0 || wizard.isSubmitting}
      >
        Back
      </Button>
      {isLast ? (
        <Button
          onClick={() => {
            void wizard.submit();
          }}
          disabled={!wizard.canAdvance || wizard.isSubmitting}
        >
          {wizard.isSubmitting ? "Saving…" : "Complete setup"}
        </Button>
      ) : (
        <Button onClick={wizard.next} disabled={!wizard.canAdvance}>
          Next
        </Button>
      )}
    </DialogFooter>
  );
}
