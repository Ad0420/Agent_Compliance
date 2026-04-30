// Content for the Regulations v2 dossier.
// Each entry has the headline triad (fine, deadline, verdict),
// a sales-mode short body, full-statute drawer content, and citations.

export const TODAY = new Date(2026, 3, 30); // April 30, 2026

export type DeadlineState = "live" | "soon" | "ongoing";

export type Fine = { big: string; sub: string; per?: string };

export type ThermoRow = { lbl: string; val: string; tier: "top" | "mid" | "low"; pct: number };

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
  thermo: ThermoRow[] | null;
  citations: Record<string, string>;
  exposure: number;
  fineFlat?: number;
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
    thermo: [
      { lbl: "Prohibited practices (Art. 5)", val: "€35M / 7%", tier: "top", pct: 100 },
      { lbl: "High-risk obligations", val: "€15M / 3%", tier: "mid", pct: 43 },
      { lbl: "Misleading information", val: "€7.5M / 1%", tier: "low", pct: 21 },
    ],
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
    thermo: null,
    citations: {
      ADAI: "Anti-Discrimination in AI Law. Common nickname for Colorado SB 24-205.",
      "Consequential decision":
        "A decision with material legal or similarly significant effects on a consumer, including offers of credit, employment, insurance, healthcare, or housing.",
    },
    exposure: 0,
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
    thermo: null,
    citations: {
      TRAIGA: "Texas Responsible AI Governance Act. The shipped version of HB 149.",
      "Affirmative defense": "Compliance with NIST AI RMF can be raised as a defense if enforcement is brought.",
    },
    exposure: 0,
    fineFlat: 200000,
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
    thermo: [
      { lbl: "SB 942 daily violation", val: "$5,000 / day", tier: "top", pct: 100 },
      { lbl: "AB 316 autonomy defense", val: "case-by-case", tier: "mid", pct: 50 },
      { lbl: "AB 2013 training-data", val: "civil action", tier: "low", pct: 25 },
    ],
    citations: {
      CAITA: "California AI Transparency Act. SB 942.",
      "AB 853":
        "Signed October 13, 2025. Pushed CAITA to Aug 2, 2026 and added 2027/2028 obligations for large platforms and capture devices.",
      "Manifest disclosure": "A visible label on the AI-generated content (e.g. a watermark or notice).",
      "Latent disclosure": "Embedded metadata, technically permanent or extraordinarily difficult to remove.",
    },
    exposure: 0.005,
    fineFlat: 5000 * 365,
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
    thermo: null,
    citations: {
      "Rule 3110":
        "FINRA's supervision rule. Member firms must establish and maintain a system to supervise the activities of associated persons.",
      "Notice 24-09": "Issued June 27, 2024. Confirms existing FINRA rules apply to AI; does not create new requirements.",
    },
    exposure: 0,
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
    thermo: [
      { lbl: "Civil penalty cap (annual, per category)", val: "$2.1M", tier: "top", pct: 100 },
      { lbl: "Criminal exposure (willful)", val: "case", tier: "mid", pct: 60 },
    ],
    citations: {
      ePHI: "Electronic Protected Health Information.",
      BAA: "Business Associate Agreement. Required between a covered entity and any third party that handles PHI on its behalf.",
      "§164.312(b)":
        "The Security Rule audit-controls standard. Requires hardware, software, and procedural mechanisms that record and examine activity in systems containing ePHI.",
    },
    exposure: 0,
    fineFlat: 2100000,
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
    thermo: null,
    citations: {
      SaMD:
        "Software as a Medical Device. Software intended to be used for medical purposes that performs those purposes without being part of a hardware medical device.",
      PCCP: "Predetermined Change Control Plan. Lets manufacturers pre-authorize specified AI model modifications.",
      QMSR: "Quality Management System Regulation. Replaces 21 CFR Part 820 and aligns with ISO 13485.",
    },
    exposure: 0,
  },
];
