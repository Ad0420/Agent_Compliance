// Customers list — Phase 1 PR 13, Stream F item F2.
//
// Replaces the PR #198 stub. Full implementation:
//   - Display name (links to detail) — Petrona via font-display utility
//   - Status (StatusDot + label)
//   - AI Coverage rollup (CoverageMatrix variant="compact")
//   - Last activity (relative)
//   - 30-day decision count (batched via ?with_counts=1, no N+1)
//   - BAA status (StatusDot + label)
//
// Filters: status + BAA status chips. Sorting: by URL query param,
// default last_seen_at DESC. Empty list → EmptyState primitive.
// pending_setup rows get an amber-tinted background.

"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { useCustomers } from "@/hooks/use-customers";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import { CoverageMatrixCompact } from "@/components/dashboard/coverage-matrix";
import { formatRelativeTime } from "@/lib/utils";
import type {
  BAAStatus,
  Customer,
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

const STATUS_FILTER_OPTIONS: CustomerStatus[] = [
  "pending_setup",
  "active",
  "suspended",
];
const BAA_FILTER_OPTIONS: BAAStatus[] = ["active", "missing", "expired"];

type SortKey = "last_seen" | "name" | "decisions";

export default function CustomersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Read filters + sort from URL so the state is shareable / bookmarkable
  // and survives navigation back from the Customer detail page.
  const statusFilter =
    (searchParams.get("status") as CustomerStatus | null) ?? null;
  const baaFilter =
    (searchParams.get("baa") as BAAStatus | null) ?? null;
  const sort = (searchParams.get("sort") as SortKey | null) ?? "last_seen";

  const setQuery = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === null || value === "") {
      params.delete(key);
    } else {
      params.set(key, value);
    }
    router.replace(`/customers${params.toString() ? `?${params.toString()}` : ""}`);
  };

  const { data, isLoading, error } = useCustomers({
    status: statusFilter ?? undefined,
    baa_status: baaFilter ?? undefined,
    with_counts: true,
    limit: 100,
  });

  // Memoize the raw list so the sort effect below depends on a stable
  // reference. Without this the React Compiler refuses to optimize the
  // sorted memo because the dependency could mutate on each render.
  const customers = React.useMemo<Customer[]>(
    () => data?.items ?? [],
    [data?.items],
  );
  const totalDecisions = customers.reduce(
    (sum, c) => sum + (c.decision_count_30d ?? 0),
    0,
  );

  const sorted = React.useMemo(() => {
    const list = [...customers];
    switch (sort) {
      case "name":
        list.sort((a, b) =>
          (a.display_name ?? a.tenant_id).localeCompare(
            b.display_name ?? b.tenant_id,
          ),
        );
        break;
      case "decisions":
        list.sort(
          (a, b) =>
            (b.decision_count_30d ?? 0) - (a.decision_count_30d ?? 0),
        );
        break;
      case "last_seen":
      default:
        list.sort((a, b) => {
          const A = a.last_seen_at ? new Date(a.last_seen_at).getTime() : 0;
          const B = b.last_seen_at ? new Date(b.last_seen_at).getTime() : 0;
          return B - A;
        });
        break;
    }
    return list;
  }, [customers, sort]);

  return (
    <div className="mx-auto max-w-6xl space-y-8 py-2">
      <header className="space-y-2">
        <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
          Customers
        </h1>
        <p className="text-[13px] text-[color:var(--ink-2)]">
          {isLoading
            ? "Loading…"
            : `${customers.length} customer${customers.length === 1 ? "" : "s"} · ${totalDecisions.toLocaleString()} decision${
                totalDecisions === 1 ? "" : "s"
              } last 30 days`}
        </p>
      </header>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--brick-bg)] p-4 text-[13px] text-[color:var(--brick)]"
        >
          Could not load customers. Try refreshing.
        </div>
      ) : null}

      <Filters
        statusFilter={statusFilter}
        baaFilter={baaFilter}
        onStatus={(v) => setQuery("status", v)}
        onBaa={(v) => setQuery("baa", v)}
      />

      {isLoading ? (
        <div
          aria-busy="true"
          className="flex justify-center py-8 text-[color:var(--ink-3)]"
          data-testid="customers-loading"
        >
          <Loading.Spinner size={20} label="Loading customers" />
        </div>
      ) : sorted.length === 0 ? (
        statusFilter || baaFilter ? (
          <EmptyState
            title="No customers match these filters"
            subtitle="Clear the filters to see all customers in this organization."
            ctaLabel="Clear filters"
            onCtaClick={() => {
              const params = new URLSearchParams();
              router.replace("/customers");
              void params;
            }}
          />
        ) : (
          <EmptyState
            title="No customers yet"
            subtitle="Customers appear here automatically once your SDK starts capturing decisions."
          />
        )
      ) : (
        <CustomersTable
          customers={sorted}
          sort={sort}
          onSort={(v) => setQuery("sort", v === "last_seen" ? null : v)}
        />
      )}
    </div>
  );
}

function Filters({
  statusFilter,
  baaFilter,
  onStatus,
  onBaa,
}: {
  statusFilter: CustomerStatus | null;
  baaFilter: BAAStatus | null;
  onStatus: (v: CustomerStatus | null) => void;
  onBaa: (v: BAAStatus | null) => void;
}) {
  return (
    <div className="space-y-3" data-testid="customers-filters">
      <FilterGroup
        label="Status"
        options={STATUS_FILTER_OPTIONS.map((opt) => ({
          value: opt,
          label: STATUS_LABEL[opt],
        }))}
        selected={statusFilter}
        onSelect={(v) => onStatus(v as CustomerStatus | null)}
      />
      <FilterGroup
        label="BAA"
        options={BAA_FILTER_OPTIONS.map((opt) => ({
          value: opt,
          label: BAA_LABEL[opt],
        }))}
        selected={baaFilter}
        onSelect={(v) => onBaa(v as BAAStatus | null)}
      />
    </div>
  );
}

function FilterGroup<T extends string>({
  label,
  options,
  selected,
  onSelect,
}: {
  label: string;
  options: { value: T; label: string }[];
  selected: T | null;
  onSelect: (v: T | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
        {label}
      </span>
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={chipClass(selected === null)}
      >
        All
      </button>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onSelect(selected === opt.value ? null : opt.value)}
          className={chipClass(selected === opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function chipClass(active: boolean): string {
  return [
    "inline-flex h-7 items-center rounded-full border px-3 text-[12px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
    active
      ? "border-[color:var(--ink)] bg-[color:var(--ink)] text-[color:var(--paper)]"
      : "border-[color:var(--ink-4)] bg-[color:var(--paper)] text-[color:var(--ink-2)] hover:bg-[color:var(--paper-2)]",
  ].join(" ");
}

function CustomersTable({
  customers,
  sort,
  onSort,
}: {
  customers: Customer[];
  sort: SortKey;
  onSort: (sort: SortKey) => void;
}) {
  return (
    <div
      className="overflow-hidden rounded-md border border-[color:var(--ink-4)]"
      data-testid="customers-table"
    >
      <table className="w-full text-left text-[13px] [font-feature-settings:'tnum']">
        <thead className="bg-[color:var(--paper-2)] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          <tr>
            <th scope="col" className="px-4 py-3">
              <SortHeader
                label="Customer"
                value="name"
                active={sort === "name"}
                onSelect={onSort}
              />
            </th>
            <th scope="col" className="px-4 py-3">Status</th>
            <th scope="col" className="px-4 py-3">AI coverage</th>
            <th scope="col" className="px-4 py-3">
              <SortHeader
                label="Last activity"
                value="last_seen"
                active={sort === "last_seen"}
                onSelect={onSort}
              />
            </th>
            <th scope="col" className="px-4 py-3">
              <SortHeader
                label="Decisions 30d"
                value="decisions"
                active={sort === "decisions"}
                onSelect={onSort}
              />
            </th>
            <th scope="col" className="px-4 py-3">BAA</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--ink-4)]">
          {customers.map((c) => (
            <CustomerRow key={c.id} customer={c} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SortHeader({
  label,
  value,
  active,
  onSelect,
}: {
  label: string;
  value: SortKey;
  active: boolean;
  onSelect: (value: SortKey) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      className={`inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.08em] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] ${
        active ? "text-[color:var(--ink)]" : "text-[color:var(--ink-2)] hover:text-[color:var(--ink)]"
      }`}
      aria-pressed={active}
    >
      {label}
      {active ? <span aria-hidden="true">↓</span> : null}
    </button>
  );
}

function CustomerRow({ customer }: { customer: Customer }) {
  const pending = customer.status === "pending_setup";
  // Per the spec, pending_setup rows carry a subtle amber tint so the
  // operator scans for "needs attention" at row-glance.
  const rowClass = pending
    ? "bg-[color:var(--amber-bg)]/40 hover:bg-[color:var(--amber-bg)]/60"
    : "transition-colors hover:bg-[color:var(--paper-2)]";
  return (
    <tr className={rowClass}>
      <td className="px-4 py-3">
        <Link
          href={`/customers/${encodeURIComponent(customer.tenant_id)}`}
          className="font-display text-[15px] font-normal text-[color:var(--ink)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
        >
          {customer.display_name ?? customer.tenant_id}
        </Link>
      </td>
      <td className="px-4 py-3">
        <StatusDot
          variant={STATUS_VARIANT[customer.status]}
          label={STATUS_LABEL[customer.status]}
        />
      </td>
      <td className="px-4 py-3">
        <CoverageRollupCell tenant_id={customer.tenant_id} />
      </td>
      <td className="px-4 py-3 text-[color:var(--ink-2)]">
        {customer.last_seen_at ? formatRelativeTime(customer.last_seen_at) : "—"}
      </td>
      <td className="px-4 py-3 text-[color:var(--ink)]">
        {(customer.decision_count_30d ?? 0).toLocaleString()}
      </td>
      <td className="px-4 py-3">
        <StatusDot
          variant={BAA_VARIANT[customer.baa_status]}
          label={BAA_LABEL[customer.baa_status]}
        />
      </td>
    </tr>
  );
}

// Lazy-load the per-customer agents call for the AI coverage rollup. The
// list endpoint doesn't embed the rollup itself; embedding would require
// joining customer_agents server-side and would muddy the cache shape.
// The per-row query is cheap (LIMIT 1 capture check + small ORM read)
// and React Query dedupes when multiple rows hit the same key.
import { useCustomerAgents } from "@/hooks/use-customers";

function CoverageRollupCell({ tenant_id }: { tenant_id: string }) {
  const { data, isLoading } = useCustomerAgents(tenant_id, true);
  if (isLoading) {
    return (
      <span className="inline-flex items-center text-[color:var(--ink-3)]">
        <Loading.Spinner size={12} label="Loading coverage" />
      </span>
    );
  }
  return <CoverageMatrixCompact agents={data?.items ?? []} />;
}
