/**
 * TriageGuard look book.
 *
 * Single-page style guide that demonstrates every primitive in
 * `components/ui/` and `components/brand/`. The Wave 2 view-layer agent
 * (and the founder, for QA) opens this at http://localhost:3002 to verify
 * the design system before composing real product pages.
 *
 * Sections:
 *   1. Brand — wordmark sizes, glyph sizes, palette swatches
 *   2. Typography — display + body type scale
 *   3. Buttons — variants × sizes (incl. escalate + disabled)
 *   4. Badges — variants × sizes
 *   5. Risk pills — all four tiers + compact + custom labels
 *   6. Status dots — all four states
 *   7. Cards — elevations + tones + a realistic triage case
 *   8. Inputs — text input, textarea
 *   9. Topbar — the real header (rendered above the page)
 *  10. Session pipeline — vertical step component, all four states
 */

import { Topbar } from "@/components/ui/topbar";
import { Wordmark } from "@/components/brand/Wordmark";
import { Glyph } from "@/components/brand/Glyph";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RiskPill } from "@/components/ui/risk-pill";
import { StatusDot } from "@/components/ui/status-dot";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SessionStep } from "@/components/ui/session-step";

export default function LookBook() {
  return (
    <div className="min-h-screen bg-[var(--paper)]">
      <Topbar
        signedInAs={{
          name: "Nurse Rivera",
          role: "RN",
          license: "CA-RN-7740291",
        }}
        centerSlot={
          <StatusDot status="running" label="Triage queue · 12 cases waiting" />
        }
      />

      <main className="mx-auto max-w-7xl px-6 py-12">
        {/* Hero */}
        <section className="case-grid rounded-2xl bg-[var(--paper-2)] px-10 py-14 mb-14 ring-1 ring-[var(--hairline)]">
          <Badge variant="teal" size="sm" withDot className="mb-5">
            TriageGuard design system v0.1
          </Badge>
          <h1
            className="font-serif text-5xl font-normal leading-[1.05] text-[var(--ink)] max-w-3xl"
            style={{ letterSpacing: "-0.02em" }}
          >
            AI triage for the telehealth front door.
          </h1>
          <p className="mt-5 max-w-2xl font-sans text-base text-[var(--ink-2)] leading-relaxed">
            Every component on this page is a primitive in the TriageGuard
            library. Pages are composed on top of these — never restyle the
            building blocks.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg">
              Open queue
            </Button>
            <Button variant="secondary" size="lg">
              Review pending case
            </Button>
            <Button variant="escalate" size="lg">
              Escalate to ER
            </Button>
          </div>
        </section>

        {/* Brand */}
        <Section
          n="01"
          title="Brand"
          subtitle="Wordmark and glyph at every supported size."
        >
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Wordmark</CardTitle>
                <CardDescription>
                  Glyph + DM Serif lockup. Use the smallest size that reads
                  cleanly.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-7">
                <div className="flex items-center gap-3">
                  <Wordmark size="sm" />
                  <Caption>24px</Caption>
                </div>
                <div className="flex items-center gap-3">
                  <Wordmark size="md" />
                  <Caption>32px</Caption>
                </div>
                <div className="flex items-center gap-3">
                  <Wordmark size="lg" />
                  <Caption>40px</Caption>
                </div>
                <div className="flex items-center gap-3">
                  <Wordmark size="xl" />
                  <Caption>64px</Caption>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Glyph</CardTitle>
                <CardDescription>
                  Stethoscope-pulse mark. Standalone use — favicon, app icon,
                  tight placements.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-6">
                <div className="flex items-center gap-6">
                  <Glyph size={24} />
                  <Glyph size={32} />
                  <Glyph size={48} />
                  <Glyph size={64} />
                </div>
                <div className="flex items-center gap-4">
                  <Glyph size={48} tone="primary" />
                  <Glyph size={48} tone="ink" />
                  <div className="bg-[var(--teal)] rounded-lg p-2">
                    <Glyph size={48} tone="white" />
                  </div>
                </div>
                <Caption>
                  Three tones: primary (teal mark on white tile), ink (for
                  paper-on-paper), white (for filled teal surfaces).
                </Caption>
              </CardContent>
            </Card>
          </div>

          {/* Palette */}
          <div className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Palette</CardTitle>
                <CardDescription>
                  Cool ivory, deep teal primary, crimson reserved for
                  escalation. No emerald, no cobalt — those belong to Vera and
                  ScribeMD. Contrast ratios in{" "}
                  <code className="font-mono text-xs px-1 py-0.5 rounded bg-[var(--paper-2)]">
                    LOOK.md
                  </code>
                  .
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                  <Swatch label="paper" hex="#FBF8F1" />
                  <Swatch label="paper-2" hex="#F4EFE4" />
                  <Swatch label="ink" hex="#0E1A1A" textLight />
                  <Swatch label="teal" hex="#0F766E" textLight />
                  <Swatch label="teal-soft" hex="#CDE8E4" />
                  <Swatch label="teal-deep" hex="#0B5650" textLight />
                  <Swatch label="crimson" hex="#B91C1C" textLight />
                  <Swatch label="crimson-soft" hex="#FBE0E0" />
                  <Swatch label="amber" hex="#92400E" textLight />
                  <Swatch label="amber-soft" hex="#FCE7C5" />
                  <Swatch label="moss" hex="#2F6A3D" textLight />
                  <Swatch label="taupe" hex="#6E4E2E" textLight />
                </div>
              </CardContent>
            </Card>
          </div>
        </Section>

        {/* Typography */}
        <Section
          n="02"
          title="Typography"
          subtitle="DM Serif Display for display, Inter for UI, JetBrains Mono for IDs."
        >
          <Card>
            <CardContent className="flex flex-col gap-6 pt-6">
              <div>
                <Caption>Display · serif · 48 / -2</Caption>
                <p
                  className="font-serif text-5xl font-normal text-[var(--ink)]"
                  style={{ letterSpacing: "-0.02em" }}
                >
                  Triage with two-second confidence.
                </p>
              </div>
              <div>
                <Caption>H1 · serif · 30 / -1.5</Caption>
                <p
                  className="font-serif text-3xl font-normal text-[var(--ink)]"
                  style={{ letterSpacing: "-0.015em" }}
                >
                  Case 24-04-30-0142
                </p>
              </div>
              <div>
                <Caption>H2 · serif · 20</Caption>
                <p className="font-serif text-xl font-normal text-[var(--ink)]">
                  Patient · Symptoms · AI level · Decision
                </p>
              </div>
              <div>
                <Caption>Body · sans · 16</Caption>
                <p className="font-sans text-base text-[var(--ink)] leading-relaxed max-w-2xl">
                  47-year-old female reports sudden-onset right-sided weakness
                  and slurred speech that began 18 minutes ago. AI proposes
                  self-care; held for nurse review (red-flag terms).
                </p>
              </div>
              <div>
                <Caption>Body small · sans · 14</Caption>
                <p className="font-sans text-sm text-[var(--ink-2)] max-w-2xl">
                  Use this size for queue rows, secondary metadata, and the
                  body of cards.
                </p>
              </div>
              <div>
                <Caption>Mono · 13</Caption>
                <p className="font-mono text-sm text-[var(--ink-2)]">
                  case_01HM4C2K9P · CA-RN-7740291 · dec_01HM4C2K9R7N
                </p>
              </div>
            </CardContent>
          </Card>
        </Section>

        {/* Buttons */}
        <Section
          n="03"
          title="Buttons"
          subtitle="Five variants. Pill-rounded, soft shadow, teal focus ring. Escalate is the signature CTA."
        >
          <Card>
            <CardContent className="flex flex-col gap-6 pt-6">
              <Row label="Primary">
                <Button variant="primary" size="sm">Open case</Button>
                <Button variant="primary" size="md">Open case</Button>
                <Button variant="primary" size="lg">Open case</Button>
              </Row>
              <Row label="Secondary">
                <Button variant="secondary" size="sm">Skip for now</Button>
                <Button variant="secondary" size="md">Skip for now</Button>
                <Button variant="secondary" size="lg">Skip for now</Button>
              </Row>
              <Row label="Ghost">
                <Button variant="ghost" size="sm">Cancel</Button>
                <Button variant="ghost" size="md">Cancel</Button>
                <Button variant="ghost" size="lg">Cancel</Button>
              </Row>
              <Row label="Destructive">
                <Button variant="destructive" size="sm">Reject decision</Button>
                <Button variant="destructive" size="md">Reject decision</Button>
                <Button variant="destructive" size="lg">Reject decision</Button>
              </Row>
              <Row label="Escalate">
                <Button variant="escalate" size="sm">Escalate to ER</Button>
                <Button variant="escalate" size="md">Escalate to ER</Button>
                <Button variant="escalate" size="lg">Escalate to ER</Button>
              </Row>
              <Row label="Disabled">
                <Button variant="primary" disabled>Open case</Button>
                <Button variant="secondary" disabled>Skip for now</Button>
                <Button variant="escalate" disabled>Escalate to ER</Button>
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Badges */}
        <Section
          n="04"
          title="Badges"
          subtitle="Pill chips for status, counts, and meta labels. Optional leading dot."
        >
          <Card>
            <CardContent className="flex flex-col gap-5 pt-6">
              <Row label="Variants">
                <Badge variant="neutral">Self-care</Badge>
                <Badge variant="teal">Virtual visit</Badge>
                <Badge variant="amber">Urgent care</Badge>
                <Badge variant="crimson">ER</Badge>
                <Badge variant="moss">Recorded</Badge>
                <Badge variant="outline">Archived</Badge>
              </Row>
              <Row label="With dot">
                <Badge variant="teal" withDot>Awaiting nurse</Badge>
                <Badge variant="amber" withDot>Held for review</Badge>
                <Badge variant="crimson" withDot>Escalated</Badge>
                <Badge variant="moss" withDot>Approved</Badge>
              </Row>
              <Row label="Sizes">
                <Badge variant="teal" size="sm">sm</Badge>
                <Badge variant="teal" size="md">md</Badge>
                <Badge variant="teal" size="lg">lg</Badge>
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Risk Pills */}
        <Section
          n="05"
          title="Risk pills"
          subtitle="Four tiers. Reach for these when a nurse needs to read clinical risk at a glance."
        >
          <Card>
            <CardContent className="flex flex-col gap-5 pt-6">
              <Row label="Default">
                <RiskPill tier="low" />
                <RiskPill tier="medium" />
                <RiskPill tier="high" />
                <RiskPill tier="critical" />
              </Row>
              <Row label="Compact">
                <RiskPill tier="low" compact />
                <RiskPill tier="medium" compact />
                <RiskPill tier="high" compact />
                <RiskPill tier="critical" compact />
              </Row>
              <Row label="Custom label">
                <RiskPill tier="low" label="Routine" />
                <RiskPill tier="medium" label="Review needed" />
                <RiskPill tier="high" label="Red-flag terms" />
                <RiskPill tier="critical" label="Stroke pathway" />
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Status Dots */}
        <Section
          n="06"
          title="Status dots"
          subtitle="Live indicator for long-running operations. Active state pulses (decoration only — color and label always carry the meaning)."
        >
          <Card>
            <CardContent className="flex flex-col gap-5 pt-6">
              <Row label="States">
                <StatusDot status="running" />
                <StatusDot status="waiting" />
                <StatusDot status="committed" />
                <StatusDot status="error" />
              </Row>
              <Row label="Custom labels">
                <StatusDot status="running" label="Assessing symptoms" />
                <StatusDot status="waiting" label="Held for nurse review" />
                <StatusDot status="committed" label="Decision recorded" />
                <StatusDot status="error" label="Escalation failed" />
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Cards */}
        <Section
          n="07"
          title="Cards"
          subtitle="Hairline + soft shadow, rounded-xl. The TriageGuard case-file surface."
        >
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            <Card elevation="flat">
              <CardHeader>
                <CardTitle>Flat</CardTitle>
                <CardDescription>
                  Hairline only, no shadow. Nested within other cards.
                </CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="sm">
              <CardHeader>
                <CardTitle>Small</CardTitle>
                <CardDescription>
                  Subtle lift. Queue rows, sidebar items.
                </CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="md">
              <CardHeader>
                <CardTitle>Medium</CardTitle>
                <CardDescription>
                  Default workhorse — most surfaces.
                </CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="lg">
              <CardHeader>
                <CardTitle>Large</CardTitle>
                <CardDescription>
                  Hero surfaces, modals, the active case card.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
          <div className="mt-6 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {(["teal", "amber", "crimson", "moss"] as const).map((t) => (
              <Card key={t} tone={t}>
                <CardHeader>
                  <CardTitle className="capitalize">{t} ring</CardTitle>
                  <CardDescription>
                    Use a tone ring when the card surfaces a status — e.g. a
                    case held for review.
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
          </div>

          {/* Realistic example */}
          <div className="mt-6">
            <Card elevation="lg" tone="crimson">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Case 24-04-30-0142</CardTitle>
                    <CardDescription>
                      47F · sudden-onset right-sided weakness, slurred speech,
                      18 min onset
                    </CardDescription>
                  </div>
                  <RiskPill tier="critical" label="Stroke pathway" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="crimson" withDot>Held for review</Badge>
                  <Badge variant="amber">Red-flag: hemiparesis, dysarthria</Badge>
                  <Badge variant="outline">AI proposed: self-care</Badge>
                  <span className="font-mono text-xs text-[var(--ink-3)] ml-auto">
                    case_01HM4C2K9P
                  </span>
                </div>
              </CardContent>
              <CardFooter>
                <Button variant="escalate">Escalate to ER</Button>
                <Button variant="secondary">Confirm AI level</Button>
                <Button variant="ghost">Hold for second opinion</Button>
              </CardFooter>
            </Card>
          </div>
        </Section>

        {/* Forms */}
        <Section
          n="08"
          title="Inputs"
          subtitle="Inset shadow, teal focus ring. Keyboard-first."
        >
          <Card>
            <CardContent className="grid gap-5 pt-6 md:grid-cols-2">
              <Field label="Patient ID">
                <Input placeholder="pt_01HM4C2K9P" />
              </Field>
              <Field label="Nurse license">
                <Input defaultValue="CA-RN-7740291" />
              </Field>
              <Field label="Symptom history" className="md:col-span-2">
                <Textarea
                  rows={4}
                  defaultValue="47F reports sudden-onset right-sided weakness + slurred speech beginning ~18 min ago. Denies headache. No prior stroke. On warfarin for AFib (INR last week 2.4)."
                />
              </Field>
              <Field label="Disabled" className="md:col-span-2">
                <Input disabled placeholder="Read-only field" />
              </Field>
            </CardContent>
          </Card>
        </Section>

        {/* Session Pipeline */}
        <Section
          n="09"
          title="Session pipeline"
          subtitle="Vertical timeline of the triage flow. All four states demonstrated in narrative order."
        >
          <Card elevation="lg">
            <CardHeader>
              <CardTitle>Live triage · Case 24-04-30-0142</CardTitle>
              <CardDescription>
                Submitted 4 min ago · 47F, possible stroke
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="pt-2">
                <SessionStep
                  state="done"
                  label="Patient symptoms captured"
                  sublabel="Intake form · 4 min ago"
                  payload={
                    <span>
                      &ldquo;Right side numb, words coming out wrong since 18
                      min ago. Scared.&rdquo;
                    </span>
                  }
                />
                <SessionStep
                  state="done"
                  label="AI assessed and proposed level"
                  sublabel="Anthropic claude-sonnet-4-6 · 980 tokens"
                  payload={
                    <div className="flex items-center gap-2">
                      <span>AI proposed:</span>
                      <Badge variant="neutral" withDot>
                        Self-care
                      </Badge>
                    </div>
                  }
                />
                <SessionStep
                  state="active"
                  label="Red-flag screen"
                  sublabel="Detecting clinical red-flag terms before release"
                  payload={
                    <div className="flex flex-col gap-1.5">
                      <span className="font-medium text-[var(--ink)]">
                        Red-flag terms detected:
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        <RiskPill tier="high" compact label="hemiparesis" />
                        <RiskPill tier="high" compact label="dysarthria" />
                        <RiskPill tier="critical" compact label="acute onset" />
                      </div>
                    </div>
                  }
                />
                <SessionStep
                  state="blocked"
                  label="Awaiting your triage decision"
                  sublabel="No-escalation output blocked by policy — needs nurse confirmation"
                  payload={
                    <span>
                      Confirm AI level (self-care), or escalate to virtual
                      visit / urgent / ER. Patient never sees the AI&rsquo;s
                      original recommendation until you decide.
                    </span>
                  }
                />
                <SessionStep
                  state="idle"
                  label="Release decision to patient"
                  sublabel="Patient sees the (possibly escalated) recommendation"
                  isLast
                />
              </div>
            </CardContent>
          </Card>
        </Section>

        <footer className="mt-16 pt-10 border-t border-[var(--hairline)] text-center">
          <Wordmark size="sm" className="opacity-70" />
          <p className="mt-3 font-sans text-xs text-[var(--ink-3)]">
            TriageGuard, Inc. · Demo bench
          </p>
        </footer>
      </main>
    </div>
  );
}

/* ---------- helpers (kept local to the look book) ---------- */

function Section({
  n,
  title,
  subtitle,
  children,
}: {
  n: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-14">
      <div className="mb-5 flex items-baseline gap-3">
        <span className="font-mono text-xs text-[var(--ink-3)]">{n}</span>
        <h2
          className="font-serif text-2xl font-normal text-[var(--ink)]"
          style={{ letterSpacing: "-0.015em" }}
        >
          {title}
        </h2>
      </div>
      {subtitle && (
        <p className="mb-5 max-w-2xl font-sans text-sm text-[var(--ink-3)]">
          {subtitle}
        </p>
      )}
      {children}
    </section>
  );
}

function Caption({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
      {children}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)] w-24 shrink-0">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <span className="font-sans text-xs font-medium text-[var(--ink-2)]">
        {label}
      </span>
      {children}
    </label>
  );
}

function Swatch({
  label,
  hex,
  textLight,
}: {
  label: string;
  hex: string;
  textLight?: boolean;
}) {
  return (
    <div className="flex flex-col">
      <div
        className="h-16 rounded-lg ring-1 ring-inset ring-[var(--hairline)] flex items-end p-2"
        style={{
          backgroundColor: hex,
          color: textLight ? "rgba(255,255,255,0.92)" : "var(--ink)",
        }}
      >
        <span className="font-mono text-[10px]">{hex}</span>
      </div>
      <span className="mt-1.5 font-sans text-xs font-medium text-[var(--ink-2)]">
        {label}
      </span>
    </div>
  );
}
