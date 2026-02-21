"use client";

import { useQuery } from "@tanstack/react-query";
import { getOrganization } from "@/lib/api-client";

export function useOrganization() {
  return useQuery({
    queryKey: ["organization"],
    queryFn: getOrganization,
    staleTime: 300_000,
  });
}
