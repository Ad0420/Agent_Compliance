import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Scale,
  Globe,
  MapPin,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Eye,
  Users,
  Clock,
  ShieldCheck,
  Hash,
  Database,
} from "lucide-react";

const EU_REQUIREMENTS = [
  {
    article: "Art. 9",
    title: "Risk management system",
    description: "Establish and maintain a risk management system throughout the AI system lifecycle.",
  },
  {
    article: "Art. 12",
    title: "Record-keeping",
    description: "High-risk AI systems must automatically log events to enable traceability of decisions.",
  },
  {
    article: "Art. 13",
    title: "Transparency",
    description: "Ensure deployers have sufficient information to understand capabilities and limitations.",
  },
  {
    article: "Art. 14",
    title: "Human oversight",
    description: "Enable natural persons to effectively oversee the AI system during operation.",
  },
  {
    article: "Art. 86",
    title: "Right to explanation",
    description: "Individuals have the right to obtain an explanation of a decision made by a high-risk AI system.",
  },
];

const COLORADO_REQUIREMENTS = [
  {
    req: "Risk management",
    description: "Implement a risk management program to identify and mitigate algorithmic discrimination.",
  },
  {
    req: "Impact assessments",
    description: "Conduct algorithmic impact assessments before deployment and annually thereafter.",
  },
  {
    req: "Consumer disclosure",
    description: "Notify consumers when high-risk AI systems are used in consequential decisions.",
  },
  {
    req: "Right to appeal",
    description: "Consumers can appeal decisions and request human review of automated decisions.",
  },
  {
    req: "Self-reporting obligation",
    description: "Deployers must notify the Colorado AG within 90 days if algorithmic discrimination is detected.",
  },
];

const VERA_COVERAGE = [
  {
    requirement: "Tamper-evident audit trail",
    laws: ["EU AI Act Art. 12", "Colorado SB 24-205"],
    how: "Every AI action is recorded, SHA-256 hashed, and chained — no record can be altered without breaking the chain.",
    icon: Hash,
  },
  {
    requirement: "Right to explanation",
    laws: ["EU AI Act Art. 86", "Colorado SB 24-205"],
    how: "Query all decisions about any individual by data_subject_id in milliseconds. Full decision history on demand.",
    icon: Users,
  },
  {
    requirement: "Independent verification",
    laws: ["EU AI Act Art. 12", "EU AI Act Art. 9"],
    how: "KMS-signed checkpoints with Merkle roots allow third-party verification without accessing raw data.",
    icon: ShieldCheck,
  },
  {
    requirement: "Agent & model tracking",
    laws: ["EU AI Act Art. 13", "Colorado SB 24-205"],
    how: "Every record captures agent name, version, model ID, and framework. Full provenance for every decision.",
    icon: Database,
  },
  {
    requirement: "Decision documentation",
    laws: ["EU AI Act Art. 12", "EU AI Act Art. 14"],
    how: "Input data, output data, reasoning, and duration stored with each record. Complete decision context preserved.",
    icon: FileText,
  },
  {
    requirement: "Real-time monitoring",
    laws: ["EU AI Act Art. 9", "Colorado SB 24-205"],
    how: "Dashboard shows live action volume, chain integrity status, and agent activity across your entire AI fleet.",
    icon: Eye,
  },
];

const TIMELINE = [
  { date: "May 2024", event: "Colorado SB 24-205 signed into law", region: "US" },
  { date: "Aug 2024", event: "EU AI Act enters into force", region: "EU" },
  { date: "June 2026", event: "Colorado AI Act takes effect", region: "US", highlight: true },
  { date: "Aug 2026", event: "EU AI Act obligations apply to high-risk AI", region: "EU", highlight: true },
  { date: "2026–2027", event: "Canada AIDA, Brazil AI Bill expected to pass", region: "Global" },
];

const HIGH_RISK_CATEGORIES = [
  "Credit scoring & loan decisions",
  "Employment screening & HR decisions",
  "Education & academic assessment",
  "Healthcare diagnosis & treatment",
  "Law enforcement & border control",
  "Essential public services",
  "Insurance underwriting",
  "Housing & rental decisions",
];

export default function CompliancePage() {
  return (
    <div className="space-y-8 max-w-5xl">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Compliance Guide</h1>
        <p className="text-sm text-muted-foreground mt-1">
          What the laws require, what&apos;s at stake, and how Vera keeps you covered.
        </p>
      </div>

      {/* Alert banner */}
      <Card className="border-amber-500/40 bg-amber-500/5">
        <CardContent className="flex items-start gap-4 p-5">
          <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-amber-500">Two major AI regulations take effect in 2026</p>
            <p className="text-sm text-muted-foreground mt-1">
              The EU AI Act and Colorado AI Act both impose significant obligations on companies using AI for
              high-stakes decisions — including mandatory audit trails, right-to-explanation requirements, and
              penalties reaching into the tens of millions. The compliance window is closing.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Law cards */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* EU AI Act */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Globe className="h-5 w-5 text-blue-400" />
                <CardTitle className="text-base">EU AI Act</CardTitle>
              </div>
              <Badge variant="outline" className="text-xs border-blue-500/40 text-blue-400">
                Regulation (EU) 2024/1689
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              The world&apos;s first comprehensive AI law. Applies to any company whose AI systems affect people in
              the EU — regardless of where the company is headquartered.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Key dates</p>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Entered into force</span>
                  <span className="font-mono text-xs">Aug 1, 2024</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">High-risk obligations apply</span>
                  <span className="font-mono text-xs font-semibold">Aug 2, 2026</span>
                </div>
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Penalties</p>
              <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm">
                <p className="font-semibold text-destructive">Up to €35,000,000</p>
                <p className="text-xs text-muted-foreground">or 7% of global annual turnover, whichever is higher</p>
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Key obligations
              </p>
              <div className="space-y-2">
                {EU_REQUIREMENTS.map((r) => (
                  <div key={r.article} className="flex gap-2">
                    <Badge variant="secondary" className="text-[10px] h-5 shrink-0 font-mono mt-0.5">
                      {r.article}
                    </Badge>
                    <div>
                      <p className="text-xs font-medium">{r.title}</p>
                      <p className="text-xs text-muted-foreground">{r.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Colorado AI Act */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MapPin className="h-5 w-5 text-orange-400" />
                <CardTitle className="text-base">Colorado AI Act</CardTitle>
              </div>
              <Badge variant="outline" className="text-xs border-orange-500/40 text-orange-400">
                SB 24-205
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              The first US state AI law targeting &quot;consequential decisions&quot;. Sets the template other states are
              expected to follow — similar bills are active in 15+ states.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Key dates</p>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Signed into law</span>
                  <span className="font-mono text-xs">May 17, 2024</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Takes effect</span>
                  <span className="font-mono text-xs font-semibold">June 30, 2026</span>
                </div>
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Consequential decision categories
              </p>
              <div className="flex flex-wrap gap-1">
                {HIGH_RISK_CATEGORIES.map((cat) => (
                  <Badge key={cat} variant="secondary" className="text-[10px]">
                    {cat}
                  </Badge>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Key obligations
              </p>
              <div className="space-y-2">
                {COLORADO_REQUIREMENTS.map((r) => (
                  <div key={r.req} className="flex gap-2">
                    <Scale className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-medium">{r.req}</p>
                      <p className="text-xs text-muted-foreground">{r.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Timeline */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">Regulatory Timeline</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {TIMELINE.map((item, i) => (
              <div key={i} className="flex items-start gap-4">
                <div className="w-24 shrink-0">
                  <span className={`text-xs font-mono ${item.highlight ? "font-bold text-foreground" : "text-muted-foreground"}`}>
                    {item.date}
                  </span>
                </div>
                <div className="flex items-center gap-2 flex-1">
                  <div className={`h-1.5 w-1.5 rounded-full shrink-0 ${item.highlight ? "bg-amber-500" : "bg-muted-foreground/40"}`} />
                  <p className={`text-sm ${item.highlight ? "font-medium" : "text-muted-foreground"}`}>
                    {item.event}
                  </p>
                  <Badge
                    variant="outline"
                    className={`text-[10px] ml-auto shrink-0 ${
                      item.region === "EU"
                        ? "border-blue-500/40 text-blue-400"
                        : item.region === "US"
                        ? "border-orange-500/40 text-orange-400"
                        : "border-muted-foreground/40 text-muted-foreground"
                    }`}
                  >
                    {item.region}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* How Vera covers it */}
      <div>
        <h2 className="text-lg font-semibold mb-1">How Vera Covers It</h2>
        <p className="text-sm text-muted-foreground mb-4">
          Every requirement maps to a specific Vera feature — not a checkbox exercise.
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {VERA_COVERAGE.map((item) => (
            <Card key={item.requirement}>
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-accent p-2 shrink-0">
                    <item.icon className="h-4 w-4 text-accent-foreground" />
                  </div>
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium">{item.requirement}</p>
                      <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0 mt-0.5" />
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {item.laws.map((law) => (
                        <Badge key={law} variant="secondary" className="text-[10px]">
                          {law}
                        </Badge>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">{item.how}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* What's coming */}
      <Card className="border-muted">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What&apos;s Coming</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            The EU AI Act and Colorado AI Act are the opening wave. Regulators globally are watching closely.
          </p>
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            {[
              { region: "Canada", detail: "AIDA (Artificial Intelligence and Data Act) — pending parliament vote. Similar risk-based framework to EU AI Act." },
              { region: "United Kingdom", detail: "Sector-specific AI regulation actively developing. ICO guidance expanding to cover automated decision-making beyond GDPR." },
              { region: "Brazil", detail: "PL 2338/2023 — AI Bill progressing through legislature. Mirrors EU AI Act risk-based approach." },
              { region: "US Federal", detail: "Algorithmic Accountability Act reintroduced. Executive Order on AI already requires impact assessments for federal AI use." },
            ].map((item) => (
              <div key={item.region} className="rounded-md border border-border p-3">
                <p className="font-medium text-xs mb-1">{item.region}</p>
                <p className="text-xs text-muted-foreground">{item.detail}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
