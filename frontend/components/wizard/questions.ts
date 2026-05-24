/**
 * Onboarding wizard question copy (Phase 1 PR 14, Stream F item F5).
 *
 * The labels here mirror `policy-engine-mvp.md` Appendix A — the
 * canonical 5-question source of truth. Do NOT paraphrase; if the
 * Appendix wording changes, update both surfaces together.
 *
 * Slugs (the values) are the wire format the backend persists; labels
 * are display-only. Keep slugs stable across releases — a slug rename
 * forces a backfill of `wizard_answers` rows on the Organization table.
 */

import type {
  WizardAgentType,
  WizardDecisionVolume,
  WizardJurisdiction,
  WizardReviewChannel,
} from "@/lib/api-types";

export interface RadioChoice<V extends string> {
  value: V;
  label: string;
  description?: string;
}

export interface CheckboxChoice<V extends string> {
  value: V;
  label: string;
  description?: string;
  /** When true the option is rendered checked + disabled. */
  required?: boolean;
}

// Q1 — Agent type. Appendix A:
//   "AI scribe / chart entry assistant"
//   "AI receptionist / voice agent"
//   "AI prior-auth / claims agent"
//   "AI triage / symptom checker"
//   "Other clinical AI"
export const AGENT_TYPE_CHOICES: ReadonlyArray<RadioChoice<WizardAgentType>> = [
  { value: "scribe", label: "AI scribe / chart entry assistant" },
  { value: "receptionist", label: "AI receptionist / voice agent" },
  { value: "prior_auth", label: "AI prior-auth / claims agent" },
  { value: "triage", label: "AI triage / symptom checker" },
  { value: "other", label: "Other clinical AI" },
];

// Q2 — Jurisdictions. Appendix A:
//   "US Federal (HIPAA + Section 1557)  [required, can't deselect]"
//   "California (CMIA add-on)"
//   "Other state-specific (v2)"
export const JURISDICTION_CHOICES: ReadonlyArray<
  CheckboxChoice<WizardJurisdiction>
> = [
  {
    value: "us_federal",
    label: "US Federal (HIPAA + Section 1557)",
    description: "Required — applies to every Vera deployment.",
    required: true,
  },
  { value: "us_ca", label: "California (CMIA add-on)" },
  { value: "other_state", label: "Other state-specific (v2)" },
];

// Q3 — Decision volume per month. Appendix A:
//   "< 10,000      (Starter)"
//   "10K - 100K    (Growth)"
//   "100K - 1M     (Scale)"
//   "> 1M          (Enterprise)"
export const DECISION_VOLUME_CHOICES: ReadonlyArray<
  RadioChoice<WizardDecisionVolume>
> = [
  { value: "lt_10k", label: "< 10,000", description: "Starter" },
  { value: "10k_100k", label: "10K – 100K", description: "Growth" },
  { value: "100k_1m", label: "100K – 1M", description: "Scale" },
  { value: "gt_1m", label: "> 1M", description: "Enterprise" },
];

// Q4 — Channel for human review. Appendix A:
//   "In-app webhook (default — your product handles review UI;
//                    Vera invisible to your end users)"
//   "Slack (for solo practitioners or your own dev/compliance team)"
//   "Vera dashboard (compliance officer batch oversight, not clinical flow)"
//   "Multiple (combine — e.g., webhook for clinical, dashboard for compliance)"
export const REVIEW_CHANNEL_CHOICES: ReadonlyArray<
  RadioChoice<WizardReviewChannel>
> = [
  {
    value: "in_app_webhook",
    label: "In-app webhook",
    description:
      "Default — your product handles the review UI; Vera stays invisible to your end users.",
  },
  {
    value: "slack",
    label: "Slack",
    description:
      "For solo practitioners or your own dev / compliance team.",
  },
  {
    value: "vera_dashboard",
    label: "Vera dashboard",
    description:
      "Compliance officer batch oversight, not clinical flow.",
  },
  {
    value: "multiple",
    label: "Multiple",
    description:
      "Combine — e.g. webhook for clinical, dashboard for compliance.",
  },
];

// Question prompts. Use the exact Appendix A wording.
export const QUESTION_PROMPTS = {
  agent_type: "What kind of AI agent are you running?",
  jurisdictions: "What jurisdictions do you operate in?",
  decision_volume: "How many AI decisions per month, roughly?",
  channel: "Which channel for human review?",
  privacy_officer: "Your designated HIPAA Privacy Officer (name + email):",
} as const;

export const TOTAL_STEPS = 5 as const;
