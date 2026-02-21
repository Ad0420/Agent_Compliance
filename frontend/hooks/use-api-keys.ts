"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getApiKeys, createApiKeyRequest, revokeApiKey } from "@/lib/api-client";
import type { ApiKeyCreateInput } from "@/lib/api-types";

export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: getApiKeys,
    staleTime: 30_000,
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ApiKeyCreateInput) => createApiKeyRequest(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}
