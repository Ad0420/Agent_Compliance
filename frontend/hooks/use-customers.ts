"use client";

import { useQuery } from "@tanstack/react-query";
import { getCustomer, getCustomers } from "@/lib/api-client";
import type { CustomerQueryParams } from "@/lib/api-types";

/**
 * Customers list hook (Phase 1 PR 12).
 *
 * Backed by `GET /v1/customers` shipped in PR #195. Phase 1 PR 13 will
 * extend this surface with the Coverage Matrix; for now the Home page +
 * Customers stub list both consume the same shape.
 */
// Query-key shape: `["customers", "list", params]` / `["customers", "detail", id]`.
// The explicit "list"/"detail" segment lets us invalidate either bucket
// independently — `invalidateQueries({ queryKey: ["customers", "list"] })`
// refreshes the list without invalidating in-flight detail queries.
export function useCustomers(params?: CustomerQueryParams) {
  return useQuery({
    queryKey: ["customers", "list", params],
    queryFn: () => getCustomers(params),
    staleTime: 30_000,
  });
}

export function useCustomer(tenant_id: string) {
  return useQuery({
    queryKey: ["customers", "detail", tenant_id],
    queryFn: () => getCustomer(tenant_id),
    enabled: !!tenant_id,
  });
}
