"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  getAuditPdfHistory,
  getCustomer,
  getCustomerAgents,
  getCustomerChainSummary,
  getCustomerDecisions,
  getCustomers,
  patchCustomer,
  uploadCustomerBaa,
  type AuditPdfHistoryQueryParams,
  type AuditPdfHistoryResponse,
  type CustomerPatchInput,
} from "@/lib/api-client";
import type {
  BAAUploadInput,
  BAAUploadResponse,
  Customer,
  CustomerAgentsResponse,
  CustomerChainSummary,
  CustomerDecisionsQueryParams,
  CustomerDecisionsResponse,
  CustomerQueryParams,
} from "@/lib/api-types";

/**
 * Customers data hooks (Phase 1 PR 12 + PR 13).
 *
 * Backed by `GET /v1/customers` (shipped in PR #195) and the PR 13
 * additions: `GET /v1/customers/{tenant_id}/agents` (AI Coverage Matrix)
 * + `POST /v1/customers/{tenant_id}/baa` (Phase 1 acceptance gate).
 */
// Query-key shape: `["customers", "list", params]` / `["customers", "detail", id]`
// / `["customers", "agents", id]`. The explicit segment lets us invalidate
// individual buckets without nuking in-flight detail queries.
export function useCustomers(params?: CustomerQueryParams) {
  return useQuery({
    queryKey: ["customers", "list", params],
    queryFn: () => getCustomers(params),
    staleTime: 30_000,
  });
}

export function useCustomer(tenant_id: string) {
  return useQuery<Customer>({
    queryKey: ["customers", "detail", tenant_id],
    queryFn: () => getCustomer(tenant_id),
    enabled: !!tenant_id,
  });
}

export function useCustomerAgents(tenant_id: string, enabled = true) {
  return useQuery<CustomerAgentsResponse>({
    queryKey: ["customers", "agents", tenant_id],
    queryFn: () => getCustomerAgents(tenant_id),
    // Disabled by default for pending_setup customers (no agents to show
    // until decisions flow in) — caller passes `enabled` based on the
    // detail page's variant decision.
    enabled: !!tenant_id && enabled,
  });
}

export function usePatchCustomer(tenant_id: string) {
  const qc = useQueryClient();
  return useMutation<Customer, Error, CustomerPatchInput>({
    mutationFn: (input) => patchCustomer(tenant_id, input),
    onSuccess: (updated) => {
      // Seed the detail cache so the inline form re-renders without a
      // round-trip, and invalidate the list so the row picks up the new
      // display_name / contact fields on next visit.
      qc.setQueryData(["customers", "detail", tenant_id], updated);
      qc.invalidateQueries({ queryKey: ["customers", "list"] });
    },
  });
}

// Wave 2C PR C1 — Customer detail Decisions tab.
//
// Auto-refreshes while any decision has a non-terminal webhook delivery
// (pending or retrying) so the operator sees retries land without a
// manual reload. Idle once all deliveries reach a terminal state.
export function useCustomerDecisions(
  tenant_id: string,
  params?: CustomerDecisionsQueryParams,
  enabled = true,
) {
  return useQuery<CustomerDecisionsResponse>({
    queryKey: ["customers", "decisions", tenant_id, params],
    queryFn: () => getCustomerDecisions(tenant_id, params),
    enabled: !!tenant_id && enabled,
    staleTime: 10_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasInFlight = data.decisions.some(
        (d) =>
          d.webhook_delivery?.status === "pending" ||
          d.webhook_delivery?.status === "retrying",
      );
      return hasInFlight ? 15_000 : false;
    },
  });
}

// Wave 3D.2 — Customer Verification & Evidence Trail panel.
//
// Powers the per-customer "Latest checkpoint covering this customer"
// summary + 30-day timeline strip + the gate that enables the inline
// "Verify this customer's chain" button. The query keys carry the
// tenant_id so React Query's cache holds independent snapshots per
// customer; the panel sits on the Overview tab, so we keep it cheap by
// disabling auto-refetch and only invalidate on demand.
export function useCustomerChainSummary(
  tenant_id: string,
  enabled = true,
) {
  return useQuery<CustomerChainSummary>({
    queryKey: ["customers", "chain-summary", tenant_id],
    queryFn: () => getCustomerChainSummary(tenant_id),
    enabled: !!tenant_id && enabled,
    // 60s staleness — checkpoints don't seal more often than the
    // configured cadence (default hourly for live keys), so a minute is
    // a generous "fresh" window. The user can also hit the inline
    // Verify button to force a fresh round-trip when they want to see
    // the latest checkpoint immediately.
    staleTime: 60_000,
  });
}

// Phase 4 Wave 2 C4 — Generated audit PDFs history table.
//
// ``customer_id`` is the Customer's **primary key** (UUID), not the
// tenant_id slug. The list endpoint is paginated (limit/offset) and the
// history is append-only, so the data is highly cacheable: a stale read
// only misses a freshly-generated PDF. We use a short staleTime so the
// table updates promptly after the Generate modal completes, but no
// refetchInterval — no polling.
export function useAuditPdfHistory(
  customer_id: string,
  params?: AuditPdfHistoryQueryParams,
  enabled = true,
) {
  return useQuery<AuditPdfHistoryResponse>({
    queryKey: ["customers", "audit-pdf-history", customer_id, params],
    queryFn: () => getAuditPdfHistory(customer_id, params),
    enabled: !!customer_id && enabled,
    staleTime: 5_000,
  });
}

export function useUploadBaa(tenant_id: string) {
  const qc = useQueryClient();
  return useMutation<BAAUploadResponse, Error, BAAUploadInput>({
    mutationFn: (input) => uploadCustomerBaa(tenant_id, input),
    onSuccess: () => {
      // The BAA upload flips ``customer.status`` and ``customer.baa_status``
      // server-side; both list and detail caches need to be invalidated so
      // the dashboard re-renders the "populated" variant immediately.
      qc.invalidateQueries({ queryKey: ["customers", "detail", tenant_id] });
      qc.invalidateQueries({ queryKey: ["customers", "agents", tenant_id] });
      qc.invalidateQueries({ queryKey: ["customers", "list"] });
      // The Home page surfaces the org-wide BAA status banner from
      // `/v1/organizations/me/baa-status` — invalidate that too so the
      // "Resume setup" banner clears the moment the upload completes.
      qc.invalidateQueries({ queryKey: ["organization", "baa-status"] });
    },
  });
}
