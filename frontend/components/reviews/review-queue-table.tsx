"use client";

/**
 * ReviewQueueTable — Wave 2D PR C2.
 *
 * Org-wide table of all decisions in PENDING_REVIEW state. Filter bar
 * (Customer / Gate / Required role) at the top + table below. Click a
 * row to open the right-side detail panel (Pattern B layout, owned by
 * the page).
 *
 * Filtering happens client-side against the cached approvals page so
 * chip changes are instantaneous and don't trigger a refetch. The
 * backend only filters by ``status=pending`` + risk_tier (today); the
 * three UI filters here narrow the visible set without a round-trip.
 */

import * as React from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import { ReviewQueueRow } from "./review-queue-row";
import type { Approval, Customer } from "@/lib/api-types";

const ALL = "__all__";

export interface ReviewQueueTableProps {
  approvals: Approval[];
  /**
   * Map of ``data_subject_id`` → Customer for display-name resolution.
   * The Customers endpoint indexes by ``tenant_id`` (Phase 1 PR 2); the
   * Approval's ``data_subject_id`` and Customer's ``tenant_id`` share
   * the same identifier space when the customer was auto-discovered
   * from agent decisions. Caller passes the lookup; this component
   * doesn't fetch.
   */
  customersByTenantId?: Record<string, Customer>;
  /** Currently-selected row id (for highlight + detail panel sync). */
  selectedReviewId?: string | null;
  onSelect?: (approval: Approval) => void;
  /** Total queue size from the server (for the row count line). */
  total: number;
  /** True while React Query is fetching/refetching the queue. */
  isLoading?: boolean;
  isError?: boolean;
  error?: Error | null;
}

interface FilterState {
  customer: string;
  gate: string;
  role: string;
}

function extractGateName(a: Approval): string | null {
  const v = (a.context as { gate_name?: unknown }).gate_name;
  return typeof v === "string" && v.length > 0 ? v : null;
}

function extractRequiredRole(a: Approval): string | null {
  const v = (a.context as { required_role?: unknown }).required_role;
  return typeof v === "string" && v.length > 0 ? v : null;
}

export function ReviewQueueTable({
  approvals,
  customersByTenantId,
  selectedReviewId,
  onSelect,
  total,
  isLoading,
  isError,
  error,
}: ReviewQueueTableProps) {
  const [filters, setFilters] = React.useState<FilterState>({
    customer: ALL,
    gate: ALL,
    role: ALL,
  });

  // ── Derive filter options from the current queue. Keeps the chips
  // honest — only filter values that actually appear in the queue are
  // selectable. Sorted for stable rendering across refetches.
  const customerOptions = React.useMemo(() => {
    const set = new Set<string>();
    for (const a of approvals) {
      if (a.data_subject_id) set.add(a.data_subject_id);
    }
    return Array.from(set).sort();
  }, [approvals]);

  const gateOptions = React.useMemo(() => {
    const set = new Set<string>();
    for (const a of approvals) {
      const g = extractGateName(a);
      if (g) set.add(g);
    }
    return Array.from(set).sort();
  }, [approvals]);

  const roleOptions = React.useMemo(() => {
    const set = new Set<string>();
    for (const a of approvals) {
      const r = extractRequiredRole(a);
      if (r) set.add(r);
    }
    return Array.from(set).sort();
  }, [approvals]);

  // ── Apply filters in a single pass. All three chips AND together.
  const visible = React.useMemo(() => {
    return approvals.filter((a) => {
      if (filters.customer !== ALL && a.data_subject_id !== filters.customer)
        return false;
      if (filters.gate !== ALL && extractGateName(a) !== filters.gate)
        return false;
      if (filters.role !== ALL && extractRequiredRole(a) !== filters.role)
        return false;
      return true;
    });
  }, [approvals, filters]);

  if (isLoading && approvals.length === 0) {
    return (
      <div
        aria-busy="true"
        className="flex justify-center py-10 text-[color:var(--ink-3)]"
        data-testid="review-queue-loading"
      >
        <Loading.Spinner size={20} label="Loading pending reviews" />
      </div>
    );
  }

  if (isError) {
    return (
      <div
        role="alert"
        className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--brick-bg)] px-5 py-4 text-[14px] text-[color:var(--ink)]"
        data-testid="review-queue-error"
      >
        <p className="font-medium">Reviews could not be loaded.</p>
        <p className="mt-1 text-[13px] text-[color:var(--ink-2)]">
          {error?.message ??
            "Refresh the page. If the problem persists, contact support."}
        </p>
      </div>
    );
  }

  if (approvals.length === 0) {
    return (
      <div data-testid="review-queue-empty">
        <EmptyState
          title="No pending reviews"
          subtitle="When agents need human approval, they'll appear here."
        />
      </div>
    );
  }

  const selectOnChange =
    (key: keyof FilterState) =>
    (e: React.ChangeEvent<HTMLSelectElement>) =>
      setFilters((f) => ({ ...f, [key]: e.target.value }));

  return (
    <section
      aria-label="Pending reviews"
      data-testid="review-queue-loaded"
      className="space-y-3"
    >
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] px-4 py-3">
        <FilterSelect
          label="Customer"
          value={filters.customer}
          options={customerOptions}
          customersByTenantId={customersByTenantId}
          onChange={selectOnChange("customer")}
          testId="review-queue-filter-customer"
        />
        <FilterSelect
          label="Gate"
          value={filters.gate}
          options={gateOptions}
          onChange={selectOnChange("gate")}
          testId="review-queue-filter-gate"
        />
        <FilterSelect
          label="Required role"
          value={filters.role}
          options={roleOptions}
          onChange={selectOnChange("role")}
          testId="review-queue-filter-role"
        />
        <p className="ml-auto text-[12px] text-[color:var(--ink-3)] tabular-nums">
          Showing {visible.length.toLocaleString()} of {total.toLocaleString()}{" "}
          pending
        </p>
      </div>

      {visible.length === 0 ? (
        <div data-testid="review-queue-filter-empty">
          <EmptyState
            title="No reviews match your filters"
            subtitle="Adjust the filters above to see the full queue."
          />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)]">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead className="bg-[color:var(--paper-2)]">
              <tr className="border-b border-[color:var(--ink-4)]">
                <Th>Risk</Th>
                <Th>Requested</Th>
                <Th>Customer</Th>
                <Th>Agent</Th>
                <Th>Action</Th>
                <Th>Gate</Th>
                <Th>Required role</Th>
                <Th>Expires in</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => (
                <ReviewQueueRow
                  key={a.id}
                  approval={a}
                  customerDisplayName={
                    a.data_subject_id
                      ? customersByTenantId?.[a.data_subject_id]?.display_name
                      : null
                  }
                  selected={selectedReviewId === a.id}
                  onSelect={onSelect}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface FilterSelectProps {
  label: string;
  value: string;
  options: string[];
  customersByTenantId?: Record<string, Customer>;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  testId: string;
}

function FilterSelect({
  label,
  value,
  options,
  customersByTenantId,
  onChange,
  testId,
}: FilterSelectProps) {
  // Native <select> keeps the bundle small + accessible by default;
  // dashboard-design-system.md §Filter chips allows native controls
  // wherever a custom Radix popover would add noise without benefit.
  return (
    <label className="flex items-center gap-2 text-[12px] text-[color:var(--ink-2)]">
      <span className="font-medium uppercase tracking-[0.06em]">{label}</span>
      <select
        value={value}
        onChange={onChange}
        data-testid={testId}
        className="h-8 rounded-[6px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-2 text-[13px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
      >
        <option value={ALL}>All</option>
        {options.map((opt) => {
          const display =
            customersByTenantId?.[opt]?.display_name &&
            customersByTenantId[opt].display_name !== opt
              ? `${customersByTenantId[opt].display_name} (${opt})`
              : opt;
          return (
            <option key={opt} value={opt}>
              {display}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2 text-[11px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-3)]">
      {children}
    </th>
  );
}
