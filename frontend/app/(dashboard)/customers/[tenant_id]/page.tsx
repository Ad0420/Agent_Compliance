// Customer detail page — Phase 1 PR 13, Stream F item F3.
//
// Replaces the PR #198 stub. Two render paths (per the v1 plan):
//
//   Variant A — pending_setup customer (zero decisions):
//     Prominent "Complete setup" CTA above the fold + inline wizard
//     (display name → BAA upload → contact). Sample-data preview
//     beneath the CTA shows what the populated view will look like once
//     decisions stream in. Wizard's BAA upload is the Phase 1
//     acceptance gate ("one BAA upload completes setup").
//
//   Variant B — populated customer (decisions exist):
//     Header (display name + status badges + inline contact edit) →
//     AI Coverage Matrix (ABOVE Status per Codex D1) →
//     Status section → Decisions stream → BAA management widget.

"use client";

import * as React from "react";
import Link from "next/link";
import { use } from "react";
import { ArrowLeft } from "lucide-react";

import {
  useCustomer,
  useCustomerAgents,
  usePatchCustomer,
} from "@/hooks/use-customers";
import { useActions } from "@/hooks/use-actions";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import {
  CoverageMatrixCompact,
  CoverageMatrixFull,
} from "@/components/dashboard/coverage-matrix";
import { BaaUploadWidget } from "@/components/dashboard/baa-upload";
import { formatRelativeTime } from "@/lib/utils";
import type {
  ActionRecord,
  BAAStatus,
  Customer,
  CustomerAgentCoverage,
  CustomerStatus,
} from "@/lib/api-types";

const STATUS_LABEL: Record<CustomerStatus, string> = {
  pending_setup: "Setup required",
  active: "Active",
  suspended: "Suspended",
  archived: "Archived",
};

const STATUS_VARIANT: Record<CustomerStatus, StatusVariant> = {
  pending_setup: "warn",
  active: "ok",
  suspended: "warn",
  archived: "muted",
};

const BAA_LABEL: Record<BAAStatus, string> = {
  missing: "No BAA on file",
  pending: "BAA pending",
  active: "BAA in effect",
  expired: "BAA expired",
  terminated: "BAA terminated",
};

const BAA_VARIANT: Record<BAAStatus, StatusVariant> = {
  missing: "warn",
  pending: "warn",
  active: "ok",
  expired: "error",
  terminated: "error",
};

interface PageProps {
  params: Promise<{ tenant_id: string }>;
}

export default function CustomerDetailPage({ params }: PageProps) {
  const { tenant_id } = use(params);
  const { data: customer, isLoading, error } = useCustomer(tenant_id);

  return (
    <div className="mx-auto max-w-5xl space-y-10 py-2">
      <Breadcrumb
        customerName={customer?.display_name ?? customer?.tenant_id ?? null}
      />

      {isLoading ? (
        <div
          aria-busy="true"
          className="flex justify-center py-8 text-[color:var(--ink-3)]"
          data-testid="customer-detail-loading"
        >
          <Loading.Spinner size={20} label="Loading customer" />
        </div>
      ) : error ? (
        <EmptyState
          title="Customer not found"
          subtitle="No customer matches this URL. Return to the Customers list."
          ctaLabel="Back to Customers"
          ctaHref="/customers"
        />
      ) : customer ? (
        <CustomerDetailBody customer={customer} />
      ) : null}
    </div>
  );
}

function Breadcrumb({ customerName }: { customerName: string | null }) {
  return (
    <nav aria-label="Breadcrumb">
      <Link
        href="/customers"
        className="inline-flex items-center gap-1 text-[13px] text-[color:var(--ink-2)] hover:text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        <span>Customers</span>
        {customerName ? (
          <>
            <span aria-hidden="true" className="mx-1 text-[color:var(--ink-3)]">
              /
            </span>
            <span className="text-[color:var(--ink)]">{customerName}</span>
          </>
        ) : null}
      </Link>
    </nav>
  );
}

function CustomerDetailBody({ customer }: { customer: Customer }) {
  // Variant decision: pending_setup OR missing BAA → wizard surface.
  // Populated otherwise. Treating "missing BAA" as pending-setup keeps
  // the operator on the wizard until the acceptance gate is met even
  // if auto-discovery already flipped the customer to active via a
  // future lifecycle PR.
  const needsSetup =
    customer.status === "pending_setup" ||
    customer.baa_status === "missing" ||
    customer.baa_status === "expired" ||
    customer.baa_status === "terminated";

  return (
    <>
      <CustomerHeader customer={customer} />
      {needsSetup ? (
        <CompleteSetupSection customer={customer} />
      ) : (
        <PopulatedSections customer={customer} />
      )}
    </>
  );
}

function CustomerHeader({ customer }: { customer: Customer }) {
  return (
    <header className="space-y-3" data-testid="customer-header">
      <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
        {customer.display_name ?? customer.tenant_id}
      </h1>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <StatusDot
          variant={STATUS_VARIANT[customer.status]}
          label={STATUS_LABEL[customer.status]}
        />
        <StatusDot
          variant={BAA_VARIANT[customer.baa_status]}
          label={BAA_LABEL[customer.baa_status]}
        />
        {customer.last_seen_at ? (
          <span className="text-[13px] text-[color:var(--ink-2)]">
            Last activity {formatRelativeTime(customer.last_seen_at)}
          </span>
        ) : null}
      </div>
      {customer.contact_email ? (
        <p className="text-[13px] text-[color:var(--ink-2)]">
          Contact: {customer.contact_name ? `${customer.contact_name} · ` : ""}
          {customer.contact_email}
        </p>
      ) : null}
    </header>
  );
}

// ─── Variant A — pending_setup ─────────────────────────────────────────────

function CompleteSetupSection({ customer }: { customer: Customer }) {
  return (
    <div className="space-y-8">
      <section
        className="rounded-md border border-[color:var(--amber)]/30 bg-[color:var(--amber-bg)] p-6"
        data-testid="complete-setup-cta"
      >
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          Complete setup
        </p>
        <h2 className="mt-2 font-display text-2xl font-normal leading-snug text-[color:var(--ink)]">
          Finish onboarding this customer to unblock audit packets
        </h2>
        <p className="mt-2 text-[14px] text-[color:var(--ink-2)]">
          Decisions captured before setup completes are encrypted and
          hash-chained but excluded from generated PDFs. Three steps:
        </p>
        <SetupWizard customer={customer} />
      </section>

      <SamplePreview />
    </div>
  );
}

interface WizardStepHeaderProps {
  index: number;
  title: string;
  done: boolean;
}

function WizardStepHeader({ index, title, done }: WizardStepHeaderProps) {
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden="true"
        className={`flex size-5 items-center justify-center rounded-full text-[11px] font-medium ${
          done
            ? "bg-[color:var(--olive)] text-[color:var(--paper)]"
            : "bg-[color:var(--paper-3)] text-[color:var(--ink-2)]"
        }`}
      >
        {done ? "✓" : index}
      </span>
      <h3 className="text-[14px] font-semibold text-[color:var(--ink)]">
        {title}
      </h3>
    </div>
  );
}

function SetupWizard({ customer }: { customer: Customer }) {
  const patchCustomer = usePatchCustomer(customer.tenant_id);
  const [displayName, setDisplayName] = React.useState(
    customer.display_name ?? customer.tenant_id,
  );
  const [contactName, setContactName] = React.useState(customer.contact_name ?? "");
  const [contactEmail, setContactEmail] = React.useState(
    customer.contact_email ?? "",
  );

  const displayNameSet =
    customer.display_name !== null &&
    customer.display_name !== "" &&
    customer.display_name !== customer.tenant_id;
  const baaInEffect = customer.baa_status === "active";
  const contactComplete = !!customer.contact_email;

  const saveDisplayName = () => {
    if (!displayName.trim() || displayName === customer.display_name) return;
    patchCustomer.mutate({ display_name: displayName.trim() });
  };

  const saveContact = () => {
    patchCustomer.mutate({
      contact_name: contactName.trim() || null,
      contact_email: contactEmail.trim() || null,
    });
  };

  return (
    <div className="mt-6 space-y-6" data-testid="setup-wizard">
      {/* Step 1 — display name */}
      <div className="space-y-2 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-4">
        <WizardStepHeader index={1} title="Set a display name" done={displayNameSet} />
        <p className="text-[12px] text-[color:var(--ink-2)]">
          Customers list and audit PDFs use this name in place of the raw SDK
          identifier ({customer.tenant_id}).
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={patchCustomer.isPending}
            className="block flex-1 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
            aria-label="Customer display name"
            data-testid="setup-display-name-input"
          />
          <button
            type="button"
            onClick={saveDisplayName}
            disabled={
              patchCustomer.isPending ||
              !displayName.trim() ||
              displayName === customer.display_name
            }
            className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--ink)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {patchCustomer.isPending ? "Saving…" : "Save name"}
          </button>
        </div>
      </div>

      {/* Step 2 — BAA upload (the acceptance gate) */}
      <div className="space-y-3 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-4">
        <WizardStepHeader index={2} title="Upload signed BAA" done={baaInEffect} />
        <p className="text-[12px] text-[color:var(--ink-2)]">
          The signed Business Associate Agreement is required before this
          customer&apos;s decisions are included in audit packets.
        </p>
        <BaaUploadWidget
          tenant_id={customer.tenant_id}
          customer_display_name={customer.display_name ?? customer.tenant_id}
          variant="wizard"
        />
      </div>

      {/* Step 3 — contact info (optional but recommended) */}
      <div className="space-y-2 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-4">
        <WizardStepHeader
          index={3}
          title="Confirm contact (optional)"
          done={contactComplete}
        />
        <p className="text-[12px] text-[color:var(--ink-2)]">
          Who at this customer should we reach for BAA renewal reminders?
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <input
            type="text"
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
            placeholder="Contact name"
            aria-label="Contact name"
            className="block w-full rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
          />
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="contact@example.com"
            aria-label="Contact email"
            className="block w-full rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
          />
        </div>
        <button
          type="button"
          onClick={saveContact}
          disabled={patchCustomer.isPending}
          className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--ink)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {patchCustomer.isPending ? "Saving…" : "Save contact"}
        </button>
      </div>
    </div>
  );
}

// Static synthetic preview rows so the operator sees what the populated
// view will look like once decisions stream in. The values are fixed
// (and deliberately in the past) so the "Preview · No real data" tag is
// never misread as live state. Defined at module scope to satisfy the
// React Compiler purity rule (no Date.now() during render).
const SAMPLE_PREVIEW_AGENTS: CustomerAgentCoverage[] = [
  {
    id: "preview-1",
    agent_type: "scribe",
    agent_id: null,
    source: "auto_discovered",
    confidence: "high",
    status: "active",
    first_seen_at: "2026-05-12T00:00:00.000Z",
    last_seen_at: "2026-05-19T14:30:00.000Z",
    coverage: "covered",
    has_capture: true,
    hitl_gate_count: 0,
    pdf_included: false,
    posture_included: false,
  },
];

function SamplePreview() {
  return (
    <section
      className="space-y-3 rounded-md border border-dashed border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-6"
      data-testid="sample-preview"
      aria-label="Sample preview of populated customer detail page"
    >
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          Preview · No real data
        </p>
        <span className="text-[11px] uppercase tracking-[0.06em] text-[color:var(--ink-3)]">
          What you&apos;ll see after setup
        </span>
      </div>
      <p className="text-[13px] text-[color:var(--ink-2)]">
        Once setup completes and decisions begin flowing, this customer&apos;s
        page will include an AI coverage matrix, status overview, and a
        decisions stream — like this:
      </p>
      <CoverageMatrixFull agents={SAMPLE_PREVIEW_AGENTS} />
    </section>
  );
}

// ─── Variant B — populated ────────────────────────────────────────────────

function PopulatedSections({ customer }: { customer: Customer }) {
  const { data: agentData, isLoading: agentsLoading } = useCustomerAgents(
    customer.tenant_id,
    true,
  );
  const agents = agentData?.items ?? [];

  return (
    <div className="space-y-12" data-testid="customer-populated">
      {/* AI Coverage Matrix — ABOVE Status per Codex D1. */}
      <section className="space-y-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          AI coverage matrix
        </h2>
        <CoverageMatrixFull agents={agents} isLoading={agentsLoading} />
      </section>

      {/* Status section — count summary + rollup. */}
      <StatusSection customer={customer} agents={agents} />

      {/* Decisions stream. */}
      <DecisionsStream tenant_id={customer.tenant_id} />

      {/* BAA management — show current state + allow re-upload. */}
      <BaaManagement customer={customer} />
    </div>
  );
}

function StatusSection({
  customer,
  agents,
}: {
  customer: Customer;
  agents: CustomerAgentCoverage[];
}) {
  return (
    <section
      className="space-y-3 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-5"
      data-testid="status-section"
    >
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
        Status
      </h2>
      <ul className="space-y-2">
        <li>
          <StatusDot
            variant={BAA_VARIANT[customer.baa_status]}
            label={BAA_LABEL[customer.baa_status]}
          />
        </li>
        <li>
          <CoverageMatrixCompact agents={agents} />
        </li>
        <li className="text-[13px] text-[color:var(--ink-2)] tabular-nums">
          {customer.decision_count_30d.toLocaleString()} decision
          {customer.decision_count_30d === 1 ? "" : "s"} captured in the last 30
          days
        </li>
      </ul>
    </section>
  );
}

function DecisionsStream({ tenant_id }: { tenant_id: string }) {
  const { data, isLoading } = useActions({ tenant_id, limit: 50 });

  return (
    <section className="space-y-3" data-testid="decisions-stream">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          Recent decisions
        </h2>
        {data && data.total > 0 ? (
          <span className="text-[12px] text-[color:var(--ink-3)] [font-feature-settings:'tnum']">
            {data.total.toLocaleString()} total
          </span>
        ) : null}
      </div>
      {isLoading ? (
        <div
          aria-busy="true"
          className="flex justify-center py-6 text-[color:var(--ink-3)]"
        >
          <Loading.Spinner size={20} label="Loading decisions" />
        </div>
      ) : !data || data.records.length === 0 ? (
        <p className="text-[13px] text-[color:var(--ink-2)]">
          No decisions captured for this customer yet.
        </p>
      ) : (
        <DecisionsList records={data.records} />
      )}
    </section>
  );
}

function DecisionsList({ records }: { records: ActionRecord[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-[color:var(--ink-4)]">
      <table className="w-full text-left text-[13px] [font-feature-settings:'tnum']">
        <thead className="bg-[color:var(--paper-2)] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          <tr>
            <th scope="col" className="px-4 py-3">When</th>
            <th scope="col" className="px-4 py-3">Agent</th>
            <th scope="col" className="px-4 py-3">Action</th>
            <th scope="col" className="px-4 py-3">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--ink-4)]">
          {records.map((rec) => (
            <tr key={rec.id}>
              <td className="px-4 py-3 text-[color:var(--ink-2)]">
                {formatRelativeTime(rec.action_timestamp)}
              </td>
              <td className="px-4 py-3 text-[color:var(--ink)]">{rec.agent_name}</td>
              <td className="px-4 py-3 text-[color:var(--ink)]">{rec.action_name}</td>
              <td className="px-4 py-3 text-[color:var(--ink-2)]">{rec.result}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BaaManagement({ customer }: { customer: Customer }) {
  return (
    <section className="space-y-3" data-testid="baa-management">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
        BAA management
      </h2>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-5 py-4">
        <StatusDot
          variant={BAA_VARIANT[customer.baa_status]}
          label={BAA_LABEL[customer.baa_status]}
        />
      </div>
      <details className="rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-5">
        <summary className="cursor-pointer text-[13px] font-medium text-[color:var(--ink)]">
          Upload a new BAA
        </summary>
        <div className="mt-4">
          <BaaUploadWidget
            tenant_id={customer.tenant_id}
            customer_display_name={customer.display_name ?? customer.tenant_id}
            variant="section"
          />
        </div>
      </details>
    </section>
  );
}
