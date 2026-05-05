// Content for the Regulations v2 dossier.
// Each entry has the headline triad (fine, deadline, verdict),
// a sales-mode short body, full-statute drawer content, and citations.

// Live "today" — module-level so server-rendered initial paint and client-side
// hydration both reference a stable value. Components that need exact local
// midnight should call `getToday()` inside a useEffect/useState to avoid SSR
// time-zone drift.
export function getToday(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}
export const TODAY = getToday();

export type DeadlineState = "live" | "soon" | "ongoing";

export type Fine = { big: string; sub: string; per?: string };

export type Tier = "I" | "II" | "III";

export type ScalePayload =
  | { kind: "tiers"; rows: Array<{ lbl: string; val: string; tier: "top" | "mid" | "low"; pct: number }> }
  | { kind: "multiplier"; per: number; unit: "$/violation" | "$/consumer"; defaultCount: number; label: string }
  | { kind: "daily"; perDay: number; marks: number[]; label: string }
  | { kind: "examples"; items: Array<{ name: string; year: string; fine: string }> }
  | { kind: "ladder"; steps: Array<{ label: string; note?: string }> };

export type ReqItem = { label: string; ref?: string };

export type Reg = {
  id: string;
  num: string;
  short: string;
  label: string;
  sub: string;
  targetDate: string | null;
  anchorDate?: string;
  forceDate?: string;
  fine: Fine | null;
  verdict: string | null;
  verdictAfter?: string | null;
  triadOverride?: { fine?: Fine; verdict?: string; verdictAfter?: string };
  plain: {
    what: string;
    who: string;
    reqs: string[];
    reqsExtra?: string[];
  };
  statute: {
    what: string;
    who: string;
    timeline: Array<[string, string]>;
    penalties: Array<[string, string]>;
    penaltyNote?: string;
    reqs: string[];
    proposed?: string[];
    nuance?: string;
  };
  citations: Record<string, string>;
  exposure: number;
  fineFlat?: number;
  // Wave 2 redesign — additive fields. Old fields above remain populated until
  // consumers migrate in subsequent PRs.
  tier: Tier;
  tierLabel: string;
  scopeTrigger: string;
  oneliner: string;
  footnote: string;
  beforeDeployment: ReqItem[];
  duringDeployment: ReqItem[];
  scale: ScalePayload;
  source: { citation: string; lastVerified: string };
};

export function daysBetween(target: string | Date): number {
  const t = new Date(target);
  return Math.round((t.getTime() - TODAY.getTime()) / (1000 * 60 * 60 * 24));
}

export type DeadlineInfo = {
  state: DeadlineState;
  deadlineLine: string;
  daysLine: string;
  fillPct: number;
};

export function computeDeadlineState(targetDate: string | null, anchorDate?: string): DeadlineInfo {
  if (!targetDate) {
    return { state: "ongoing", deadlineLine: "Already in force", daysLine: "no future trigger date", fillPct: 100 };
  }
  const days = daysBetween(targetDate);
  if (days <= 0) {
    return { state: "live", deadlineLine: "Already in force", daysLine: `enforced since ${formatDate(targetDate)}`, fillPct: 100 };
  }
  const total = anchorDate
    ? Math.max(1, Math.round((new Date(targetDate).getTime() - new Date(anchorDate).getTime()) / (1000 * 60 * 60 * 24)))
    : Math.max(days, 365);
  const fillPct = Math.max(4, Math.min(100, Math.round(((total - days) / total) * 100)));
  return { state: "soon", deadlineLine: `${days} days`, daysLine: `until ${formatDate(targetDate)}`, fillPct };
}

export function formatDate(d: string | Date): string {
  const dt = new Date(d);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export const REGS: Reg[] = [
  {
    id: "eu",
    num: "01",
    short: "EU",
    label: "EU AI Act",
    sub: "Regulation (EU) 2024/1689",
    targetDate: "2026-08-02",
    anchorDate: "2024-08-02",
    fine: { big: "€35M", sub: "or 7% of worldwide turnover", per: "per prohibited-practice violation" },
    verdict:
      "The largest fine ceiling ever written into a technology law. It applies extraterritorially. If your output reaches a user in the EU, you are in scope.",
    verdictAfter:
      "August 2, 2026 is the binding date for high-risk system obligations. The November 2025 Digital Omnibus proposal could link this to harmonized standards readiness, but the date has not moved.",
    plain: {
      what: "The world's first comprehensive AI law. Sorts every AI system into four buckets and writes binding rules for the top two.",
      who: "Any provider or deployer of AI in the EU. Also applies to non-EU companies whose output reaches EU users. The same extraterritorial reach as GDPR.",
      reqs: [
        "Risk management system",
        "Automatic logging of every operation",
        "Human oversight for high-risk systems",
        "Serious incident reporting in 2 / 10 / 15-day windows",
      ],
      reqsExtra: [
        "Data governance",
        "Technical documentation per Annex IV",
        "Transparency obligations to users",
        "Accuracy, robustness, cybersecurity",
        "Post-market monitoring",
        "CE marking and EU database registration",
      ],
    },
    statute: {
      what: "Regulation (EU) 2024/1689. Risk-tiered framework: prohibited, high-risk, limited-risk, minimal-risk. Distinguishes providers from deployers and assigns separate obligations to each.",
      who: "Any provider or deployer of AI systems used in the EU, including non-EU companies whose AI output reaches EU users. Extra-territorial reach mirrors GDPR.",
      timeline: [
        ["Feb 2, 2025", "Prohibited practices (Article 5), AI literacy obligations"],
        ["Aug 2, 2025", "GPAI model obligations, governance bodies operational"],
        ["Aug 2, 2026", "High-risk system obligations (Annex III), transparency rules (Article 50)"],
        ["Aug 2, 2027", "High-risk AI embedded in regulated products (Annex II)"],
      ],
      penalties: [
        ["Prohibited practices (Article 5)", "€35M or 7% of worldwide turnover"],
        ["High-risk obligations", "€15M or 3% of worldwide turnover"],
        ["Incorrect or misleading information", "€7.5M or 1% of worldwide turnover"],
      ],
      penaltyNote: "For SMEs and startups, the fine is capped at the lower of the two amounts.",
      reqs: [
        "Risk management system (Article 9)",
        "Data governance (Article 10)",
        "Technical documentation per Annex IV (Article 11)",
        "Automatic logging of operation (Article 12)",
        "Transparency to users (Article 13)",
        "Human oversight (Article 14)",
        "Accuracy, robustness, cybersecurity (Article 15)",
        "Post-market monitoring (Article 72)",
        "Serious incident reporting in 2 / 10 / 15-day windows (Article 73)",
        "CE marking and EU database registration (Article 71)",
      ],
    },
    citations: {
      "Art. 5":
        "Prohibits manipulative AI, social scoring, real-time biometric ID in public, and other unacceptable-risk practices.",
      "Art. 12": "Requires automatic logging of operation throughout the lifecycle of a high-risk AI system.",
      "Art. 14":
        "Mandates human oversight measures designed to prevent or minimize risks to health, safety, or fundamental rights.",
      "Art. 73":
        "Serious incidents must be reported in tiered windows: 2 days for widespread infringement, 10 for serious harm, 15 for other reportable incidents.",
    },
    exposure: 0.07,
    tier: "I",
    tierLabel: "TIER I · UNCAPPED EXPOSURE",
    scopeTrigger: "Output reaches a user in the EU.",
    oneliner:
      "€35M or 7% of worldwide turnover for prohibited practices. Applies to any AI provider whose output reaches a user in the EU, regardless of where the company is based.",
    footnote:
      "August 2, 2026 is the binding date for high-risk obligations. The November 2025 Digital Omnibus proposal could link this to harmonized standards readiness, but the date has not moved.",
    beforeDeployment: [
      { label: "Risk management system", ref: "Art. 9" },
      { label: "Data governance", ref: "Art. 10" },
      { label: "Technical documentation per Annex IV", ref: "Art. 11" },
      { label: "Transparency mechanisms designed", ref: "Art. 13" },
      { label: "Human oversight measures designed", ref: "Art. 14" },
      { label: "Accuracy, robustness, cybersecurity validated", ref: "Art. 15" },
      { label: "CE marking and EU database registration", ref: "Art. 71" },
    ],
    duringDeployment: [
      { label: "Automatic logging of operation", ref: "Art. 12" },
      { label: "Post-market monitoring", ref: "Art. 72" },
      { label: "Serious incident reporting · 2 / 10 / 15-day windows", ref: "Art. 73" },
    ],
    scale: {
      kind: "tiers",
      rows: [
        { lbl: "Prohibited practices (Art. 5)", val: "€35M / 7%", tier: "top", pct: 100 },
        { lbl: "High-risk obligations", val: "€15M / 3%", tier: "mid", pct: 43 },
        { lbl: "Misleading information", val: "€7.5M / 1%", tier: "low", pct: 21 },
      ],
    },
    source: { citation: "Regulation (EU) 2024/1689", lastVerified: "2026-04-30" },
  },
  {
    id: "co",
    num: "02",
    short: "CO",
    label: "Colorado",
    sub: "SB 24-205 (ADAI)",
    targetDate: "2026-06-30",
    anchorDate: "2024-05-17",
    fine: {
      big: "Unfair trade practice",
      sub: "Colorado Consumer Protection Act",
      per: "AG enforcement, 60-day cure period",
    },
    verdict:
      "The first comprehensive US state AI law. There is no headline fine number, but every consequential decision in lending, hiring, healthcare, housing, or insurance will be reviewable.",
    verdictAfter:
      "Originally Feb 1, 2026. Pushed to June 30, 2026 by SB 25B-004 (signed August 28, 2025). The delay is final.",
    plain: {
      what: "Targets algorithmic discrimination in consequential decisions. Splits responsibility between developers (the model builders) and deployers (the businesses applying them).",
      who: "Anyone making or substantially influencing decisions in education, employment, financial services, government services, healthcare, housing, insurance, or legal services.",
      reqs: [
        "Reasonable care to prevent algorithmic discrimination",
        "Annual impact assessments",
        "Consumer notice when AI is used in a consequential decision",
        "Right of appeal with human review where feasible",
      ],
      reqsExtra: [
        "Risk management policy (NIST AI RMF or ISO/IEC 42001 satisfy)",
        "Disclose discovered algorithmic discrimination to the AG within 90 days",
        "Developers: documentation and intended-use statements for deployers",
        "Developers: public statement summarizing high-risk systems offered",
      ],
    },
    statute: {
      what: "Colorado SB 24-205 (sometimes called ADAI, the Anti-Discrimination in AI Law). Targets algorithmic discrimination in consequential decisions.",
      who: "Developers and deployers of high-risk AI systems making or substantially influencing consequential decisions in education, employment, financial services, government services, healthcare, housing, insurance, legal services.",
      timeline: [["June 30, 2026", "Effective date (delayed from Feb 1, 2026 by SB 25B-004)"]],
      penalties: [
        [
          "Violation type",
          "Unfair trade practice under the Colorado Consumer Protection Act. Enforced exclusively by the Colorado AG. 60-day cure period before enforcement. No private right of action.",
        ],
      ],
      reqs: [
        "Deployers: use reasonable care to prevent algorithmic discrimination",
        "Deployers: maintain a risk management policy (NIST AI RMF or ISO/IEC 42001 satisfy)",
        "Deployers: complete impact assessments annually and within 90 days of substantial modifications",
        "Deployers: notify consumers when AI is used in consequential decisions",
        "Deployers: provide a right to appeal with human review where technically feasible",
        "Deployers: disclose discovered algorithmic discrimination to the AG within 90 days",
        "Developers: provide deployers with documentation, intended-use statements, and impact-assessment artifacts",
        "Developers: maintain a public statement summarizing high-risk systems offered",
      ],
    },
    citations: {
      ADAI: "Anti-Discrimination in AI Law. Common nickname for Colorado SB 24-205.",
      "Consequential decision":
        "A decision with material legal or similarly significant effects on a consumer, including offers of credit, employment, insurance, healthcare, or housing.",
    },
    exposure: 0,
    tier: "I",
    tierLabel: "TIER I · UNCAPPED EXPOSURE",
    scopeTrigger:
      "AI is used to make or substantially influence a consequential decision about a Colorado consumer.",
    oneliner:
      "Targets algorithmic discrimination in consequential decisions across education, employment, financial services, healthcare, housing, insurance, government, and legal services. Enforced exclusively by the Colorado AG via the Consumer Protection Act, with a 60-day cure period.",
    footnote:
      "Pushed from February 1 to June 30, 2026 by SB 25B-004 (signed August 28, 2025). The delay is final.",
    beforeDeployment: [
      { label: "Risk management policy adopted (NIST AI RMF or ISO/IEC 42001 satisfy)" },
      { label: "Initial impact assessment for the high-risk AI system" },
      { label: "Developers: documentation, intended-use statements, impact-assessment artifacts for deployers" },
      { label: "Developers: public statement summarizing high-risk systems offered" },
    ],
    duringDeployment: [
      { label: "Reasonable care to prevent algorithmic discrimination" },
      { label: "Annual impact assessments + within 90 days of substantial modification" },
      { label: "Notify consumers when AI is used in consequential decisions" },
      { label: "Right to appeal with human review where technically feasible" },
      { label: "Disclose discovered algorithmic discrimination to the AG within 90 days" },
    ],
    scale: {
      kind: "multiplier",
      per: 20000,
      unit: "$/consumer",
      defaultCount: 1000,
      label: "$20,000 per violation per consumer — scales linearly with affected consumers",
    },
    source: { citation: "Colorado SB 24-205 (Anti-Discrimination in AI Law)", lastVerified: "2026-04-30" },
  },
  {
    id: "tx",
    num: "03",
    short: "TX",
    label: "Texas",
    sub: "HB 149 · TRAIGA",
    targetDate: null,
    forceDate: "2026-01-01",
    fine: { big: "$200K", sub: "per violation", per: "Texas AG enforcement, 60-day cure period" },
    verdict:
      "Already in force since January 1. Most enforcement weight sits on government and healthcare, but the prohibited-use clauses apply to every operator in the state.",
    verdictAfter:
      "Compliance with the NIST AI Risk Management Framework provides an affirmative defense. Private-sector employers are not required to run impact assessments under TRAIGA.",
    plain: {
      what: "A targeted AI law focused on prohibited uses. The original framework was significantly scaled back through the legislative process.",
      who: "Anyone developing or deploying AI in Texas, or advertising AI products to Texas residents. Operational obligations land hardest on government agencies and healthcare providers.",
      reqs: [
        "No AI intended to incite self-harm, violence, or criminal activity",
        "No AI for unlawful deepfakes or impersonating minors",
        "No AI deployed with intent to discriminate against protected classes",
        "Government agencies and healthcare providers: disclose AI use to consumers",
      ],
      reqsExtra: [
        "Affirmative defense: NIST AI Risk Management Framework compliance",
        "60-day cure period before AG enforcement",
        "No private right of action",
      ],
    },
    statute: {
      what: "Texas Responsible AI Governance Act (HB 149). Already in force since January 1, 2026. Significantly scaled back from the original proposed framework.",
      who: "Entities developing or deploying AI in Texas, advertising or providing products to Texas residents. Most operational obligations apply to government agencies and healthcare providers, not private employers.",
      timeline: [["Jan 1, 2026", "Effective. Already in force."]],
      penalties: [
        ["Maximum civil penalty", "$200,000 per violation"],
        ["Enforcement", "Texas Attorney General, exclusive"],
        ["Cure period", "60 days"],
        ["Private right of action", "None"],
      ],
      reqs: [
        "Prohibited: AI intended to incite self-harm, violence, or criminal activity",
        "Prohibited: AI producing or distributing child sexual abuse material",
        "Prohibited: AI used to create unlawful deepfakes or impersonate minors in sexual contexts",
        "Prohibited: AI deployed with intent to discriminate against protected classes (intent-based; disparate impact alone is not sufficient)",
        "Government agencies: must disclose AI use in consumer interactions",
        "Healthcare providers: must disclose AI use in patient treatment",
      ],
      nuance:
        "Private-sector employers are not required to conduct impact assessments or implement risk-management policies under TRAIGA. Compliance with the NIST AI Risk Management Framework provides an affirmative defense.",
    },
    citations: {
      TRAIGA: "Texas Responsible AI Governance Act. The shipped version of HB 149.",
      "Affirmative defense": "Compliance with NIST AI RMF can be raised as a defense if enforcement is brought.",
    },
    exposure: 0,
    fineFlat: 200000,
    tier: "II",
    tierLabel: "TIER II · CAPPED EXPOSURE",
    scopeTrigger: "AI is developed, deployed, or marketed in Texas.",
    oneliner:
      "$200,000 per violation, Texas AG enforcement, 60-day cure period. Prohibited-use clauses apply to any operator. Most operational obligations are limited to government agencies and healthcare providers.",
    footnote:
      "Compliance with the NIST AI Risk Management Framework provides an affirmative defense. Private-sector employers are not required to run impact assessments under TRAIGA.",
    beforeDeployment: [
      { label: "Confirm AI is not designed to incite self-harm, violence, or criminal activity" },
      { label: "Confirm AI is not designed for unlawful deepfakes or impersonating minors in sexual contexts" },
      { label: "Confirm AI is not deployed with intent to discriminate against protected classes" },
    ],
    duringDeployment: [
      { label: "Government agencies: disclose AI use in consumer interactions" },
      { label: "Healthcare providers: disclose AI use in patient treatment" },
      { label: "Maintain NIST AI RMF compliance to preserve affirmative defense" },
    ],
    scale: {
      kind: "multiplier",
      per: 200000,
      unit: "$/violation",
      defaultCount: 5,
      label: "$200,000 per discrete violation",
    },
    source: { citation: "Texas Responsible AI Governance Act (HB 149)", lastVerified: "2026-04-30" },
  },
  {
    id: "ca",
    num: "04",
    short: "CA",
    label: "California",
    sub: "AB 316 · AB 2013 · SB 942",
    targetDate: "2026-08-02",
    anchorDate: "2025-10-13",
    fine: { big: "$5,000", sub: "per violation, per day", per: "SB 942 (CAITA), August 2, 2026" },
    verdict:
      "California stacks four AI statutes on top of one another. Most are already in force. SB 942 is the one with daily-compounding penalties.",
    verdictAfter:
      "AB 316 closes the autonomy defense. AB 2013 forces public training-data summaries back to 2022. SB 942 takes effect August 2, 2026, deliberately aligned with the EU AI Act.",
    plain: {
      what: "Four statutes covering different AI exposures: civil liability, training-data transparency, generative-AI disclosures, and a new frontier-model regime.",
      who: "Any GenAI provider with over one million California monthly users falls under SB 942. AB 316 and AB 2013 apply broadly to anyone deploying or training AI for Californians.",
      reqs: [
        "AB 316: AI cannot be used as an autonomy defense in civil actions",
        "AB 2013: publish training-data summaries (retroactive to 2022)",
        "SB 942: free public AI detection tool",
        "SB 942: manifest and latent disclosures on AI content",
      ],
      reqsExtra: [
        "AB 489: AI cannot claim a healthcare license; patient disclosure required",
        "SB 243: companion chatbot disclosures, suicide/self-harm safety, minor protections",
        "SB 53: frontier-model developer obligations",
        "AB 853 (2027): large platforms must provide content provenance disclosure",
      ],
    },
    statute: {
      what: "California has enacted multiple AI laws with staggered effective dates. Key statutes: AB 316, AB 2013, SB 942, AB 489, SB 243, SB 53.",
      who: "Most apply to any AI provider serving California users. SB 942 has a million-monthly-user threshold.",
      timeline: [
        ["Jan 1, 2026", "AB 316, AB 2013, SB 53 in force"],
        ["Aug 2, 2026", "SB 942 (CAITA) effective. Delayed from Jan 1 by AB 853 to align with EU AI Act."],
        [
          "Jan 1, 2027",
          "AB 853: large online platforms (>2M monthly users) must provide content provenance disclosure",
        ],
        ["Jan 1, 2028", "Capture device manufacturers must include latent disclosures"],
      ],
      penalties: [
        ["SB 942 (CAITA)", "$5,000 per violation per day"],
        ["AB 316", "Removes autonomy defense in civil actions; does not create strict liability"],
      ],
      reqs: [
        "AB 316: defendants who developed, modified, or used AI cannot assert that AI 'autonomously caused the harm'",
        "AB 2013: developers of GenAI publicly available to Californians must publish training-dataset summaries",
        "SB 942: free, publicly accessible AI detection tool",
        "SB 942: manifest disclosures (visible AI labels)",
        "SB 942: latent disclosures (embedded metadata, technically permanent)",
        "AB 489: prohibits AI from claiming healthcare licenses; requires patient disclosure",
        "SB 243: chatbot disclosures, suicide/self-harm safety, minor protections",
        "SB 53: frontier-model developer obligations",
      ],
    },
    citations: {
      CAITA: "California AI Transparency Act. SB 942.",
      "AB 853":
        "Signed October 13, 2025. Pushed CAITA to Aug 2, 2026 and added 2027/2028 obligations for large platforms and capture devices.",
      "Manifest disclosure": "A visible label on the AI-generated content (e.g. a watermark or notice).",
      "Latent disclosure": "Embedded metadata, technically permanent or extraordinarily difficult to remove.",
    },
    exposure: 0.005,
    fineFlat: 5000 * 365,
    tier: "I",
    tierLabel: "TIER I · UNCAPPED EXPOSURE",
    scopeTrigger: "GenAI service is offered to California users (SB 942: more than 1M monthly users).",
    oneliner:
      "$5,000 per violation per day under SB 942 for GenAI providers with over one million monthly California users. Three additional statutes in force: AB 316 (autonomy defense closed), AB 2013 (training-data transparency), SB 53 (frontier models).",
    footnote:
      "SB 942 was delayed from January 1 to August 2, 2026 by AB 853, deliberately aligning the effective date with the EU AI Act.",
    beforeDeployment: [
      { label: "AB 2013: publish training-data summaries, retroactive to January 1, 2022" },
      { label: "SB 942: free, publicly accessible AI detection tool" },
      { label: "SB 942: technical infrastructure for manifest and latent disclosures" },
      { label: "AB 489: ensure AI does not claim a healthcare license" },
      { label: "SB 53: frontier-model developer obligations" },
    ],
    duringDeployment: [
      { label: "SB 942: apply manifest disclosures (visible labels) to GenAI output" },
      { label: "SB 942: apply latent disclosures (embedded metadata) to GenAI output" },
      { label: "SB 243: companion chatbot disclosures, suicide/self-harm safety, minor protections" },
      { label: "AB 316: do not assert AI autonomy as a defense in civil actions" },
    ],
    scale: {
      kind: "daily",
      perDay: 5000,
      marks: [1, 30, 90, 365],
      label: "SB 942 — $5,000 per violation per day, compounds without statutory cap",
    },
    source: {
      citation: "California SB 942 (CAITA), AB 316, AB 2013, AB 853, AB 489, SB 53, SB 243",
      lastVerified: "2026-04-30",
    },
  },
  {
    id: "finra",
    num: "05",
    short: "FINRA",
    label: "FINRA",
    sub: "Notice 24-09 · 2026 oversight report",
    targetDate: null,
    forceDate: "2024-06-27",
    triadOverride: {
      fine: {
        big: "Existing rules",
        sub: "Rule 3110, 2210, 4511 apply",
        per: "no AI-specific rule, no fixed cap",
      },
      verdict:
        "FINRA's existing Rule 3110 supervision applies to AI use. The 2026 Annual Regulatory Oversight Report flags agentic AI as a supervisory concern.",
      verdictAfter:
        "Notice 24-09 explicitly states it does not create new legal or regulatory requirements. Examiners will measure your AI use against existing supervision, communications, and books-and-records rules.",
    },
    fine: null,
    verdict: null,
    verdictAfter: null,
    plain: {
      what: "FINRA has not issued AI-specific rules. Existing technology-neutral rules apply when member firms use AI. The 2026 oversight report is the operating manual examiners will use.",
      who: "All FINRA member firms (broker-dealers).",
      reqs: [
        "Rule 3110: supervisory system must address AI use, model risk, data integrity",
        "Rule 2210: AI-generated communications must meet content standards",
        "Rule 4511: AI-related records must be retained",
        "Human-in-the-loop review for consequential outputs",
      ],
      reqsExtra: ["Robust supervision", "Clear limits on agent scope and authority", "Strong logging and audit capabilities"],
    },
    statute: {
      what: "FINRA, the securities self-regulatory organization for US broker-dealers, has not issued AI-specific rules. Existing technology-neutral rules apply when member firms use AI.",
      who: "All FINRA member firms (broker-dealers).",
      timeline: [
        ["June 27, 2024", "Regulatory Notice 24-09 issued. Confirms existing FINRA rules apply to AI use; does not create new requirements."],
        ["December 2025", "2026 Annual Regulatory Oversight Report flags agentic AI as an emerging supervisory concern."],
        ["March 6, 2026", "FINRA Blog: Observations on AI Agents discusses oversight expectations for autonomous AI agents."],
      ],
      penalties: [
        ["Framework", "Existing FINRA disciplinary framework (fines, suspensions, sanctions)"],
        ["Sizing", "Specific amounts depend on violation type and severity"],
      ],
      reqs: [
        "Rule 3110 (Supervision): supervisory system must address AI use, model risk management, data integrity",
        "Rule 2210 (Communications): AI-generated communications must meet content standards",
        "Rule 4511 (Books and Records): AI-related records must be retained",
        "Robust supervision",
        "Clear limits on agent scope and authority",
        "Strong logging and audit capabilities",
        "Human-in-the-loop review for consequential outputs",
      ],
      nuance:
        "Notice 24-09 explicitly states it does not create new legal or regulatory requirements. FINRA enforces existing rules in the AI context.",
    },
    citations: {
      "Rule 3110":
        "FINRA's supervision rule. Member firms must establish and maintain a system to supervise the activities of associated persons.",
      "Notice 24-09": "Issued June 27, 2024. Confirms existing FINRA rules apply to AI; does not create new requirements.",
    },
    exposure: 0,
    tier: "III",
    tierLabel: "TIER III · PROCEDURAL EXPOSURE",
    scopeTrigger: "FINRA member firm (broker-dealer) using AI in any operational role.",
    oneliner:
      "No AI-specific rules. Existing technology-neutral rules apply: Rule 3110 (supervision), Rule 2210 (communications), Rule 4511 (books and records). The 2026 Annual Regulatory Oversight Report flags agentic AI as an emerging supervisory concern.",
    footnote:
      "Notice 24-09 (June 27, 2024) explicitly states it does not create new legal or regulatory requirements. Examiners measure AI use against existing supervision and recordkeeping rules.",
    beforeDeployment: [
      { label: "Establish a supervisory system addressing AI use, model risk, and data integrity", ref: "Rule 3110" },
      { label: "Define clear limits on agent scope and authority" },
      { label: "Build logging and audit capabilities for AI activity" },
    ],
    duringDeployment: [
      { label: "Ensure AI-generated communications meet content standards", ref: "Rule 2210" },
      { label: "Retain AI-related records", ref: "Rule 4511" },
      { label: "Maintain human-in-the-loop review for consequential outputs" },
    ],
    scale: {
      kind: "examples",
      // TODO: Replace with verified recent FINRA enforcement actions before merging Wave 2.
      // These are illustrative themes drawn from FINRA 2024 enforcement categories;
      // exact case data should be sourced from FINRA's public enforcement actions database.
      items: [
        { name: "Supervision · failure to address electronic comms", year: "2024", fine: "see FINRA enforcement DB" },
        { name: "Communications · misleading or non-compliant content", year: "2024", fine: "see FINRA enforcement DB" },
        { name: "Books & records · retention failures", year: "2024", fine: "see FINRA enforcement DB" },
      ],
    },
    source: {
      citation: "FINRA Regulatory Notice 24-09 + 2026 Annual Regulatory Oversight Report",
      lastVerified: "2026-04-30",
    },
  },
  {
    id: "hipaa",
    num: "06",
    short: "HIPAA",
    label: "HIPAA",
    sub: "45 CFR Parts 160, 162, 164",
    targetDate: "2026-05-15",
    anchorDate: "2025-01-06",
    fine: { big: "$2.1M", sub: "per violation category, per year", per: "tiered civil penalties, adjusted for inflation" },
    verdict:
      "Already in force. The 2026 Security Rule update is expected to land around May. There is no HIPAA-certified AI. Compliance is operational, not a product attribute.",
    verdictAfter:
      "If finalized as proposed, the update eliminates the addressable / required distinction, mandates encryption of ePHI, and forces MFA on every system touching PHI.",
    plain: {
      what: "Federal protection for electronic Protected Health Information. The Security Rule has been in force since 2003. A major proposed update is pending.",
      who: "Covered entities (providers, plans, clearinghouses) and business associates handling PHI. Any AI vendor that touches PHI is a business associate.",
      reqs: [
        "Risk analysis before deploying AI that touches PHI",
        "Business Associate Agreements for AI vendors handling PHI",
        "Audit logs retained for 6 years",
        "Workforce training on AI-specific risks",
      ],
      reqsExtra: [
        "PHI used in AI training is still PHI",
        "Information system activity review under §164.308(a)(1)(ii)(D)",
        "Proposed 2026 update: mandatory encryption at rest and in transit",
        "Proposed 2026 update: mandatory multi-factor authentication",
        "Proposed 2026 update: annual compliance audits with formal testing",
      ],
    },
    statute: {
      what: "Federal regulation under 45 CFR Parts 160, 162, 164. Sets standards for protecting electronic Protected Health Information (ePHI).",
      who: "Covered entities (healthcare providers, health plans, healthcare clearinghouses) and business associates handling PHI.",
      timeline: [
        ["2003", "HIPAA Security Rule in force (last major update)"],
        ["Dec 2023", "OCR guidance on HIPAA and AI"],
        ["Jan 6, 2025", "2026 Security Rule update: NPRM published"],
        ["~May 2026", "Final rule expected from HHS, with ~60 days to effective date and 180-day compliance grace period"],
      ],
      penalties: [
        ["Civil penalties", "Tiered, up to ~$2.1M per violation category per year (adjusted annually for inflation)"],
        ["Criminal penalties", "Available for willful violations"],
      ],
      reqs: [
        "Audit obligations (45 CFR §164.312(b)): record and examine activity in systems containing or using ePHI",
        "Information system activity review under §164.308(a)(1)(ii)(D)",
        "Retain audit logs for at least 6 years",
        "OCR Dec 2023 guidance: risk analysis before deploying AI that touches PHI",
        "Business Associate Agreements for AI vendors handling PHI",
        "Workforce training on AI-specific risks",
        "PHI used in AI training is still PHI",
      ],
      proposed: [
        "Eliminate the 'addressable' vs 'required' distinction (everything mandatory)",
        "Mandatory encryption of ePHI at rest and in transit",
        "Mandatory multi-factor authentication for systems accessing PHI",
        "Annual compliance audits with formal testing",
        "Network segmentation requirements",
        "Expanded incident response obligations",
      ],
      nuance: "There is no 'HIPAA-certified AI.' HIPAA compliance is operational, not a product attribute.",
    },
    citations: {
      ePHI: "Electronic Protected Health Information.",
      BAA: "Business Associate Agreement. Required between a covered entity and any third party that handles PHI on its behalf.",
      "§164.312(b)":
        "The Security Rule audit-controls standard. Requires hardware, software, and procedural mechanisms that record and examine activity in systems containing ePHI.",
    },
    exposure: 0,
    fineFlat: 2100000,
    tier: "II",
    tierLabel: "TIER II · CAPPED EXPOSURE",
    scopeTrigger:
      "Covered entity or business associate handling Protected Health Information; AI vendors handling PHI are business associates.",
    oneliner:
      "Tiered civil penalties up to approximately $2.1M per violation category per year, adjusted annually for inflation. Criminal penalties available for willful violations. The Security Rule has been in force since 2003; a major update is expected to finalize around May 2026.",
    footnote:
      "If finalized as proposed, the update eliminates the addressable / required distinction, mandates encryption of ePHI at rest and in transit, mandates MFA for systems accessing PHI, and requires annual compliance audits.",
    beforeDeployment: [
      { label: "Risk analysis before deploying AI that touches PHI (OCR Dec 2023 guidance)" },
      { label: "Business Associate Agreement signed with each AI vendor handling PHI" },
      { label: "Workforce training on AI-specific risks" },
    ],
    duringDeployment: [
      { label: "Audit logs retained for 6 years", ref: "§164.312(b)" },
      { label: "Information system activity review", ref: "§164.308(a)(1)(ii)(D)" },
      { label: "Treat PHI used in AI training as PHI" },
    ],
    scale: {
      kind: "tiers",
      rows: [
        { lbl: "Civil penalty cap (annual, per category)", val: "$2.1M", tier: "top", pct: 100 },
        { lbl: "Criminal exposure (willful)", val: "case-by-case", tier: "mid", pct: 60 },
      ],
    },
    source: { citation: "45 C.F.R. Parts 160, 162, 164", lastVerified: "2026-04-30" },
  },
  {
    id: "fda",
    num: "07",
    short: "FDA",
    label: "FDA",
    sub: "QMSR · PCCP · Lifecycle",
    targetDate: null,
    forceDate: "2026-02-02",
    fine: {
      big: "Recall + ban",
      sub: "warning letters, Form 483, import bans, criminal",
      per: "civil money penalties also available",
    },
    verdict:
      "QMSR took effect February 2, 2026. Over 1,350 AI-enabled medical devices have already been authorized. Enforcement is procedural, but the consequences include taking your product off the market.",
    verdictAfter:
      "PCCP lets manufacturers pre-authorize specified model modifications without filing a new submission for each change. The Lifecycle Management draft guidance is on track to finalize.",
    plain: {
      what: "US regulation of AI-enabled Software as a Medical Device (SaMD). QMSR replaces the old quality system regulation and aligns with ISO 13485.",
      who: "Manufacturers of AI-enabled medical devices that meet the FDA's SaMD definition.",
      reqs: [
        "Predetermined Change Control Plan for model updates",
        "Bias analysis and mitigation",
        "Post-market performance monitoring",
        "QMSR-aligned quality management system",
      ],
      reqsExtra: [
        "PCCP: Description of Modifications",
        "PCCP: Modification Protocol",
        "PCCP: Impact Assessment",
        "Model description, data lineage, performance tied to claims",
        "Human-AI workflow documentation",
      ],
    },
    statute: {
      what: "US regulation of AI-enabled Software as a Medical Device (SaMD) under FDA authority.",
      who: "Manufacturers of AI-enabled medical devices that meet the FDA's SaMD definition. As of early 2026, FDA has authorized over 1,350 AI-enabled medical devices.",
      timeline: [
        ["Dec 2024", "PCCP Final Guidance issued"],
        ["Jan 7, 2025", "AI-Enabled Device Software Functions: Lifecycle Management Draft Guidance issued"],
        ["Apr 7, 2025", "Comment period closed"],
        ["Aug 2025", "Joint PCCP Guiding Principles (FDA + Health Canada + UK MHRA) issued"],
        ["Feb 2, 2026", "FDA QMSR effective. Replaces 21 CFR Part 820, ISO 13485-aligned"],
      ],
      penalties: [
        ["Warning letters and Form 483 observations", ""],
        ["Product recalls", ""],
        ["Import bans", ""],
        ["Civil money penalties", ""],
        ["Criminal prosecution", "for willful violations"],
      ],
      reqs: [
        "PCCP: Description of Modifications",
        "PCCP: Modification Protocol",
        "PCCP: Impact Assessment",
        "Lifecycle Management: model description, data lineage, performance tied to claims",
        "Lifecycle Management: bias analysis and mitigation",
        "Lifecycle Management: human-AI workflow documentation",
        "Lifecycle Management: post-market performance monitoring",
        "Lifecycle Management: PCCP for post-market updates",
        "QMSR: ISO 13485-aligned quality management system",
      ],
    },
    citations: {
      SaMD:
        "Software as a Medical Device. Software intended to be used for medical purposes that performs those purposes without being part of a hardware medical device.",
      PCCP: "Predetermined Change Control Plan. Lets manufacturers pre-authorize specified AI model modifications.",
      QMSR: "Quality Management System Regulation. Replaces 21 CFR Part 820 and aligns with ISO 13485.",
    },
    exposure: 0,
    tier: "III",
    tierLabel: "TIER III · PROCEDURAL EXPOSURE",
    scopeTrigger: "AI-enabled medical device that meets the FDA's Software as a Medical Device (SaMD) definition.",
    oneliner:
      "QMSR took effect February 2, 2026, replacing 21 CFR Part 820 and aligning with ISO 13485. Enforcement consequences include warning letters, Form 483 observations, recalls, import bans, civil money penalties, and criminal prosecution. Over 1,350 AI-enabled medical devices have been authorized as of early 2026.",
    footnote:
      "PCCP (Predetermined Change Control Plan) lets manufacturers pre-authorize specified AI model modifications without filing a new submission. The Lifecycle Management draft guidance is on track to finalize.",
    beforeDeployment: [
      { label: "PCCP filed: Description of Modifications, Modification Protocol, Impact Assessment" },
      { label: "QMSR-aligned Quality Management System established" },
      { label: "Lifecycle: model description, data lineage, performance tied to claims" },
      { label: "Lifecycle: bias analysis and mitigation" },
      { label: "Lifecycle: human-AI workflow documentation" },
    ],
    duringDeployment: [
      { label: "Lifecycle: post-market performance monitoring" },
      { label: "Lifecycle: PCCP execution for model updates" },
    ],
    scale: {
      kind: "ladder",
      steps: [
        { label: "Form 483 observation", note: "Inspection finding requiring response" },
        { label: "Warning letter", note: "Public, formal" },
        { label: "Recall", note: "Product removed from market" },
        { label: "Import ban / detention", note: "Foreign-manufactured products blocked" },
        { label: "Civil money penalty", note: "Administrative fine" },
        { label: "Criminal prosecution", note: "Willful violations" },
      ],
    },
    source: {
      citation: "FDA QMSR (supersedes 21 CFR Part 820); PCCP Final Guidance (Dec 2024)",
      lastVerified: "2026-04-30",
    },
  },
];
