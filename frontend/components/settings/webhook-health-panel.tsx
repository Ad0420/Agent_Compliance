"use client";

/**
 * WebhookHealthPanel — Phase 2 Wave 2C PR C3.
 *
 * Sits inside a Settings → Integrations webhook subscription card and
 * surfaces operator-grade signal that the endpoint is healthy: a status
 * line, a quartet of stats over the last 24h, and an expandable accordion
 * of the most recent deliveries with per-row Replay for aborts.
 *
 * Health classification (24h window):
 *   - `info`  — zero deliveries in window → "Idle"
 *   - `error` — any aborted deliveries → "Failing"
 *   - `warn`  — any attempt_count > 1 (retries occurred) → "Degraded"
 *   - `ok`    — everything succeeded first try → "Healthy"
 *
 * Auto-refreshes via the `useWebhookDeliveries` hook (refetchInterval),
 * so an operator who just hit Replay sees forward progress without a
 * manual reload.
 */

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { Loading } from "@/components/ui/loading";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import {
  useReplayWebhookDelivery,
  useWebhookDeliveries,
} from "@/hooks/use-webhooks";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { WebhookDelivery } from "@/lib/api-types";

import { WebhookDeliveryRow } from "./webhook-delivery-row";

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

export interface HealthStats {
  /** All deliveries created in the last 24h, any status. */
  total: number;
  /** Terminal deliveries in the last 24h (succeeded + aborted). The
   *  success-rate denominator — excludes in-flight so an endpoint with
   *  several pending deliveries doesn't read as "67%". */
  terminal: number;
  succeeded: number;
  retried: number;
  pending: number;
  aborted: number;
  /** Percentage succeeded out of *terminal* deliveries, or null when no
   *  terminal deliveries in window. */
  successRatePct: number | null;
  lastSuccess: { at: string; statusCode: number | null } | null;
}

export interface HealthClassification {
  variant: StatusVariant;
  label: string;
}

/**
 * Reduce a delivery list (newest-first, last 24h plus older for context)
 * to the scalar stats shown in the panel header.
 *
 * Exported for test reuse.
 */
export function computeHealthStats(
  deliveries: WebhookDelivery[],
  now: number = Date.now(),
): HealthStats {
  const cutoff = now - ONE_DAY_MS;
  const recent = deliveries.filter((d) => {
    const created = new Date(d.created_at).getTime();
    return Number.isFinite(created) && created >= cutoff;
  });

  let succeeded = 0;
  let retried = 0;
  let pending = 0;
  let aborted = 0;
  for (const d of recent) {
    if (d.status === "succeeded") succeeded += 1;
    if (d.status === "aborted") aborted += 1;
    if (d.status === "pending" && d.attempt_count > 1) pending += 1;
    if (d.attempt_count > 1 && d.status !== "aborted") retried += 1;
  }

  const total = recent.length;
  // Success rate denominator counts terminal deliveries only — including
  // in-flight rows would make a healthy endpoint with several pending
  // deliveries read as e.g. "67% (2/3)" until the sweeper catches up.
  const terminal = succeeded + aborted;
  const successRatePct =
    terminal === 0 ? null : Math.round((succeeded / terminal) * 100);

  // The "last delivery" line uses the most recent succeeded row, not just
  // the newest row of any status — operators care that the endpoint is
  // currently accepting traffic, and a string of pending/aborted rows is
  // not evidence of that.
  const lastSuccess = (() => {
    for (const d of deliveries) {
      if (d.status === "succeeded" && d.succeeded_at) {
        return {
          at: d.succeeded_at,
          statusCode: d.last_status_code,
        };
      }
    }
    return null;
  })();

  return {
    total,
    terminal,
    succeeded,
    retried,
    pending,
    aborted,
    successRatePct,
    lastSuccess,
  };
}

/**
 * Map stats to a single status indicator. The order matters: aborts
 * always beat retries, and retries always beat idle.
 *
 * Exported for test reuse.
 */
export function classifyHealth(stats: HealthStats): HealthClassification {
  if (stats.aborted > 0) {
    return {
      variant: "error",
      label: `Failing — ${stats.aborted} ${stats.aborted === 1 ? "abort" : "aborts"} in last 24h`,
    };
  }
  if (stats.retried > 0) {
    return {
      variant: "warn",
      label: `Degraded — ${stats.retried} ${stats.retried === 1 ? "retry" : "retries"} in last 24h`,
    };
  }
  if (stats.total === 0) {
    return {
      variant: "muted",
      label: "Idle — no traffic in last 24h",
    };
  }
  return { variant: "ok", label: "Healthy" };
}

export interface WebhookHealthPanelProps {
  webhookId: string;
  /**
   * Override "now" — only used by tests. Production reads system time.
   */
  now?: number;
  className?: string;
}

export function WebhookHealthPanel({
  webhookId,
  now,
  className,
}: WebhookHealthPanelProps) {
  // The backend caps `limit` at 200. A high-volume endpoint (>50/day)
  // would have its 24h window truncated at 50, deflating stats. Ask for
  // the max so the window has the best chance of being complete; the
  // accordion still only displays the 10 newest.
  const { data, isLoading, isError, error } = useWebhookDeliveries(webhookId, {
    limit: 200,
  });
  const replay = useReplayWebhookDelivery(webhookId);
  const [expanded, setExpanded] = React.useState(false);
  const accordionId = React.useId();

  if (isLoading) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 text-[13px] text-[color:var(--ink-2)]",
          className,
        )}
        aria-busy="true"
      >
        <Loading.Spinner label="Loading delivery health" />
        <span>Loading delivery health…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <p
        className={cn("text-[13px] text-[color:var(--ink-2)]", className)}
        role="alert"
      >
        Couldn&apos;t load delivery health
        {error instanceof Error ? ` — ${error.message}` : ""}.
      </p>
    );
  }

  const deliveries = data?.deliveries ?? [];
  const stats = computeHealthStats(deliveries, now);
  const health = classifyHealth(stats);
  // Show up to 10 most recent in the accordion to match the spec.
  const accordionDeliveries = deliveries.slice(0, 10);

  return (
    <section
      data-slot="webhook-health-panel"
      className={cn("flex flex-col gap-3", className)}
      aria-label="Delivery health"
    >
      <StatusDot variant={health.variant} label={health.label} />

      <dl
        className={cn(
          "grid grid-cols-2 gap-x-6 gap-y-1 text-[12px]",
          "sm:grid-cols-4",
        )}
      >
        <div>
          <dt className="text-[color:var(--ink-3)]">Last delivery</dt>
          <dd
            className="font-medium text-[color:var(--ink)] tabular-nums"
            title={stats.lastSuccess?.at ?? undefined}
          >
            {stats.lastSuccess ? (
              <>
                {formatRelativeTime(stats.lastSuccess.at)}
                {stats.lastSuccess.statusCode != null ? (
                  <>
                    {" "}
                    <span className="text-[color:var(--ink-2)]">
                      &middot; HTTP {stats.lastSuccess.statusCode}
                    </span>
                  </>
                ) : null}
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[color:var(--ink-3)]">24h success rate</dt>
          <dd className="font-medium text-[color:var(--ink)] tabular-nums">
            {stats.successRatePct == null ? (
              "—"
            ) : (
              <>
                {stats.successRatePct}%{" "}
                <span className="text-[color:var(--ink-2)]">
                  ({stats.succeeded}/{stats.terminal})
                </span>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[color:var(--ink-3)]">Retries pending</dt>
          <dd className="font-medium text-[color:var(--ink)] tabular-nums">
            {stats.pending}
          </dd>
        </div>
        <div>
          <dt className="text-[color:var(--ink-3)]">Aborted (24h)</dt>
          <dd className="font-medium text-[color:var(--ink)] tabular-nums">
            {stats.aborted}
          </dd>
        </div>
      </dl>

      {accordionDeliveries.length > 0 ? (
        <div>
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={accordionId}
            onClick={() => setExpanded((v) => !v)}
            className={cn(
              "inline-flex items-center gap-1 rounded-sm text-[12px] font-medium",
              "text-[color:var(--ink-2)] transition-colors hover:text-[color:var(--ink)]",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-[color:var(--ink)]",
            )}
          >
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "size-3 transition-transform",
                expanded && "rotate-180",
              )}
            />
            {expanded ? "Hide" : "Show"} recent deliveries (
            {accordionDeliveries.length})
          </button>
          {expanded ? (
            <ul
              id={accordionId}
              role="region"
              aria-label="Recent webhook deliveries"
              className="mt-2"
            >
              {accordionDeliveries.map((d) => {
                const isThisRow = replay.variables === d.id;
                return (
                  <WebhookDeliveryRow
                    key={d.id}
                    delivery={d}
                    onReplay={(deliveryId) => replay.mutate(deliveryId)}
                    isReplaying={replay.isPending && isThisRow}
                    replayError={
                      replay.isError && isThisRow && replay.error
                        ? replay.error.message
                        : null
                    }
                  />
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
