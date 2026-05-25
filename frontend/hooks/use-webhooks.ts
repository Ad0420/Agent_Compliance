"use client";

/**
 * Webhook data hooks (Phase 2 Wave 2C PR C3).
 *
 * Backed by:
 *   - `GET /v1/webhooks` (subscription list)
 *   - `GET /v1/webhooks/{id}/deliveries` (recent deliveries + attempts)
 *   - `POST /v1/webhooks/{id}/deliveries/{delivery_id}/replay` (manual
 *      re-queue of an aborted delivery)
 *
 * All endpoints require the `admin` permission server-side. The dashboard
 * uses Clerk session auth (E4); the SDK uses API keys. Both flows hit the
 * same `require_permission("admin")` dependency.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  getWebhookDeliveries,
  getWebhooks,
  replayWebhookDelivery,
} from "@/lib/api-client";
import type {
  WebhookDeliveriesQueryParams,
  WebhookDeliveriesResponse,
  WebhookDeliveryReplayResponse,
  WebhookListResponse,
} from "@/lib/api-types";

// Query-key shape:
//   ["webhooks", "list"]
//   ["webhooks", "deliveries", id, params]
// Single namespace lets a replay invalidate the deliveries bucket cleanly.
export function useWebhooks() {
  return useQuery<WebhookListResponse>({
    queryKey: ["webhooks", "list"],
    queryFn: () => getWebhooks(),
    staleTime: 30_000,
  });
}

export function useWebhookDeliveries(
  webhook_id: string,
  params?: WebhookDeliveriesQueryParams,
  enabled = true,
) {
  return useQuery<WebhookDeliveriesResponse>({
    queryKey: ["webhooks", "deliveries", webhook_id, params],
    queryFn: () => getWebhookDeliveries(webhook_id, params),
    enabled: !!webhook_id && enabled,
    // The panel auto-refreshes every 30s so an operator who just hit
    // Replay sees the new attempt land without manual refresh. 30s is
    // long enough to avoid hammering the backend on a tab left open.
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useReplayWebhookDelivery(webhook_id: string) {
  const qc = useQueryClient();
  return useMutation<WebhookDeliveryReplayResponse, Error, string>({
    mutationFn: (delivery_id: string) =>
      replayWebhookDelivery(webhook_id, delivery_id),
    onSuccess: () => {
      // Refetch deliveries for this subscription so the row's status
      // flips from "aborted" to "pending" in the UI.
      qc.invalidateQueries({
        queryKey: ["webhooks", "deliveries", webhook_id],
      });
    },
  });
}
