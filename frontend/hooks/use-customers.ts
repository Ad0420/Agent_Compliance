"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  getCustomer,
  getCustomerAgents,
  getCustomers,
  patchCustomer,
  uploadCustomerBaa,
  type CustomerPatchInput,
} from "@/lib/api-client";
import type {
  BAAUploadInput,
  BAAUploadResponse,
  Customer,
  CustomerAgentsResponse,
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
