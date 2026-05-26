"use client";

/**
 * Off-Vera S3 mirror data hooks (Phase 3 Wave 3D.3).
 *
 * Backed by:
 *   - GET    /v1/dashboard/s3-export-config      (current ARN + counts + recent)
 *   - PUT    /v1/dashboard/s3-export-arn         (admin set/update)
 *   - DELETE /v1/dashboard/s3-export-arn         (admin clear)
 *   - POST   /v1/dashboard/s3-export-arn/validate (admin pure validation)
 *   - POST   /v1/dashboard/s3-export-arn/probe    (admin trust probe, gated)
 *
 * Read is admin + developer (developers debug SDK integration); write is
 * admin-only. The hooks don't enforce RBAC client-side — that's an
 * authoritative server check — but mutations gated behind admin-only UI
 * never fire for non-admin sessions.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  clearS3MirrorArn,
  getS3MirrorConfig,
  probeS3MirrorArn,
  updateS3MirrorArn,
  validateS3MirrorArn,
} from "@/lib/api-client";
import type {
  S3MirrorConfig,
  S3MirrorValidateInput,
  S3MirrorValidateResponse,
} from "@/lib/api-types";

const QUERY_KEY = ["s3-mirror", "config"] as const;

export function useS3MirrorConfig() {
  return useQuery<S3MirrorConfig>({
    queryKey: QUERY_KEY,
    queryFn: () => getS3MirrorConfig(),
    // Config rarely changes; recent-exports table benefits from a slow
    // background refresh so the row counts and last-success time stay
    // close-to-fresh without hammering the API.
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useUpdateS3MirrorArn() {
  const qc = useQueryClient();
  return useMutation<S3MirrorConfig, Error, string>({
    mutationFn: (arn: string) => updateS3MirrorArn(arn),
    onSuccess: (data) => {
      // The PUT response is shaped like the GET response, so we can
      // hydrate the cache directly and skip a follow-up fetch.
      qc.setQueryData(QUERY_KEY, data);
    },
  });
}

export function useClearS3MirrorArn() {
  const qc = useQueryClient();
  return useMutation<S3MirrorConfig, Error, void>({
    mutationFn: () => clearS3MirrorArn(),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
    },
  });
}

export function useValidateS3MirrorArn() {
  return useMutation<S3MirrorValidateResponse, Error, S3MirrorValidateInput>({
    mutationFn: (input) => validateS3MirrorArn(input),
  });
}

export function useProbeS3MirrorArn() {
  return useMutation<S3MirrorValidateResponse, Error, S3MirrorValidateInput>({
    mutationFn: (input) => probeS3MirrorArn(input),
  });
}
