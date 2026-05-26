"use client";

/**
 * ReviewInboxCard — one row in the clinician's Review Inbox.
 *
 * Shows the redacted context Vera sent over the wire (diagnoses,
 * orders, risk tier, required role) plus the local timestamps. The
 * Approve / Reject buttons route through the backend which then calls
 * Vera's `complete_review` SDK helper — the call is recorded on the
 * audit chain via the SDK, not raw HTTP.
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RiskPill } from "@/components/ui/risk-pill";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { ReviewInboxItem, RiskTier } from "@/lib/api/types";

interface ReviewInboxCardProps {
  item: ReviewInboxItem;
  isDeciding: boolean;
  onDecide(approvalId: string, decision: "approve" | "reject", note: string | undefined): void;
}

export function ReviewInboxCard({
  item,
  isDeciding,
  onDecide,
}: ReviewInboxCardProps) {
  const [note, setNote] = React.useState<string>("");
  const ctx = (item.context_excerpt ?? {}) as {
    diagnoses?: unknown;
    medication_orders?: unknown;
    lab_or_imaging_orders?: unknown;
  };

  const diagnoses = Array.isArray(ctx.diagnoses)
    ? (ctx.diagnoses.filter((v) => typeof v === "string") as string[])
    : [];
  const meds = Array.isArray(ctx.medication_orders)
    ? (ctx.medication_orders.filter((v) => typeof v === "string") as string[])
    : [];
  const labs = Array.isArray(ctx.lab_or_imaging_orders)
    ? (ctx.lab_or_imaging_orders.filter((v) => typeof v === "string") as string[])
    : [];

  const tier: RiskTier = (item.risk_tier as RiskTier | null) ?? "medium";
  const disabled = isDeciding || item.status !== "pending";

  const handleApprove = () => {
    if (disabled) return;
    onDecide(item.approval_id, "approve", note.trim() || undefined);
  };
  const handleReject = () => {
    if (disabled) return;
    onDecide(item.approval_id, "reject", note.trim() || undefined);
  };

  const statusBadge = (() => {
    if (item.status === "pending") {
      return (
        <Badge variant="cobalt" size="sm" aria-label="Pending clinician review">
          Awaiting clinician review
        </Badge>
      );
    }
    if (item.status === "approved") {
      return (
        <Badge variant="sage" size="sm">
          Approved
        </Badge>
      );
    }
    if (item.status === "rejected") {
      return (
        <Badge variant="coral" size="sm">
          Rejected
        </Badge>
      );
    }
    return (
      <Badge variant="amber" size="sm">
        Expired
      </Badge>
    );
  })();

  return (
    <Card
      elevation="md"
      tone={item.status === "pending" ? "cobalt" : "neutral"}
      data-testid="review-inbox-card"
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              {item.agent_name ?? "scribe"} · {item.action_name ?? "review"}
            </span>
            <CardTitle className="text-lg">
              {diagnoses[0] ?? "Pending HITL review"}
            </CardTitle>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1.5">
              {statusBadge}
              {item.required_role && (
                <Badge variant="outline" size="sm">
                  requires {item.required_role.replace(/_/g, " ")}
                </Badge>
              )}
              {item.data_subject_id && (
                <span className="font-mono text-[11px] text-[var(--ink-3)]">
                  subject {item.data_subject_id}
                </span>
              )}
            </div>
          </div>
          <RiskPill tier={tier} />
        </div>
      </CardHeader>

      <CardContent>
        <div className="grid gap-4 sm:grid-cols-3">
          <OrderList title="Diagnoses" items={diagnoses} />
          <OrderList title="Medication orders" items={meds} />
          <OrderList title="Labs / imaging" items={labs} />
        </div>

        <div className="mt-4 font-mono text-[11px] text-[var(--ink-3)]">
          <span>review</span>{" "}
          <span className="rounded-md bg-[var(--paper-2)] px-1.5 py-0.5">
            {item.approval_id}
          </span>
          {item.requested_at && (
            <span className="ml-3">requested {formatTs(item.requested_at)}</span>
          )}
          {item.expires_at && (
            <span className="ml-3">expires {formatTs(item.expires_at)}</span>
          )}
        </div>

        {item.status !== "pending" && item.decided_by && (
          <p className="mt-3 font-sans text-sm text-[var(--ink-2)]">
            Decided by <strong>{item.decided_by}</strong>
            {item.decided_at ? ` · ${formatTs(item.decided_at)}` : ""}
            {item.decision_note ? ` — “${item.decision_note}”` : ""}
          </p>
        )}

        {item.status === "pending" && (
          <div className="mt-5 flex flex-col gap-3">
            <Textarea
              placeholder="Optional note for the audit trail…"
              rows={2}
              value={note}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setNote(e.target.value)
              }
              maxLength={2000}
              data-testid="review-note"
            />
            <div className="flex flex-wrap items-center justify-end gap-3">
              <Button
                variant="destructive"
                size="md"
                onClick={handleReject}
                disabled={disabled}
                data-testid="review-reject"
              >
                Reject
              </Button>
              <Button
                variant="primary"
                size="md"
                onClick={handleApprove}
                disabled={disabled}
                data-testid="review-approve"
              >
                {isDeciding ? "Saving…" : "Approve"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function OrderList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="font-sans text-xs font-semibold uppercase tracking-wide text-[var(--ink-2)]">
        {title}
      </h4>
      {items.length === 0 ? (
        <p className="mt-1 font-sans text-sm italic text-[var(--ink-3)]">
          None.
        </p>
      ) : (
        <ul className={cn("mt-1.5 flex flex-col gap-1")}>
          {items.map((label, idx) => (
            <li
              key={`${label}-${idx}`}
              className="rounded-lg bg-[var(--paper-2)] px-2.5 py-1.5 font-sans text-sm text-[var(--ink)]"
            >
              {label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}
