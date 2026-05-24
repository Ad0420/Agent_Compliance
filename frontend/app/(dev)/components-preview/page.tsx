"use client";

/**
 * Component primitives preview — Phase 1 PR 0b.
 *
 * Dev-only Storybook-style page that renders every Phase 1 primitive in
 * every variant. Reviewers visit `/components-preview` in dev (it 404s in
 * production via `app/(dev)/layout.tsx`) to visually verify token usage,
 * focus rings, severity colours, and dashboard tone.
 *
 * Every primitive that ships in this PR appears here at least once. If you
 * add a new primitive under `frontend/components/ui/`, add it to this page
 * so subsequent reviewers (human or AI) can see it without scaffolding.
 */

import * as React from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { StatusDot, StatusIcon } from "@/components/ui/status-indicator";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner, ProgressBar } from "@/components/ui/loading";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { RadioGroup, RadioOption } from "@/components/ui/radio-group";
import { Checkbox, AttestationCheckbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { DocumentIcon } from "@/components/ui/document-icon";
import { IntegrationCard } from "@/components/ui/integration-card";
import { RecommendationCard } from "@/components/ui/recommendation-card";
import { WizardProgress } from "@/components/ui/wizard-progress";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-[color:var(--ink-4)] py-10 first:border-t-0">
      <h2 className="font-display text-[24px] text-[color:var(--ink)] leading-tight">
        {title}
      </h2>
      {description ? (
        <p className="mt-2 max-w-2xl text-[14px] text-[color:var(--ink-2)] leading-relaxed">
          {description}
        </p>
      ) : null}
      <div className="mt-6 flex flex-col gap-8">{children}</div>
    </section>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[160px_1fr] items-start gap-6">
      <p className="pt-1 text-[12px] font-medium uppercase tracking-[0.08em] text-[color:var(--ink-3)]">
        {label}
      </p>
      <div className="flex flex-wrap items-center gap-4">{children}</div>
    </div>
  );
}

export default function ComponentsPreviewPage() {
  // Controlled bits of state for the interactive primitives — re-renders
  // are scoped to this page only.
  const [toggleA, setToggleA] = React.useState(true);
  const [toggleB, setToggleB] = React.useState(false);
  const [radio, setRadio] = React.useState<string | undefined>("co_branded");
  const [checked, setChecked] = React.useState(true);
  const [attested, setAttested] = React.useState(false);
  const [textareaValue, setTextareaValue] = React.useState(
    "Acme is deploying a clinical decision support agent across 14 hospitals…",
  );
  const [recExpanded, setRecExpanded] = React.useState(true);
  const [wizardStep, setWizardStep] = React.useState(2);

  return (
    <TooltipProvider>
      <main className="mx-auto max-w-5xl px-6 py-12">
        <header className="mb-12">
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[color:var(--ink-3)]">
            Phase 1 · PR 0b · dev only
          </p>
          <h1 className="mt-2 font-display text-[36px] text-[color:var(--ink)] leading-tight">
            Component primitives
          </h1>
          <p className="mt-3 max-w-2xl text-[14px] text-[color:var(--ink-2)] leading-relaxed">
            Every reusable primitive shipped in this PR, rendered in every
            variant. Verify focus rings, severity colours, and dashboard
            voice match{" "}
            <code className="rounded bg-[color:var(--paper-3)] px-1.5 py-0.5 font-mono text-[12px]">
              dashboard-design-system.md
            </code>{" "}
            before merging downstream PRs that consume them.
          </p>
        </header>

        <Section
          title="StatusIndicator"
          description="Dot + label and icon + label variants. Always paired with text — colour alone is never the signal."
        >
          <Row label="StatusDot">
            <StatusDot variant="ok" label="Chain intact" />
            <StatusDot variant="warn" label="BAA expires in 30 days" />
            <StatusDot variant="error" label="Chain integrity violation" />
            <StatusDot variant="muted" label="Not yet deployed" />
          </Row>
          <Row label="StatusIcon">
            <StatusIcon variant="ok" label="Compliant" />
            <StatusIcon variant="warn" label="Warning" />
            <StatusIcon variant="error" label="Error" />
            <StatusIcon variant="muted" label="Inactive" />
          </Row>
          <Row label="Size 32">
            <StatusIcon size={32} variant="ok" label="Compliant" />
            <StatusIcon size={32} variant="warn" label="Warning" />
            <StatusIcon size={32} variant="error" label="Error" />
          </Row>
        </Section>

        <Section
          title="SeverityBadge"
          description="Pill marker for issue severity. 22px tall, 6px radius, uppercase."
        >
          <Row label="Default labels">
            <SeverityBadge severity="HIGH" />
            <SeverityBadge severity="MEDIUM" />
            <SeverityBadge severity="LOW" />
            <SeverityBadge severity="INFO" />
          </Row>
          <Row label="Custom label">
            <SeverityBadge severity="HIGH">EXPIRED BAA</SeverityBadge>
            <SeverityBadge severity="MEDIUM">STALE</SeverityBadge>
            <SeverityBadge severity="LOW">OPTIONAL</SeverityBadge>
          </Row>
        </Section>

        <Section
          title="EmptyState"
          description="Title + optional subtitle + optional CTA. No illustrations, no emoji."
        >
          <Row label="With CTA (button)">
            <div className="w-full rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)]">
              <EmptyState
                title="You haven't generated any audit PDFs yet."
                subtitle="Audit PDFs collect a customer's posture, evidence trail, and chain integrity into a single reviewable document."
                ctaLabel="Generate your first PDF"
                onCtaClick={() => alert("CTA clicked")}
              />
            </div>
          </Row>
          <Row label="With CTA (link)">
            <div className="w-full rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)]">
              <EmptyState
                title="No customers yet."
                ctaLabel="Add your first customer"
                ctaHref="/dashboard"
              />
            </div>
          </Row>
          <Row label="Title only">
            <div className="w-full rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)]">
              <EmptyState title="No webhook deliveries in the last 24 hours." />
            </div>
          </Row>
        </Section>

        <Section
          title="Loading"
          description="Spinner for 200ms-2s contexts; ProgressBar for 2s-30s contexts. No skeleton screens."
        >
          <Row label="Spinner sizes">
            <Spinner size={12} />
            <Spinner size={16} />
            <Spinner size={20} />
            <Spinner size={24} />
            <span className="inline-flex items-center gap-2 text-[14px] text-[color:var(--ink)]">
              <Spinner size={12} label="Generating" />
              Generating…
            </span>
          </Row>
          <Row label="ProgressBar (50%)">
            <div className="w-80">
              <ProgressBar value={50} label="Generating PDF (3 of 7 sections)…" />
            </div>
          </Row>
          <Row label="Indeterminate">
            <div className="w-80">
              <ProgressBar ariaLabel="Importing CSV" />
            </div>
          </Row>
        </Section>

        <Section
          title="Toggle (switch)"
          description="Per-row enable/disable. Keyboard-toggleable via Space/Enter."
        >
          <Row label="Standalone">
            <ToggleSwitch
              checked={toggleA}
              onChange={setToggleA}
              ariaLabel="Enable feature"
            />
            <ToggleSwitch
              checked={false}
              onChange={() => {}}
              disabled
              ariaLabel="Disabled toggle"
            />
          </Row>
          <Row label="With label">
            <div className="w-96">
              <ToggleSwitch
                checked={toggleB}
                onChange={setToggleB}
                label="Send weekly digest"
                description="Friday 09:00 UTC, summarising the past 7 days of audit activity."
              />
            </div>
          </Row>
        </Section>

        <Section
          title="RadioGroup + RadioOption"
          description="Native radio inputs with the labeled-row variant from the wizard / PDF modal."
        >
          <Row label="Group">
            <div className="w-full max-w-md">
              <RadioGroup
                name="branding"
                label="Branding"
                value={radio}
                onChange={setRadio}
              >
                <RadioOption
                  value="vera"
                  label="Vera-branded"
                  description="Render the PDF under Vera's evidence-trail mark."
                />
                <RadioOption
                  value="co_branded"
                  label="Co-branded"
                  description="Show your organisation's mark alongside Vera's evidence-trail mark."
                />
                <RadioOption
                  value="white_label"
                  label="White-label (your brand only)"
                  description="Suppress Vera chrome. Available on Enterprise plans."
                  disabled
                />
              </RadioGroup>
            </div>
          </Row>
        </Section>

        <Section
          title="Checkbox + AttestationCheckbox"
          description="Standard checkbox plus the brick-bordered attestation variant for the audit-PDF flow."
        >
          <Row label="Standard">
            <Checkbox
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              label="Email me when a recommendation is generated"
              description="One email per recommendation. Quiet hours respected."
            />
          </Row>
          <Row label="Error state">
            <Checkbox
              error
              label="Required field"
              description="You must accept the terms before continuing."
            />
          </Row>
          <Row label="Attestation">
            <div className="w-full max-w-2xl">
              <AttestationCheckbox
                checked={attested}
                onChange={setAttested}
                attestation="I am authorised to attest that the compliance posture below accurately reflects this deployment as of today's date."
                context="Your name, role, and the current UTC timestamp will be embedded in the generated PDF's evidence trail."
              />
            </div>
          </Row>
          <Row label="Attestation (error)">
            <div className="w-full max-w-2xl">
              {/* Renders the brick banner intensified — full-strength border,
                  4px brick left-border accent, brick label colour, brick
                  checkbox border — to simulate a failed-submit state where
                  attestation is required but unchecked. */}
              <AttestationCheckbox
                checked={false}
                onChange={() => {}}
                error
                attestation="I am authorised to attest that the compliance posture below accurately reflects this deployment as of today's date."
                context="You must attest before generating the audit PDF."
              />
            </div>
          </Row>
        </Section>

        <Section
          title="Textarea"
          description="Label + textarea + helper / error / counter. 100px minimum height."
        >
          <Row label="With counter">
            <div className="w-full max-w-2xl">
              <Textarea
                label="Customer description"
                helpText="Used in the audit PDF's executive summary."
                value={textareaValue}
                onChange={(e) => setTextareaValue(e.target.value)}
                maxLength={280}
              />
            </div>
          </Row>
          <Row label="Error">
            <div className="w-full max-w-2xl">
              <Textarea
                label="Justification"
                error="Justification is required to override the recommendation."
                placeholder="Why are you overriding this recommendation?"
              />
            </div>
          </Row>
        </Section>

        <Section
          title="DocumentIcon"
          description="Muted-red page-with-folded-corner glyph. The one exception to the monochrome icon rule."
        >
          <Row label="Sizes">
            <DocumentIcon size={16} />
            <DocumentIcon size={20} />
            <DocumentIcon size={24} />
            <DocumentIcon size={32} />
          </Row>
          <Row label="With label">
            <DocumentIcon size={32} label="PDF" />
            <DocumentIcon size={32} label="CSV" />
          </Row>
        </Section>

        <Section
          title="IntegrationCard"
          description="Settings → Integrations grid card. The brand-coloured logo is the one place coloured backgrounds are allowed."
        >
          <Row label="Connected">
            <div className="grid w-full grid-cols-1 gap-6 md:grid-cols-2">
              <IntegrationCard
                name="Slack"
                logo={
                  <span className="flex size-10 items-center justify-center rounded-[8px] bg-[#611f69] text-[14px] font-bold text-white">
                    S
                  </span>
                }
                description="Post webhook delivery failures and pending review notifications to a Slack channel."
                status={{ variant: "ok", label: "Connected · 0 failures in 24h" }}
                domain={{ label: "slack.com", href: "https://slack.com" }}
                controls={
                  <>
                    <button
                      type="button"
                      className={
                        "inline-flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-[13px] text-[color:var(--ink-2)] hover:bg-[color:var(--paper-3)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
                      }
                    >
                      Settings
                    </button>
                    <ToggleSwitch
                      checked={true}
                      onChange={() => {}}
                      ariaLabel="Enable Slack integration"
                    />
                  </>
                }
              />
              <IntegrationCard
                name="OpenTimestamps"
                logo={
                  <span className="flex size-10 items-center justify-center rounded-[8px] bg-[#1a2942] text-[14px] font-bold text-white">
                    OT
                  </span>
                }
                description="Anchor hash-chain checkpoints into the Bitcoin blockchain for independent verification."
                status={{ variant: "warn", label: "Anchor pending · last 6h ago" }}
                domain={{ label: "opentimestamps.org" }}
                controls={
                  <ToggleSwitch
                    checked={true}
                    onChange={() => {}}
                    ariaLabel="Enable OpenTimestamps"
                  />
                }
              />
            </div>
          </Row>
        </Section>

        <Section
          title="RecommendationCard"
          description="AI Insights card. Severity badge, quoted source, suggested action, Apply button, and the regulatory disclaimer footer."
        >
          <Row label="Expanded">
            <div className="w-full max-w-3xl">
              <RecommendationCard
                severity="HIGH"
                title="Cleveland Clinic BAA missing required breach-notification window"
                quotedSource={
                  <>
                    “Business Associate shall report to Covered Entity any
                    Breach of Unsecured Protected Health Information of which
                    it becomes aware within <strong>sixty (60) days</strong> of
                    discovery.”
                  </>
                }
                description="The HIPAA Breach Notification Rule requires reporting within 60 days for breaches affecting fewer than 500 individuals, but the BAA on file does not include the rule's required content elements (description, types of unsecured PHI, mitigation steps)."
                suggestedAction="Insert the §164.410 required-content paragraph from the standard HIPAA BAA template into Section 4.2 of Cleveland Clinic's BAA before next renewal."
                expanded={recExpanded}
                onToggle={setRecExpanded}
                onApply={() => alert("Apply recommendation")}
              />
            </div>
          </Row>
          <Row label="Collapsed">
            <div className="w-full max-w-3xl">
              <RecommendationCard
                severity="MEDIUM"
                title="Reviewer attestation latency for Mercy Hospital is below threshold"
                description="The median time from agent decision to human reviewer attestation is 4.2 hours; the target is under 1 hour."
                onApply={() => alert("Apply recommendation")}
              />
            </div>
          </Row>
          <Row label="LOW (no apply)">
            <div className="w-full max-w-3xl">
              <RecommendationCard
                severity="LOW"
                title="Add a redundant timestamp anchor for OpenTimestamps outages"
                description="Vera anchors chain checkpoints into Bitcoin via OpenTimestamps every 4 hours. Adding a secondary anchor (e.g., Ethereum mainnet) would protect against single-network outages."
              />
            </div>
          </Row>
        </Section>

        <Section
          title="WizardProgress"
          description="N-step dot indicator for the 5-question wizard and other multi-step flows."
        >
          <Row label="5 steps (step 3)">
            <WizardProgress totalSteps={5} currentStep={2} showLabel />
          </Row>
          <Row label="Interactive">
            <div className="flex items-center gap-4">
              <WizardProgress
                totalSteps={5}
                currentStep={wizardStep}
                onStepClick={setWizardStep}
                showLabel
              />
              <button
                type="button"
                onClick={() => setWizardStep((s) => Math.min(4, s + 1))}
                className="inline-flex h-8 items-center rounded-[8px] bg-[color:var(--ink)] px-3 text-[12px] font-medium text-[color:var(--paper)]"
              >
                Next →
              </button>
            </div>
          </Row>
          <Row label="3 steps (last)">
            <WizardProgress totalSteps={3} currentStep={2} />
          </Row>
        </Section>

        <Section
          title="Tooltip"
          description="Shadcn-Radix tooltip already in the codebase; previewed here for completeness."
        >
          <Row label="On hover">
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="inline-flex h-8 items-center rounded-[8px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] px-3 text-[13px] text-[color:var(--ink)]">
                  Hover me
                </button>
              </TooltipTrigger>
              <TooltipContent>Tooltip body in ink-on-paper.</TooltipContent>
            </Tooltip>
          </Row>
        </Section>
      </main>
    </TooltipProvider>
  );
}
