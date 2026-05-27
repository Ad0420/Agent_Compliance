"use client";

/**
 * OnboardingWizard — 2-question redesign (Phase 5 polish).
 *
 * Modal sequence rendering the 2-question onboarding flow. Restyled
 * to match the rest of the dashboard's Dialog primitives (see
 * ``components/customers/audit-pdf-modal.tsx`` for the reference
 * pattern). Each step is its own DialogContent — single component,
 * conditional body. The dot indicator at the top is `WizardProgress`.
 *
 * Two questions:
 *   1. Jurisdictions     — multi-select; US Federal always required
 *   2. Privacy Officer   — name + email (PII; not persisted in localStorage)
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
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { WizardProgress } from "@/components/ui/wizard-progress";
import { Loading } from "@/components/ui/loading";
import { useOnboardingWizard, type WizardStep } from "@/hooks/use-onboarding-wizard";
import {
  JURISDICTION_CHOICES,
  QUESTION_PROMPTS,
  QUESTION_SUBPROMPTS,
  TOTAL_STEPS,
} from "@/components/wizard/questions";
import { cn } from "@/lib/utils";

export function OnboardingWizard() {
  const wizard = useOnboardingWizard();

  return (
    <Dialog
      open={wizard.isOpen}
      onOpenChange={(open) => {
        if (!open) wizard.close();
      }}
    >
      {/*
        Per-modal Vera-token override matching audit-pdf-modal.tsx —
        the shadcn DialogContent primitive's default ``bg-background``
        resolves to the dark shadcn token because Radix portals mount
        the content to ``document.body`` (outside the ``.dashboard``
        scope that reassigns ``--background`` to ``--paper``).
      */}
      <DialogContent
        className="max-w-lg bg-[color:var(--paper)] border-[color:var(--ink-4)] text-[color:var(--ink)]"
        aria-labelledby="onboarding-wizard-title"
        aria-describedby="onboarding-wizard-prompt"
        data-testid="onboarding-wizard"
      >
        <WizardHeader step={wizard.currentStep} />
        <div className="space-y-5">
          <WizardBody />
          {wizard.submitError ? (
            <p
              role="alert"
              className="text-[13px] text-[color:var(--brick)]"
            >
              {wizard.submitError}
            </p>
          ) : null}
          {wizard.generateError ? (
            <p
              role="alert"
              className="text-[13px] text-[color:var(--brick)]"
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
    <DialogHeader>
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
        {step === 0 ? QUESTION_PROMPTS.jurisdictions : QUESTION_PROMPTS.privacy_officer}
      </DialogTitle>
      <DialogDescription className="text-[13px] text-[color:var(--ink-2)]">
        {step === 0
          ? QUESTION_SUBPROMPTS.jurisdictions
          : QUESTION_SUBPROMPTS.privacy_officer}
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
    <div id="onboarding-wizard-prompt">
      {step === 0 && <StepJurisdictions />}
      {step === 1 && <StepPrivacyOfficer />}
    </div>
  );
}

// ── Step 1 — Jurisdictions ─────────────────────────────────────────

function StepJurisdictions() {
  const wizard = useOnboardingWizard();
  const selected = wizard.answers.jurisdictions ?? [];
  const otherSelected = selected.includes("other");
  const otherEntries = wizard.answers.jurisdictions_other ?? [];

  // The Textarea is bound to a single string the user types as
  // newline-separated entries; we split + filter on every keystroke
  // so the hook state is always the parsed list. Max 10 lines,
  // max 64 chars each.
  const otherText = otherEntries.join("\n");

  const handleOtherChange = React.useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const raw = e.target.value;
      const lines = raw
        .split("\n")
        .map((l) => l.slice(0, 64))
        .slice(0, 10);
      // Preserve empty lines while typing — we filter when submitting.
      // But for state purposes, drop pure-empty trailing lines so the
      // hook state matches what'll actually persist.
      const cleaned = lines.map((l) => l.trim()).filter((l) => l.length > 0);
      wizard.setJurisdictionsOther(cleaned);
    },
    [wizard],
  );

  return (
    <div className="space-y-3">
      <fieldset
        className="space-y-2"
        role="group"
        aria-label={QUESTION_PROMPTS.jurisdictions}
      >
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
      </fieldset>
      {otherSelected ? (
        <div className="rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-3">
          <Textarea
            label="Describe each — one per line"
            rows={3}
            maxLength={10 * 65}
            placeholder="e.g. Florida&#10;Brazil&#10;Ontario"
            value={otherText}
            onChange={handleOtherChange}
            data-testid="wizard-jurisdictions-other"
          />
          <p className="mt-1.5 text-[12px] text-[color:var(--ink-3)]">
            Up to 10 entries, 64 characters each. Each becomes a
            placeholder section in your AI Care Disclosure.
          </p>
        </div>
      ) : null}
    </div>
  );
}

// ── Step 2 — Privacy Officer ───────────────────────────────────────

function StepPrivacyOfficer() {
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
          data-testid="wizard-po-name"
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
          data-testid="wizard-po-email"
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
  const showBack = wizard.currentStep > 0;
  return (
    <DialogFooter>
      {/*
        Back button — hidden entirely on step 1 of 2 (no
        non-functional grayed-out button). Visible + enabled on step 2.
        Styling matches the Cancel button in audit-pdf-modal.tsx.
      */}
      {showBack ? (
        <button
          type="button"
          onClick={wizard.back}
          disabled={wizard.isSubmitting}
          className={cn(
            "inline-flex h-9 items-center justify-center rounded-[10px]",
            "border border-[color:var(--ink-4)] px-4 text-[14px] font-medium",
            "text-[color:var(--ink-2)] transition-colors",
            "hover:bg-[color:var(--paper-2)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
            "focus-visible:outline-[color:var(--ink)]",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          data-testid="wizard-back"
        >
          Back
        </button>
      ) : null}
      <button
        type="button"
        onClick={() => {
          if (isLast) {
            void wizard.submit();
          } else {
            wizard.next();
          }
        }}
        disabled={!wizard.canAdvance || wizard.isSubmitting}
        className={cn(
          "inline-flex h-9 items-center justify-center gap-2 rounded-[10px]",
          "border border-[color:var(--ink)] bg-[color:var(--ink)] px-4",
          "text-[14px] font-medium text-[color:var(--paper)]",
          "transition-colors hover:bg-[color:var(--ink-2)]",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-[color:var(--ink)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
        data-testid="wizard-primary"
      >
        {isLast
          ? wizard.isSubmitting
            ? "Saving…"
            : "Complete setup"
          : "Next"}
      </button>
    </DialogFooter>
  );
}
