"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCheckpoints, createCheckpoint, verifyAllCheckpoints } from "@/lib/api-client";

export function useCheckpoints() {
  return useQuery({
    queryKey: ["checkpoints"],
    queryFn: getCheckpoints,
    staleTime: 30_000,
  });
}

export function useCreateCheckpoint() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createCheckpoint,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checkpoints"] });
    },
  });
}

export function useVerifyCheckpoints() {
  return useMutation({
    mutationFn: verifyAllCheckpoints,
  });
}
