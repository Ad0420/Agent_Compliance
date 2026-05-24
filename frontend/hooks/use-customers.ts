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
export function useCustomers(params?: CustomerQueryParams) {
  return useQuery({
    queryKey: ["customers", params],
    queryFn: () => getCustomers(params),
    staleTime: 30_000,
  });
}

export function useCustomer(tenant_id: string) {
  return useQuery({
    queryKey: ["customers", tenant_id],
    queryFn: () => getCustomer(tenant_id),
    enabled: !!tenant_id,
  });
}
