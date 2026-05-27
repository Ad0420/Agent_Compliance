/**
 * Human-readable metadata for the five Phase 5 templates.
 *
 * The display names are pinned per the PR B1 brief; descriptions are
 * one-line companions the card grid renders below the title so the
 * reader can pick the right document without guessing. Kept here as a
 * single source of truth so any drift between the editor view and the
 * card grid trips a TypeScript error.
 */

import type { TemplateKey } from "@/lib/api-client";

export const TEMPLATE_DISPLAY_NAMES: Record<TemplateKey, string> = {
  hipaa_risk_analysis: "HIPAA Risk Analysis",
  section_1557_ndp: "Section 1557 Nondiscrimination Policy",
  ai_tool_inventory: "AI Tool Inventory",
  workforce_training_outline: "Workforce AI Training Module",
  ai_care_disclosure: "AI-Assisted Care Disclosure",
};

export const TEMPLATE_DESCRIPTIONS: Record<TemplateKey, string> = {
  hipaa_risk_analysis:
    "Annual risk-analysis worksheet covering the safeguards required under 45 CFR § 164.308(a)(1).",
  section_1557_ndp:
    "Nondiscrimination policy covering the use of AI-driven patient-care tools under HHS Section 1557.",
  ai_tool_inventory:
    "Itemised inventory of AI tools in use, their vendors, and the decisions they influence.",
  workforce_training_outline:
    "Curriculum outline for the annual workforce training module on AI-assisted care.",
  ai_care_disclosure:
    "Patient-facing disclosure describing how AI tools support — and never replace — clinician judgment.",
};
