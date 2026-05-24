// Customer detail stub — PR 13 will replace with the full Customer detail
// surface described in `dashboard-design.md` §Screen 3 — Customer detail.
//
// Phase 1 PR 12 introduces the route so the Home page's Recent activity
// rows and the Customers list can link somewhere live. This stub renders
// the bare minimum: display name + status pair + a "coming soon" notice.

"use client";

import Link from "next/link";
import { use } from "react";
import { useCustomer } from "@/hooks/use-customers";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import type { BAAStatus, CustomerStatus } from "@/lib/api-types";
import { ArrowLeft } from "lucide-react";

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

export default function CustomerDetailStubPage({ params }: PageProps) {
  const { tenant_id } = use(params);
  const { data: customer, isLoading, error } = useCustomer(tenant_id);

  return (
    <div className="mx-auto max-w-3xl space-y-8 py-2">
      <Link
        href="/customers"
        className="inline-flex items-center gap-1 text-sm text-[color:var(--ink-2)] hover:text-[color:var(--ink)]"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        Customers
      </Link>

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
          subtitle={`No customer with tenant id "${tenant_id}".`}
          ctaLabel="Back to Customers"
          ctaHref="/customers"
        />
      ) : customer ? (
        <>
          <header className="space-y-3">
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
            </div>
          </header>

          <section className="rounded-md border border-dashed border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-6">
            <p className="text-[13px] font-medium text-[color:var(--ink)]">
              Full detail page coming in PR 13.
            </p>
            <p className="mt-1 text-[13px] text-[color:var(--ink-2)]">
              The next phase ships generate-audit-PDF, status overview,
              recent decisions, reviewers, documents, and past audit PDFs
              for this customer.
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}
