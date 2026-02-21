"use client";

import { useQuery } from "@tanstack/react-query";
import { getAgents, getAgent } from "@/lib/api-client";

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: getAgents,
    staleTime: 60_000,
  });
}

export function useAgent(id: string) {
  return useQuery({
    queryKey: ["agents", id],
    queryFn: () => getAgent(id),
    enabled: !!id,
  });
}
