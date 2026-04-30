/**
 * ScribeMD look book.
 *
 * Single-page style guide that demonstrates every primitive in
 * `components/ui/` and `components/brand/`. The Wave 2 agent (and you, for QA)
 * should open this at http://localhost:3001 to verify the design system before
 * composing real product pages.
 *
 * Sections:
 *   1. Brand — wordmark sizes, glyph sizes, palette swatches
 *   2. Typography — display + body type scale
 *   3. Buttons — variants × sizes
 *   4. Badges — variants × sizes
 *   5. Risk pills — all four tiers + compact
 *   6. Status dots — all four states
 *   7. Cards — elevations + tones
 *   8. Inputs — text input, textarea
 *   9. Topbar — the real header (rendered above the page)
 *  10. Encounter pipeline — vertical step component, all four states
 */

import { Topbar } from "@/components/ui/topbar";
import { Wordmark } from "@/components/brand/Wordmark";
import { Glyph } from "@/components/brand/Glyph";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RiskPill } from "@/components/ui/risk-pill";
import { StatusDot } from "@/components/ui/status-dot";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EncounterStep } from "@/components/ui/encounter-step";

export default function LookBook() {
  return (
    <div className="min-h-screen bg-[var(--paper)]">
      <Topbar
        signedInAs={{
          name: "Dr. Adams",
          credentials: "M.D.",
          npi: "1234567890",
        }}
        centerSlot={<StatusDot status="running" label="Encounter live · Room 4B" />}
      />

      <main className="mx-auto max-w-7xl px-6 py-12">
        {/* Hero */}
        <section className="paper-grain rounded-3xl bg-[var(--paper-2)] px-10 py-14 mb-14 ring-1 ring-[var(--hairline)]">
          <Badge variant="cobalt" size="sm" className="mb-5">
            ScribeMD design system v0.1
          </Badge>
          <h1
            className="font-serif text-5xl font-semibold leading-[1.05] text-[var(--ink)] max-w-3xl"
            style={{ letterSpacing: "-0.025em" }}
          >
            Ambient AI scribe for the modern hospital.
          </h1>
          <p className="mt-5 max-w-2xl font-sans text-base text-[var(--ink-2)] leading-relaxed">
            Every component on this page is a primitive in the ScribeMD library.
            Pages are composed on top of these — never restyle the building blocks.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg">Start a draft</Button>
            <Button variant="secondary" size="lg">Open last encounter</Button>
            <Button variant="ghost" size="lg">View settings</Button>
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
                <CardDescription>Glyph + serif lockup. Use the smallest size that reads cleanly.</CardDescription>
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
                <CardDescription>Standalone — favicon, app icon, tight placements.</CardDescription>
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
                  <div className="bg-[var(--cobalt)] rounded-xl p-2">
                    <Glyph size={48} tone="white" />
                  </div>
                </div>
                <Caption>
                  Three tones: primary (default), ink (for cobalt backgrounds), white (for cobalt fills).
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
                  Cream paper, cobalt primary, warm risk states. No emerald, no teal —
                  those are Vera&rsquo;s. See <code className="font-mono text-xs px-1 py-0.5 rounded bg-[var(--paper-2)]">LOOK.md</code> for contrast ratios.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                  <Swatch label="paper" hex="#FAF7F2" />
                  <Swatch label="paper-2" hex="#F1ECE2" />
                  <Swatch label="ink" hex="#1B1A17" textLight />
                  <Swatch label="cobalt" hex="#2E5BD8" textLight />
                  <Swatch label="cobalt-soft" hex="#E5ECFB" />
                  <Swatch label="cobalt-deep" hex="#1E3FA8" textLight />
                  <Swatch label="amber" hex="#C2410C" textLight />
                  <Swatch label="amber-soft" hex="#FBE6CF" />
                  <Swatch label="coral" hex="#B42318" textLight />
                  <Swatch label="coral-soft" hex="#FCD9D2" />
                  <Swatch label="sage" hex="#4F7C5A" textLight />
                  <Swatch label="sage-soft" hex="#DCEAD8" />
                </div>
              </CardContent>
            </Card>
          </div>
        </Section>

        {/* Typography */}
        <Section n="02" title="Typography" subtitle="Source Serif 4 for display, Inter for UI, JetBrains Mono for IDs.">
          <Card>
            <CardContent className="flex flex-col gap-6 pt-6">
              <div>
                <Caption>Display · serif · 48 / -2.5</Caption>
                <p className="font-serif text-5xl font-semibold tracking-tight text-[var(--ink)]" style={{ letterSpacing: "-0.025em" }}>
                  The notes write themselves.
                </p>
              </div>
              <div>
                <Caption>H1 · serif · 30 / -1</Caption>
                <p className="font-serif text-3xl font-semibold text-[var(--ink)]" style={{ letterSpacing: "-0.015em" }}>
                  Encounter 24-04-29-014
                </p>
              </div>
              <div>
                <Caption>H2 · serif · 20</Caption>
                <p className="font-serif text-xl font-semibold text-[var(--ink)]">
                  Subjective &middot; Objective &middot; Assessment &middot; Plan
                </p>
              </div>
              <div>
                <Caption>Body · sans · 16</Caption>
                <p className="font-sans text-base text-[var(--ink)] leading-relaxed max-w-2xl">
                  Patient is a 64-year-old female presenting with a two-day history of
                  productive cough and low-grade fever. Denies chest pain or dyspnea.
                </p>
              </div>
              <div>
                <Caption>Body small · sans · 14</Caption>
                <p className="font-sans text-sm text-[var(--ink-2)] max-w-2xl">
                  Use this size for table cells, secondary metadata, and the body of cards.
                </p>
              </div>
              <div>
                <Caption>Mono · 13</Caption>
                <p className="font-mono text-sm text-[var(--ink-2)]">
                  enc_01HK9F7T3M2J8R · NPI 1234567890 · MRN 0049-2841
                </p>
              </div>
            </CardContent>
          </Card>
        </Section>

        {/* Buttons */}
        <Section n="03" title="Buttons" subtitle="Four variants. Pill-rounded, soft shadow, cobalt focus ring.">
          <Card>
            <CardContent className="flex flex-col gap-6 pt-6">
              <Row label="Primary">
                <Button variant="primary" size="sm">Sign note</Button>
                <Button variant="primary" size="md">Sign note</Button>
                <Button variant="primary" size="lg">Sign note</Button>
              </Row>
              <Row label="Secondary">
                <Button variant="secondary" size="sm">Discard</Button>
                <Button variant="secondary" size="md">Discard</Button>
                <Button variant="secondary" size="lg">Discard</Button>
              </Row>
              <Row label="Ghost">
                <Button variant="ghost" size="sm">Cancel</Button>
                <Button variant="ghost" size="md">Cancel</Button>
                <Button variant="ghost" size="lg">Cancel</Button>
              </Row>
              <Row label="Destructive">
                <Button variant="destructive" size="sm">Reject draft</Button>
                <Button variant="destructive" size="md">Reject draft</Button>
                <Button variant="destructive" size="lg">Reject draft</Button>
              </Row>
              <Row label="Disabled">
                <Button variant="primary" disabled>Sign note</Button>
                <Button variant="secondary" disabled>Discard</Button>
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Badges */}
        <Section n="04" title="Badges" subtitle="Pill chips for status, counts, and meta labels.">
          <Card>
            <CardContent className="flex flex-col gap-5 pt-6">
              <Row label="Variants">
                <Badge variant="neutral">Draft</Badge>
                <Badge variant="cobalt">In review</Badge>
                <Badge variant="amber">Needs sign-off</Badge>
                <Badge variant="coral">Hold</Badge>
                <Badge variant="sage">Committed</Badge>
                <Badge variant="outline">Archived</Badge>
              </Row>
              <Row label="Sizes">
                <Badge variant="cobalt" size="sm">sm</Badge>
                <Badge variant="cobalt" size="md">md</Badge>
                <Badge variant="cobalt" size="lg">lg</Badge>
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Risk Pills */}
        <Section n="05" title="Risk pills" subtitle="Four tiers. Use these any time a clinician needs to read risk at a glance.">
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
                <RiskPill tier="high" label="Controlled substance" />
                <RiskPill tier="critical" label="STAT" />
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Status Dots */}
        <Section n="06" title="Status dots" subtitle="Live indicator for long-running operations. Active state pulses.">
          <Card>
            <CardContent className="flex flex-col gap-5 pt-6">
              <Row label="States">
                <StatusDot status="running" />
                <StatusDot status="waiting" />
                <StatusDot status="committed" />
                <StatusDot status="error" />
              </Row>
              <Row label="Custom labels">
                <StatusDot status="running" label="Listening" />
                <StatusDot status="waiting" label="Awaiting Dr. Adams" />
                <StatusDot status="committed" label="Sent to Epic" />
                <StatusDot status="error" label="Audio dropped" />
              </Row>
            </CardContent>
          </Card>
        </Section>

        {/* Cards */}
        <Section n="07" title="Cards" subtitle="Soft shadows over hairline borders. The signature ScribeMD surface.">
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            <Card elevation="flat">
              <CardHeader>
                <CardTitle>Flat</CardTitle>
                <CardDescription>Hairline border, no shadow. Nested within other cards.</CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="sm">
              <CardHeader>
                <CardTitle>Small</CardTitle>
                <CardDescription>Subtle lift. List rows, sidebar items.</CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="md">
              <CardHeader>
                <CardTitle>Medium</CardTitle>
                <CardDescription>Default workhorse — most surfaces.</CardDescription>
              </CardHeader>
            </Card>
            <Card elevation="lg">
              <CardHeader>
                <CardTitle>Large</CardTitle>
                <CardDescription>Hero surfaces, modals, the active encounter card.</CardDescription>
              </CardHeader>
            </Card>
          </div>
          <div className="mt-6 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {(["cobalt", "amber", "coral", "sage"] as const).map((t) => (
              <Card key={t} tone={t}>
                <CardHeader>
                  <CardTitle className="capitalize">{t} ring</CardTitle>
                  <CardDescription>
                    Use a tone ring when the card surfaces a status — e.g. an encounter
                    flagged for review.
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
          </div>

          {/* Realistic example */}
          <div className="mt-6">
            <Card elevation="lg">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Encounter 24-04-29-014</CardTitle>
                    <CardDescription>Mary Chen &middot; 64F &middot; productive cough, 2-day onset</CardDescription>
                  </div>
                  <RiskPill tier="medium" label="Order review" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="cobalt">Drafting</Badge>
                  <Badge variant="neutral">Room 4B</Badge>
                  <Badge variant="outline">14 min elapsed</Badge>
                  <span className="font-mono text-xs text-[var(--ink-3)] ml-auto">enc_01HK9F7T3M</span>
                </div>
              </CardContent>
              <CardFooter>
                <Button variant="primary">Open draft</Button>
                <Button variant="ghost">Skip for now</Button>
              </CardFooter>
            </Card>
          </div>
        </Section>

        {/* Forms */}
        <Section n="08" title="Inputs" subtitle="Inset shadow, cobalt focus ring. Keyboard-first.">
          <Card>
            <CardContent className="grid gap-5 pt-6 md:grid-cols-2">
              <Field label="Patient MRN">
                <Input placeholder="0049-2841" />
              </Field>
              <Field label="Provider NPI">
                <Input defaultValue="1234567890" />
              </Field>
              <Field label="Subjective" className="md:col-span-2">
                <Textarea
                  rows={4}
                  defaultValue="64yo F presents with productive cough × 2 days, intermittent low-grade fever (max 100.4°F). Denies chest pain, dyspnea, hemoptysis."
                />
              </Field>
              <Field label="Disabled" className="md:col-span-2">
                <Input disabled placeholder="Read-only field" />
              </Field>
            </CardContent>
          </Card>
        </Section>

        {/* Encounter Pipeline */}
        <Section
          n="09"
          title="Encounter pipeline"
          subtitle="Vertical timeline of agent steps. All four states demonstrated in order."
        >
          <Card elevation="lg">
            <CardHeader>
              <CardTitle>Live encounter &middot; Room 4B</CardTitle>
              <CardDescription>Started 14 min ago &middot; Mary Chen, 64F</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="pt-2">
                <EncounterStep
                  state="done"
                  label="Captured room audio"
                  sublabel="14 min · 22.4 MB · auto-transcribed"
                />
                <EncounterStep
                  state="done"
                  label="Drafted SOAP note"
                  sublabel="Anthropic claude-sonnet-4-6 · 1,840 tokens"
                  payload={
                    <span className="font-serif italic">
                      &ldquo;64yo F with productive cough and intermittent low-grade fever.
                      Vitals stable. Lungs CTA bilaterally. A: viral URI vs. early CAP.&rdquo;
                    </span>
                  }
                />
                <EncounterStep
                  state="active"
                  label="Extracting orders"
                  sublabel="OpenAI gpt-4o · processing"
                  payload="Detected: chest x-ray, CBC with diff, monitor temp q4h."
                />
                <EncounterStep
                  state="blocked"
                  label="Awaiting clinician sign-off"
                  sublabel="One controlled substance order — needs your eyes"
                  payload={
                    <div className="flex items-center gap-2">
                      <RiskPill tier="high" compact label="Schedule III" />
                      <span>Hydrocodone 5/325 PO q6h PRN pain</span>
                    </div>
                  }
                />
                <EncounterStep
                  state="idle"
                  label="Commit to chart"
                  sublabel="Will sync to Epic on approval"
                  isLast
                />
              </div>
            </CardContent>
          </Card>
        </Section>

        <footer className="mt-16 pt-10 border-t border-[var(--hairline)] text-center">
          <Wordmark size="sm" className="opacity-70" />
          <p className="mt-3 font-sans text-xs text-[var(--ink-3)]">
            ScribeMD Health, Inc. &middot; Demo bench
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
          className="font-serif text-2xl font-semibold text-[var(--ink)]"
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
        className="h-16 rounded-xl ring-1 ring-inset ring-[var(--hairline)] flex items-end p-2"
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
