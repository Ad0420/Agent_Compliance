/**
 * Onboarding wizard question copy — 2-question redesign (Phase 5 polish).
 *
 * Slugs (the values) are the wire format the backend persists; labels
 * are display-only. Keep slugs stable across releases — a slug rename
 * forces a backfill of `wizard_answers` rows on the Organization table.
 *
 * The original 5-question wizard was trimmed to 2 questions
 * (jurisdictions + privacy_officer) after user testing surfaced that
 * the other three answers (agent_type, decision_volume, channel) never
 * drove differentiated product behaviour. The retired choice arrays
 * (AGENT_TYPE_CHOICES etc.) no longer exist — a stale import will
 * fail tsc, which is what we want.
 */

import type { WizardJurisdiction } from "@/lib/api-types";

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

// Q1 — Jurisdictions. Expanded set in Phase 5 polish:
//   us_federal       — required, always included (HIPAA + Section 1557)
//   california_ab489 — clinical decision support disclosure
//   california_sb942 — AI consumer disclosure
//   texas            — TRAIGA healthcare provisions
//   utah             — AIPA generative AI disclosure
//   colorado         — SB 24-205 consequential AI disclosure
//   eu               — EU AI Act high-risk AI obligations
//   new_york         — placeholder (no built-in clause yet)
//   other            — free-text partner to ``jurisdictions_other``
export const JURISDICTION_CHOICES: ReadonlyArray<
  CheckboxChoice<WizardJurisdiction>
> = [
  {
    value: "us_federal",
    label: "United States (HIPAA + Section 1557)",
    description: "Federal baseline. Always included.",
    required: true,
  },
  {
    value: "california_ab489",
    label: "California — AB 489",
    description: "Clinical decision support disclosure (medtech)",
  },
  {
    value: "california_sb942",
    label: "California — SB 942",
    description: "AI consumer disclosure (in force Aug 2026)",
  },
  {
    value: "texas",
    label: "Texas — TRAIGA",
    description: "Responsible AI Governance Act, healthcare provisions",
  },
  {
    value: "utah",
    label: "Utah — AIPA",
    description: "AI Policy Act, generative AI disclosure",
  },
  {
    value: "colorado",
    label: "Colorado — SB 24-205",
    description: "Consequential AI decisions (in force Jun 2026)",
  },
  {
    value: "eu",
    label: "European Union — AI Act",
    description: "High-risk AI obligations (in force Aug 2026)",
  },
  {
    value: "new_york",
    label: "New York",
    description: "Placeholder — coordinate with counsel",
  },
  {
    value: "other",
    label: "Other (specify below)",
    description: "We'll add a placeholder section for counsel review",
  },
];

// Question prompts. Header copy for each step.
export const QUESTION_PROMPTS = {
  jurisdictions: "Where do your customers' end users live?",
  privacy_officer: "Your designated HIPAA Privacy Officer",
} as const;

// Sub-copy rendered under each header.
export const QUESTION_SUBPROMPTS = {
  jurisdictions:
    "We use this to add the right disclosure clauses to your templates. Pick everywhere your customers operate — you can change this later.",
  privacy_officer:
    "We'll insert this name into your HIPAA Risk Analysis and Section 1557 templates as the named coordinator. Stored on your organization only.",
} as const;

export const TOTAL_STEPS = 2 as const;
