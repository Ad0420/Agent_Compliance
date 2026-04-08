"use client";

import { useState } from "react";
import { Globe, MapPin, TrendingUp } from "lucide-react";

const TABS = [
  { id: "eu", label: "EU AI Act", icon: Globe },
  { id: "colorado", label: "Colorado AI Act", icon: MapPin },
  { id: "coming", label: "What's Coming", icon: TrendingUp },
];

const CONTENT = {
  eu: {
    badge: "Regulation (EU) 2024/1689",
    badgeColor: "text-blue-400 border-blue-500/30 bg-blue-500/5",
    effectiveDate: "Aug 2, 2026",
    penalty: "Prohibited AI (Art. 5): up to €35M or 7% revenue · High-risk AI: up to €15M or 3% revenue",
    penaltyColor: "text-red-400",
    intro:
      "The world's first comprehensive AI law. Applies to any company whose AI affects people in the EU — regardless of where you're headquartered.",
    requirements: [
      {
        label: "Art. 9 — Risk management system",
        detail: "Establish, implement, document and maintain a risk management system throughout the entire AI lifecycle.",
      },
      {
        label: "Art. 12 — Record-keeping",
        detail: "High-risk AI systems must automatically log events throughout their lifecycle to enable traceability of decisions. Deployers must retain logs for at least six months.",
      },
      {
        label: "Art. 13 — Transparency",
        detail: "Deployers must have sufficient information to understand and oversee the system.",
      },
      {
        label: "Art. 14 — Human oversight",
        detail: "Enable humans to monitor, intervene, and override AI decisions at any time.",
      },
      {
        label: "Art. 86 — Right to explanation",
        detail: "Individuals can request a meaningful explanation of any AI decision affecting them.",
      },
    ],
    highRisk: [
      "Credit scoring & loan decisions",
      "Employment & HR screening",
      "Education & academic assessment",
      "Healthcare diagnosis",
      "Law enforcement",
      "Border control & biometrics",
    ],
    accentColor: "blue",
  },
  colorado: {
    badge: "SB 24-205 · Signed May 17, 2024",
    badgeColor: "text-orange-400 border-orange-500/30 bg-orange-500/5",
    effectiveDate: "June 30, 2026",
    penalty: "Colorado AG enforcement only — no private right of action. Up to $20,000 per violation.",
    penaltyColor: "text-orange-400",
    intro:
      "The first comprehensive US state AI consumer protection law, targeting 'consequential decisions'. Multiple states are actively enacting AI legislation — Colorado sets an early benchmark.",
    requirements: [
      {
        label: "Risk management program",
        detail: "Developers and deployers must implement a program to identify and mitigate algorithmic discrimination.",
      },
      {
        label: "Impact assessments",
        detail: "Annual algorithmic impact assessments required, covering purpose, data used, known discrimination risks, and post-deployment monitoring.",
      },
      {
        label: "Consumer disclosure",
        detail: "Notify consumers when high-risk AI is used in a consequential decision and inform them of their rights.",
      },
      {
        label: "Right to appeal",
        detail: "Consumers can appeal consequential decisions and request human review where technically feasible.",
      },
      {
        label: "Self-reporting obligation",
        detail: "Deployers must notify the Colorado AG within 90 days if algorithmic discrimination is detected.",
      },
    ],
    highRisk: [
      "Credit & lending",
      "Employment decisions",
      "Healthcare & diagnosis",
      "Housing & rentals",
      "Education access",
      "Insurance",
      "Legal services",
      "Essential government services",
    ],
    accentColor: "orange",
  },
  coming: null,
};

const COMING_SOON = [
  {
    region: "Canada",
    law: "AIDA — Artificial Intelligence and Data Act",
    status: "Pending parliament vote",
    detail: "Risk-based framework closely mirroring the EU AI Act. Mandatory audit and incident reporting.",
    color: "blue",
  },
  {
    region: "United Kingdom",
    law: "Sector-specific AI regulation",
    status: "Actively developing",
    detail: "ICO guidance expanding automated decision-making rules beyond GDPR. Sector regulators publishing binding codes.",
    color: "purple",
  },
  {
    region: "Brazil",
    law: "PL 2338/2023 — Brazilian AI Bill",
    status: "Moving through legislature",
    detail: "Mirrors EU AI Act risk-based approach. Consequential decisions require human oversight and audit trails.",
    color: "green",
  },
  {
    region: "US Federal",
    law: "Algorithmic Accountability Act",
    status: "Reintroduced in Congress",
    detail: "Requires impact assessments for automated decision systems. Executive Order on AI already mandates federal agency compliance.",
    color: "amber",
  },
  {
    region: "US States",
    law: "State-level AI legislation",
    status: "Rapidly expanding",
    detail: "45 states introduced AI-related bills in 2025, with 145 enacted into law. Most address specific use cases — biometrics, deepfakes, hiring — rather than comprehensive frameworks like Colorado's.",
    color: "red",
  },
];

export function RegulationsTabs() {
  const [active, setActive] = useState("eu");
  const content = CONTENT[active as keyof typeof CONTENT];

  return (
    <div>
      {/* Tab bar */}
      <div className="flex gap-1 rounded-lg border border-border/60 bg-card/60 p-1 mb-8">
        {TABS.map((tab) => {
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium transition-all duration-150 ${
                isActive
                  ? "bg-background text-foreground shadow-sm border border-border/60"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {active === "coming" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground mb-5">
            The EU AI Act and Colorado AI Act are the opening wave. Regulators globally are watching closely —
            <span className="text-foreground font-medium"> Vera is built to cover all of them.</span>
          </p>
          {COMING_SOON.map((item) => (
            <div
              key={item.region}
              className="flex items-start gap-4 rounded-lg border border-border/60 bg-card/40 px-5 py-4"
            >
              <div className="min-w-[110px]">
                <p className="text-sm font-semibold">{item.region}</p>
                <span className="text-[10px] text-muted-foreground/60 font-mono">{item.status}</span>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-0.5">{item.law}</p>
                <p className="text-xs text-muted-foreground/70">{item.detail}</p>
              </div>
            </div>
          ))}
        </div>
      ) : content && content !== null ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-5">
          {/* Left: main info */}
          <div className="sm:col-span-3 space-y-5">
            <div className="flex items-center gap-3">
              <span className={`rounded-full border px-3 py-0.5 text-xs font-medium ${content.badgeColor}`}>
                {content.badge}
              </span>
              <span className="text-xs text-muted-foreground">
                Effective: <span className="font-semibold text-foreground">{content.effectiveDate}</span>
              </span>
            </div>
            <p className="text-sm text-muted-foreground">{content.intro}</p>

            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Key obligations</p>
              {content.requirements.map((req) => (
                <div key={req.label} className="rounded-lg border border-border/50 bg-card/40 px-4 py-3">
                  <p className="text-xs font-semibold mb-0.5">{req.label}</p>
                  <p className="text-xs text-muted-foreground">{req.detail}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Right: sidebar */}
          <div className="sm:col-span-2 space-y-5">
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">Penalty</p>
              <p className={`text-sm font-bold ${content.penaltyColor}`}>{content.penalty}</p>
            </div>

            <div className="rounded-lg border border-border/60 bg-card/40 px-4 py-4 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">High-risk categories</p>
              <div className="flex flex-wrap gap-1.5">
                {content.highRisk.map((cat) => (
                  <span
                    key={cat}
                    className="rounded-md border border-border/60 bg-accent/50 px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {cat}
                  </span>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border/60 bg-card/40 px-4 py-4 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">How Vera covers it</p>
              {[
                "Immutable audit trail for every AI action",
                "data_subject_id lookup for Art. 86 / right to explanation",
                "KMS-signed checkpoints for independent verification",
                "Agent + model tracking for full provenance",
              ].map((item) => (
                <div key={item} className="flex items-start gap-2">
                  <span className="text-green-400 text-xs mt-0.5 shrink-0">✓</span>
                  <p className="text-xs text-muted-foreground">{item}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
