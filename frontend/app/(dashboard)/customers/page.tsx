// Minimal Customers list — PR 13 will replace with full list + detail + Coverage Matrix.
//
// Phase 1 PR 12 ships the Customers sidebar entry; without a landing
// page at /customers, the nav click 404s. This page is intentionally
// thin: it lists the rows from GET /v1/customers (shipped in PR #195)
// with three user-facing columns (Customer, Status, BAA). The customer
// display name links to the detail page where the tenant_id is the URL
// segment — there's no separate user-facing "Tenant ID" column, since
// tenant_id is SDK plumbing and not vocabulary for CEOs / in-house
// counsel. PR 13 will replace this file end-to-end with the full
// Customers experience described in `dashboard-design.md` §Screen 2 —
// Customers list + Coverage Matrix.

"use client";

import Link from "next/link";
import { useCustomers } from "@/hooks/use-customers";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import type { BAAStatus, Customer, CustomerStatus } from "@/lib/api-types";

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

export default function CustomersPage() {
  const { data, isLoading, error } = useCustomers({ limit: 100 });
  const customers = data?.items ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-8 py-2">
      <header className="space-y-2">
        <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
          Customers
        </h1>
        <p className="text-sm text-[color:var(--ink-2)]">
          {isLoading
            ? "Loading…"
            : `${customers.length} customer${customers.length === 1 ? "" : "s"}`}
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--brick-bg)] p-4 text-sm text-[color:var(--brick)]">
          Could not load customers. Try refreshing.
        </div>
      ) : null}

      {isLoading ? (
        <div
          aria-busy="true"
          className="flex justify-center py-8 text-[color:var(--ink-3)]"
          data-testid="customers-loading"
        >
          <Loading.Spinner size={20} label="Loading customers" />
        </div>
      ) : customers.length === 0 ? (
        <EmptyState
          title="No customers yet"
          subtitle="Customers appear here automatically once your SDK starts capturing decisions."
        />
      ) : (
        <CustomersTable customers={customers} />
      )}
    </div>
  );
}

function CustomersTable({ customers }: { customers: Customer[] }) {
  return (
    <div
      className="overflow-hidden rounded-md border border-[color:var(--ink-4)]"
      data-testid="customers-table"
    >
      <table className="w-full text-left text-sm">
        <thead className="bg-[color:var(--paper-2)] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          <tr>
            <th scope="col" className="px-4 py-3">Customer</th>
            <th scope="col" className="px-4 py-3">Status</th>
            <th scope="col" className="px-4 py-3">BAA</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--ink-4)]">
          {customers.map((c) => (
            <tr
              key={c.id}
              className="transition-colors hover:bg-[color:var(--paper-2)]"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/customers/${encodeURIComponent(c.tenant_id)}`}
                  className="font-medium text-[color:var(--ink)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
                >
                  {c.display_name ?? c.tenant_id}
                </Link>
              </td>
              <td className="px-4 py-3">
                <StatusDot variant={STATUS_VARIANT[c.status]} label={STATUS_LABEL[c.status]} />
              </td>
              <td className="px-4 py-3">
                <StatusDot variant={BAA_VARIANT[c.baa_status]} label={BAA_LABEL[c.baa_status]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
