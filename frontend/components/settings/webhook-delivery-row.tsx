"use client";

/**
 * WebhookDeliveryRow — Phase 2 Wave 2C PR C3.
 *
 * One row in the expandable delivery log inside `WebhookHealthPanel`.
 * Shows event_type / status / time / attempts / status code, and surfaces
 * a Replay button when the delivery is in a terminal "aborted" state.
 *
 * Replay UX is intentionally confirmation-gated: a misclick should never
 * silently re-fire a webhook that a downstream system has already paid
 * the price for failing. The dialog spells out the consequence.
 */

import * as React from "react";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Loading } from "@/components/ui/loading";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { WebhookDelivery, WebhookDeliveryStatus } from "@/lib/api-types";

const STATUS_VARIANT: Record<WebhookDeliveryStatus, StatusVariant> = {
  succeeded: "ok",
  pending: "muted",
  in_progress: "muted",
  aborted: "error",
};

const STATUS_LABEL: Record<WebhookDeliveryStatus, string> = {
  succeeded: "Delivered",
  pending: "Pending",
  in_progress: "Sending",
  aborted: "Aborted",
};

function pickTimestamp(d: WebhookDelivery): string {
  // Most-recent-meaningful timestamp: terminal time if terminal, else the
  // latest attempt time, else the row's created_at.
  if (d.succeeded_at) return d.succeeded_at;
  if (d.aborted_at) return d.aborted_at;
  const last = d.attempts[d.attempts.length - 1];
  if (last?.attempted_at) return last.attempted_at;
  return d.created_at;
}

function absoluteTooltip(iso: string): string {
  try {
    return format(new Date(iso), "MMM d, yyyy HH:mm:ss");
  } catch {
    return iso;
  }
}

export interface WebhookDeliveryRowProps {
  delivery: WebhookDelivery;
  onReplay: (delivery_id: string) => void;
  isReplaying: boolean;
}

export function WebhookDeliveryRow({
  delivery,
  onReplay,
  isReplaying,
}: WebhookDeliveryRowProps) {
  const variant = STATUS_VARIANT[delivery.status];
  const label = STATUS_LABEL[delivery.status];
  const ts = pickTimestamp(delivery);
  const isAborted = delivery.status === "aborted";
  const [open, setOpen] = React.useState(false);

  const handleConfirm = () => {
    onReplay(delivery.id);
    setOpen(false);
  };

  return (
    <li
      data-slot="webhook-delivery-row"
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-3",
        "border-b border-[color:var(--ink-4)] py-2.5 last:border-b-0",
        "text-[13px] text-[color:var(--ink)]",
      )}
    >
      <div className="min-w-0">
        <p className="truncate font-medium" title={delivery.event_type}>
          {delivery.event_type}
        </p>
        <p className="truncate font-mono text-[11px] text-[color:var(--ink-3)]">
          {delivery.id}
        </p>
      </div>
      <StatusDot variant={variant} label={label} />
      <time
        className="tabular-nums text-[color:var(--ink-2)]"
        dateTime={ts}
        title={absoluteTooltip(ts)}
      >
        {formatRelativeTime(ts)}
      </time>
      <span className="tabular-nums text-[color:var(--ink-2)]">
        {delivery.attempt_count} {delivery.attempt_count === 1 ? "attempt" : "attempts"}
      </span>
      <span className="tabular-nums text-[color:var(--ink-2)]">
        {delivery.last_status_code != null ? (
          <>HTTP {delivery.last_status_code}</>
        ) : (
          <span aria-label="No HTTP response yet">—</span>
        )}
      </span>

      {isAborted ? (
        <div className="col-span-5 mt-2 flex justify-end">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isReplaying}
              >
                {isReplaying ? (
                  <>
                    <Loading.Spinner aria-busy="true" />
                    Replaying…
                  </>
                ) : (
                  "Replay"
                )}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Replay delivery?</DialogTitle>
                <DialogDescription>
                  Vera will re-send <span className="font-mono text-xs">{delivery.event_type}</span>{" "}
                  to this endpoint immediately. The receiver should be
                  idempotent on the event id —{" "}
                  <span className="font-mono text-xs">{delivery.id}</span>.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline" size="sm">
                    Cancel
                  </Button>
                </DialogClose>
                <Button
                  type="button"
                  size="sm"
                  onClick={handleConfirm}
                  disabled={isReplaying}
                >
                  Replay now
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      ) : null}
    </li>
  );
}
