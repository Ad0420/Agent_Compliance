"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getPolicies,
  createPolicy,
  updatePolicy,
  deletePolicy,
  getViolations,
  resolveViolation,
} from "@/lib/api-client";
import type { PolicyCreateInput, PolicyUpdateInput, ViolationQueryParams } from "@/lib/api-types";

export function usePolicies(is_active?: boolean) {
  return useQuery({
    queryKey: ["policies", is_active],
    queryFn: () => getPolicies(is_active),
    staleTime: 30_000,
  });
}

export function useCreatePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: PolicyCreateInput) => createPolicy(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
}

export function useUpdatePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PolicyUpdateInput }) => updatePolicy(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
}

export function useDeletePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePolicy(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
}

export function useViolations(params?: ViolationQueryParams) {
  return useQuery({
    queryKey: ["violations", params],
    queryFn: () => getViolations(params),
    staleTime: 15_000,
  });
}

export function useResolveViolation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, resolved_by }: { id: string; resolved_by?: string }) =>
      resolveViolation(id, resolved_by),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["violations"] }),
  });
}
