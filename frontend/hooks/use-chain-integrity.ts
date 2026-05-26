"use client";

/**
 * useChainIntegrity — Phase 3 Wave 3D.1.
 *
 * Single-call aggregate for the Home page Chain Integrity tile. Cached
 * 60s (matches ``useChainVerification`` cadence) so the tile and the
 * topbar pill stay in sync on a refresh.
 */

import { useQuery } from "@tanstack/react-query";

import { getChainIntegrity } from "@/lib/api-client";

export function useChainIntegrity() {
  return useQuery({
    queryKey: ["chain-integrity"],
    queryFn: () => getChainIntegrity(),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
