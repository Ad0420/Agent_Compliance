"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getApprovals,
  getApproval,
  createApproval,
  decideApproval,
  cancelApproval,
} from "@/lib/api-client";
import type {
  ApprovalCreateInput,
  ApprovalDecisionInput,
  ApprovalQueryParams,
} from "@/lib/api-types";

export function useApprovals(params?: ApprovalQueryParams) {
  return useQuery({
    queryKey: ["approvals", params],
    queryFn: () => getApprovals(params),
    staleTime: 10_000,
    refetchInterval: (query) => {
      // Auto-refresh while there are pending approvals
      const data = query.state.data;
      const hasPending = data?.approvals.some((a) => a.status === "pending");
      return hasPending ? 5_000 : false;
    },
  });
}

export function useApproval(id: string | undefined) {
  return useQuery({
    queryKey: ["approval", id],
    queryFn: () => getApproval(id as string),
    enabled: !!id,
  });
}

export function useCreateApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ApprovalCreateInput) => createApproval(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

export function useDecideApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ApprovalDecisionInput }) =>
      decideApproval(id, input),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      queryClient.invalidateQueries({ queryKey: ["approval", variables.id] });
    },
  });
}

export function useCancelApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => cancelApproval(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      queryClient.invalidateQueries({ queryKey: ["approval", id] });
    },
  });
}
