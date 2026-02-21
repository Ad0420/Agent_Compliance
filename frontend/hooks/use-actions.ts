"use client";

import { useQuery } from "@tanstack/react-query";
import { getActions, getAction } from "@/lib/api-client";
import type { ActionQueryParams } from "@/lib/api-types";

export function useActions(params?: ActionQueryParams) {
  return useQuery({
    queryKey: ["actions", params],
    queryFn: () => getActions(params),
    staleTime: 30_000,
  });
}

export function useAction(id: string) {
  return useQuery({
    queryKey: ["actions", id],
    queryFn: () => getAction(id),
    enabled: !!id,
  });
}
