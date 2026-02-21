"use client";

import { useQuery } from "@tanstack/react-query";
import { verifyChain, verifyRecord } from "@/lib/api-client";

export function useChainVerification() {
  return useQuery({
    queryKey: ["chain-verification"],
    queryFn: () => verifyChain(),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function useRecordVerification(id: string) {
  return useQuery({
    queryKey: ["record-verification", id],
    queryFn: () => verifyRecord(id),
    enabled: !!id,
  });
}
