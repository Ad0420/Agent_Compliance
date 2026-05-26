"use client";

/**
 * Compliance posture data hook (Phase 4 Wave 2 PR C1).
 *
 * Wraps ``GET /v1/compliance/posture`` (Wave 1 B1). The endpoint
 * recomputes on demand and is non-trivial to evaluate (six dimensions
 * against the configured rolling window), so we hold a generous
 * client-side staleTime — the user is not expected to see posture move
 * minute-by-minute. The window selector callback invalidates by
 * changing the query key, not by manual invalidation.
 */

import { useQuery } from "@tanstack/react-query";

import {
  getCompliancePosture,
  type CompliancePostureResponse,
} from "@/lib/api-client";

export function useCompliancePosture(windowDays: number = 30) {
  return useQuery<CompliancePostureResponse>({
    queryKey: ["compliance", "posture", windowDays],
    queryFn: () => getCompliancePosture(windowDays),
    staleTime: 30_000,
  });
}
