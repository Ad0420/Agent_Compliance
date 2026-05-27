"use client";

/**
 * useOnboardingWizard — 2-question redesign (Phase 5 polish).
 *
 * Drives the onboarding modal. Shape mirrors backend
 * `app/schemas/wizard.py`.
 *
 * The original 5-question wizard was trimmed to 2 questions
 * (jurisdictions + privacy_officer) after user testing surfaced that
 * the other three answers never drove product behaviour.
 *
 * State machine:
 *
 *   closed ──open()──▶ open at first-unanswered step (server state +
 *                       localStorage draft both consulted)
 *   open  ──next()──▶ open at next step (after client-side validation)
 *   open  ──back()──▶ open at previous step (no validation)
 *   open  ──submit()─▶ POST {completed:true}; on success, close + invalidate
 *                       organization / wizard queries.
 *   open  ──close()──▶ closed (draft persists; non-PII answers stay in
 *                       localStorage so the operator can resume)
 *
 * Where state lives:
 *
 *   - Server (Organization.wizard_answers / wizard_completed_at) — the
 *     source of truth across devices, browsers, and incognito tabs.
 *   - localStorage `vera.wizard.draft.<orgId>` — the in-flight non-PII
 *     answers (jurisdictions + jurisdictions_other). Lets the operator
 *     reload mid-wizard on the same device without losing progress.
 *   - React state — every answer, including the Privacy Officer (PII).
 *
 * PRIVACY: the Privacy Officer (`privacy_officer`) is PII (name +
 * email). It is held in React state ONLY and is NEVER serialised to
 * localStorage. The draft on disk omits the key entirely so a stolen
 * device backup can't leak the Privacy Officer's contact info. The
 * hook re-prompts for the Privacy Officer on every resume.
 *
 * RE-OPEN AFTER COMPLETION: `open()` does not block when
 * `completedAt !== null` — an admin can re-open the wizard from any
 * surface to edit answers. Submitting again is a partial-update on
 * the JSON column; the server does NOT bump `wizard_completed_at` on
 * re-submit, so the first-completion timestamp is preserved for audit.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  generateTemplates,
  getWizardAnswers,
  submitWizardAnswers,
} from "@/lib/api-client";
import type {
  WizardAnswers,
  WizardAnswersResponse,
  WizardAnswersSubmission,
  WizardJurisdiction,
  WizardPrivacyOfficer,
} from "@/lib/api-types";
import { TOTAL_STEPS } from "@/components/wizard/questions";

/**
 * Post-completion handoff — Phase 5 PR B2.
 *
 * On successful wizard submission with ``completed=true`` we kick off
 * ``POST /v1/templates/generate`` (idempotent on the backend), then
 * route the operator to the Templates page so they can review +
 * counsel-attest each generated template.
 */
export const TEMPLATES_GENERATED_TOAST = (count: number): string =>
  `${count} templates generated. Review with counsel before sign-off.`;

export const TEMPLATES_GENERATE_FAILED_MESSAGE =
  "Couldn't generate templates automatically. Open Templates from the Compliance menu to generate manually.";

export const TEMPLATES_REDIRECT_PATH =
  "/compliance/templates?generated=true";

// Step index → wizard field. Keep in sync with the modal step order.
export type WizardStep = 0 | 1;

export const WIZARD_STEP_FIELDS: ReadonlyArray<keyof WizardAnswers> = [
  "jurisdictions",
  "privacy_officer",
];

// localStorage key. Scoped by org so two orgs in the same browser
// (Clerk supports org switching) don't cross-contaminate drafts.
function draftStorageKey(orgId: string | null | undefined): string | null {
  if (!orgId) return null;
  return `vera.wizard.draft.${orgId}`;
}

/**
 * Subset of WizardAnswers we're willing to persist to localStorage.
 * EXCLUDES `privacy_officer` by construction so PII never touches disk.
 */
interface DraftAnswers {
  jurisdictions: WizardJurisdiction[] | null;
  jurisdictions_other: string[] | null;
}

function emptyAnswers(): WizardAnswers {
  return {
    jurisdictions: null,
    jurisdictions_other: null,
    privacy_officer: null,
  };
}

function readDraft(orgId: string | null | undefined): DraftAnswers | null {
  const key = draftStorageKey(orgId);
  if (!key) return null;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DraftAnswers>;
    return {
      jurisdictions: parsed.jurisdictions ?? null,
      jurisdictions_other: parsed.jurisdictions_other ?? null,
    };
  } catch {
    return null;
  }
}

function writeDraft(orgId: string | null | undefined, draft: DraftAnswers): void {
  const key = draftStorageKey(orgId);
  if (!key || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // localStorage quota / private mode — silently ignore. The wizard
    // continues to work from React state for this session.
  }
}

function clearDraft(orgId: string | null | undefined): void {
  const key = draftStorageKey(orgId);
  if (!key || typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/**
 * Find the first step (zero-indexed) whose corresponding answer is
 * absent. Used by `open()` so resume lands on next-unanswered, not
 * last-saved. Returns 0 when no answers exist, TOTAL_STEPS-1 when
 * every answer exists (so the user lands on the final review step).
 */
export function firstUnansweredStep(answers: WizardAnswers): WizardStep {
  for (let i = 0; i < WIZARD_STEP_FIELDS.length; i += 1) {
    const field = WIZARD_STEP_FIELDS[i];
    const v = answers[field];
    if (v === null || v === undefined) {
      return i as WizardStep;
    }
    if (Array.isArray(v) && v.length === 0) {
      return i as WizardStep;
    }
  }
  return (TOTAL_STEPS - 1) as WizardStep;
}

/**
 * Validate the current step's answer enough to enable the Next button.
 * Server is the source of truth — we duplicate just enough here to
 * avoid round-trips on every keystroke.
 */
export function isStepValid(step: WizardStep, answers: WizardAnswers): boolean {
  switch (step) {
    case 0: {
      // Jurisdictions — non-empty list including ``us_federal``.
      // ``jurisdictions_other`` validation is NOT required (soft
      // contract — disclosure renders the section regardless).
      const j = answers.jurisdictions;
      return Array.isArray(j) && j.length > 0 && j.includes("us_federal");
    }
    case 1: {
      const po = answers.privacy_officer;
      if (!po) return false;
      const nameOk = Boolean(po.name && po.name.trim().length > 0);
      const emailOk = Boolean(
        po.email && po.email.includes("@") && po.email.split("@")[1]?.includes("."),
      );
      return nameOk && emailOk;
    }
    default:
      return false;
  }
}

export interface UseOnboardingWizardReturn {
  isOpen: boolean;
  currentStep: WizardStep;
  answers: WizardAnswers;
  /** Server-side completion timestamp (ISO). null while in-progress / unopened. */
  completedAt: string | null;
  /** Inline submit error from the most recent POST attempt. */
  submitError: string | null;
  /**
   * Inline error from the post-completion ``POST /v1/templates/generate``
   * call. Non-null when the wizard saved cleanly but template
   * generation failed.
   */
  generateError: string | null;
  /** Network status. */
  isLoading: boolean;
  isSubmitting: boolean;
  /** True when the current step's answer satisfies client-side validation. */
  canAdvance: boolean;
  open: () => void;
  close: () => void;
  goToStep: (step: WizardStep) => void;
  next: () => void;
  back: () => void;
  toggleJurisdiction: (j: WizardJurisdiction) => void;
  setJurisdictionsOther: (next: string[]) => void;
  setPrivacyOfficer: (next: WizardPrivacyOfficer) => void;
  /**
   * POST with completed=true. On success closes the modal AND fires
   * the post-completion handoff: ``generateTemplates()`` →
   * ``router.push(TEMPLATES_REDIRECT_PATH)``. A failure of the
   * generate step does NOT block the close — see ``generateError``.
   */
  submit: () => Promise<void>;
}

const OnboardingWizardContext =
  React.createContext<UseOnboardingWizardReturn | null>(null);

export interface OnboardingWizardProviderProps {
  children: React.ReactNode;
}

export function OnboardingWizardProvider({
  children,
}: OnboardingWizardProviderProps) {
  const { organization, isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();
  const orgId = organization?.id ?? null;

  const [isOpen, setIsOpen] = React.useState(false);
  const [currentStep, setCurrentStep] = React.useState<WizardStep>(0);
  const [answers, setAnswers] = React.useState<WizardAnswers>(() => emptyAnswers());
  const [completedAt, setCompletedAt] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [generateError, setGenerateError] = React.useState<string | null>(null);
  const [hydratedOrgId, setHydratedOrgId] = React.useState<string | null>(null);

  // ── Persist non-PII draft to localStorage on every answers change.
  React.useEffect(() => {
    if (!orgId) return;
    const draft: DraftAnswers = {
      jurisdictions: answers.jurisdictions,
      jurisdictions_other: answers.jurisdictions_other,
    };
    // Only write if at least one field is populated — avoids touching
    // localStorage just to write a row of nulls for every org load.
    const anyAnswered =
      (draft.jurisdictions && draft.jurisdictions.length > 0) ||
      (draft.jurisdictions_other && draft.jurisdictions_other.length > 0);
    if (anyAnswered) {
      writeDraft(orgId, draft);
    }
  }, [orgId, answers]);

  // ── Hydrate from server + localStorage when org changes.
  React.useEffect(() => {
    if (!isSignedIn || !orgId) {
      setHydratedOrgId(null);
      return;
    }
    if (hydratedOrgId === orgId) return;

    let cancelled = false;
    setIsLoading(true);

    getWizardAnswers()
      .then((res: WizardAnswersResponse) => {
        if (cancelled) return;
        const server = res.answers ?? emptyAnswers();
        const draft = readDraft(orgId);
        // Server wins on each field; fall back to localStorage draft for
        // non-PII fields the server doesn't have yet. PrivacyOfficer
        // always comes from server (no localStorage source).
        const merged: WizardAnswers = {
          jurisdictions:
            server.jurisdictions ?? draft?.jurisdictions ?? null,
          jurisdictions_other:
            server.jurisdictions_other ?? draft?.jurisdictions_other ?? null,
          privacy_officer: server.privacy_officer ?? null,
        };
        setAnswers(merged);
        setCompletedAt(res.completed_at);
        setHydratedOrgId(orgId);
      })
      .catch(() => {
        // 401/403 etc. — leave defaults.
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isSignedIn, orgId, hydratedOrgId]);

  const open = React.useCallback(() => {
    setSubmitError(null);
    setCurrentStep(firstUnansweredStep(answers));
    setIsOpen(true);
  }, [answers]);

  const close = React.useCallback(() => {
    setIsOpen(false);
    setSubmitError(null);
    setGenerateError(null);
  }, []);

  const goToStep = React.useCallback((step: WizardStep) => {
    setCurrentStep(step);
  }, []);

  const next = React.useCallback(() => {
    setCurrentStep((s) => {
      const max = (TOTAL_STEPS - 1) as WizardStep;
      const candidate = Math.min(s + 1, max);
      return candidate as WizardStep;
    });
  }, []);

  const back = React.useCallback(() => {
    setCurrentStep((s) => Math.max(0, s - 1) as WizardStep);
  }, []);

  const toggleJurisdiction = React.useCallback((j: WizardJurisdiction) => {
    setAnswers((prev) => {
      // us_federal is required and cannot be toggled off.
      if (j === "us_federal") {
        const current = prev.jurisdictions ?? [];
        if (current.includes("us_federal")) return prev;
        return { ...prev, jurisdictions: [...current, "us_federal"] };
      }
      const current = prev.jurisdictions ?? ["us_federal"];
      const has = current.includes(j);
      const nextList = has
        ? current.filter((x) => x !== j)
        : [...current, j];
      // If the user deselected ``other``, clear the free-text list too
      // so a stale draft doesn't keep PII-adjacent content around.
      const nextOther =
        j === "other" && has ? null : prev.jurisdictions_other;
      return {
        ...prev,
        jurisdictions: nextList,
        jurisdictions_other: nextOther,
      };
    });
  }, []);

  const setJurisdictionsOther = React.useCallback((next: string[]) => {
    setAnswers((prev) => ({ ...prev, jurisdictions_other: next }));
  }, []);

  const setPrivacyOfficer = React.useCallback(
    (next: WizardPrivacyOfficer) => {
      setAnswers((prev) => ({ ...prev, privacy_officer: next }));
    },
    [],
  );

  const submit = React.useCallback(async () => {
    setIsSubmitting(true);
    setSubmitError(null);
    setGenerateError(null);
    try {
      const body: WizardAnswersSubmission = {
        answers,
        completed: true,
      };
      const res = await submitWizardAnswers(body);
      setCompletedAt(res.completed_at);
      if (res.answers) setAnswers(res.answers);
      // Wipe the on-disk draft once the answers live on the server.
      clearDraft(orgId);
      queryClient.invalidateQueries({ queryKey: ["wizard-answers"] });
      queryClient.invalidateQueries({ queryKey: ["organization"] });

      // ── Phase 5 PR B2 — Post-completion handoff ─────────────────
      try {
        const generated = await generateTemplates();
        setIsOpen(false);
        const count = generated.generated.length + generated.skipped_attested.length;
        toast.success(TEMPLATES_GENERATED_TOAST(count));
        router.push(TEMPLATES_REDIRECT_PATH);
      } catch (genErr) {
        const message =
          genErr instanceof ApiError && genErr.message
            ? `${TEMPLATES_GENERATE_FAILED_MESSAGE} (${genErr.message})`
            : TEMPLATES_GENERATE_FAILED_MESSAGE;
        setGenerateError(message);
        toast.error(TEMPLATES_GENERATE_FAILED_MESSAGE);
        setIsOpen(false);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.message || "Couldn't save your answers.");
      } else {
        setSubmitError("Couldn't save your answers.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [answers, orgId, queryClient, router]);

  const canAdvance = React.useMemo(
    () => isStepValid(currentStep, answers),
    [currentStep, answers],
  );

  const value: UseOnboardingWizardReturn = {
    isOpen,
    currentStep,
    answers,
    completedAt,
    submitError,
    generateError,
    isLoading,
    isSubmitting,
    canAdvance,
    open,
    close,
    goToStep,
    next,
    back,
    toggleJurisdiction,
    setJurisdictionsOther,
    setPrivacyOfficer,
    submit,
  };

  return (
    <OnboardingWizardContext.Provider value={value}>
      {children}
    </OnboardingWizardContext.Provider>
  );
}

export function useOnboardingWizard(): UseOnboardingWizardReturn {
  const ctx = React.useContext(OnboardingWizardContext);
  if (!ctx) {
    throw new Error(
      "useOnboardingWizard must be rendered inside <OnboardingWizardProvider>",
    );
  }
  return ctx;
}
