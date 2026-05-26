"use client";

/**
 * /reviews — the clinician's in-band Review Inbox (W2.1).
 *
 * Surfaces every pending HITL approval that Vera has flagged for this
 * organization via the `approval.requested` / `review.requested`
 * webhook. The clinician clicks Approve/Reject; the backend calls
 * Vera's `complete_review` SDK helper and Vera's `review.completed`
 * webhook flips the row to terminal.
 *
 * No PHI shown beyond what Vera already exposed in the webhook
 * payload's redacted context — full notes live on the encounter page.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import {
  useDecideReview,
  useReviewInbox,
} from "@/hooks/use-review-inbox";
import type { ReviewListFilter } from "@/lib/api/types";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import { Topbar } from "@/components/ui/topbar";
import { ReviewInboxCard } from "@/components/reviews/review-inbox-card";

const FILTERS: { value: ReviewListFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
  { value: "all", label: "All" },
];

export default function ReviewInboxPage() {
  const { signedInAs, isLoading: authLoading } = useAuth();
  const router = useRouter();

  const [filter, setFilter] = React.useState<ReviewListFilter>("pending");
  const { items, isLoading, error, refetch } = useReviewInbox({ status: filter });
  const { decide, isDeciding, error: decideError } = useDecideReview();

  React.useEffect(() => {
    if (authLoading) return;
    if (!signedInAs) router.replace("/login");
  }, [authLoading, signedInAs, router]);

  const handleDecide = React.useCallback(
    (
      approvalId: string,
      decision: "approve" | "reject",
      note: string | undefined,
    ) => {
      void decide(approvalId, decision, note)
        .then(() => refetch())
        .catch(() => {
          // decideError captures the message; surfaced below.
        });
    },
    [decide, refetch],
  );

  if (authLoading || !signedInAs) {
    return (
      <div className="min-h-screen bg-[var(--paper)] flex items-center justify-center">
        <StatusDot status="running" label="Loading" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--paper)]">
      <Topbar
        signedInAs={{ name: signedInAs }}
        centerSlot={
          <StatusDot
            status={items.length > 0 ? "waiting" : "running"}
            label={
              items.length > 0
                ? `${items.length} pending review${items.length === 1 ? "" : "s"}`
                : "Review Inbox"
            }
          />
        }
      />

      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="font-display text-2xl text-[var(--ink)]">
              Review Inbox
            </h1>
            <p className="mt-1 font-sans text-sm text-[var(--ink-3)]">
              AI-drafted orders held for attending review. Decisions land
              on the audit chain via Vera.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <Button
                key={f.value}
                variant={filter === f.value ? "primary" : "secondary"}
                size="sm"
                onClick={() => setFilter(f.value)}
                data-testid={`filter-${f.value}`}
              >
                {f.label}
              </Button>
            ))}
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-4 rounded-xl bg-[var(--coral-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--coral)] ring-1 ring-inset ring-[rgba(180,35,24,0.22)]"
          >
            {error.message}
          </div>
        )}
        {decideError && (
          <div
            role="alert"
            className="mb-4 rounded-xl bg-[var(--coral-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--coral)] ring-1 ring-inset ring-[rgba(180,35,24,0.22)]"
          >
            {decideError.message}
          </div>
        )}

        {isLoading && items.length === 0 && (
          <Card elevation="sm">
            <CardContent>
              <p className="font-sans text-sm text-[var(--ink-3)]">
                Loading…
              </p>
            </CardContent>
          </Card>
        )}

        {!isLoading && items.length === 0 && (
          <Card elevation="sm">
            <CardHeader>
              <CardTitle className="text-lg">Nothing waiting</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-sans text-sm text-[var(--ink-3)]">
                {filter === "pending"
                  ? "No AI-drafted orders are waiting for your review right now."
                  : "Nothing in this view."}
              </p>
            </CardContent>
          </Card>
        )}

        <div className="flex flex-col gap-4">
          {items.map((item) => (
            <ReviewInboxCard
              key={item.approval_id}
              item={item}
              isDeciding={isDeciding}
              onDecide={handleDecide}
            />
          ))}
        </div>
      </main>
    </div>
  );
}
