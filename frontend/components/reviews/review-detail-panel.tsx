"use client";

/**
 * ReviewDetailPanel — Wave 2D PR C2 + W2.2 (read-only HIPAA hardening).
 *
 * Pattern B split work surface (per
 * dashboard-design-system.md §Layout patterns line 219+): the page wraps
 * the table in the left content area, and renders this panel as the
 * fixed-width right panel (360-420px) when a row is selected.
 *
 * W2.2 — Read-only metadata (HIPAA min-necessary)
 * ===============================================
 * The Vera dashboard is operated by AI-vendor staff (e.g. Abridge
 * employees), not the vendor's customers (hospital clinicians). Under
 * 45 CFR 164.502(b) minimum-necessary, vendor staff don't need to
 * authorize or reject agent decisions — that's the customer's
 * clinician's job, completed in-band via the customer's EHR (W2.1).
 *
 * This panel is therefore read-only metadata only:
 *
 *   ┌───────────────────────────────────────┐
 *   │ Risk badge + status header             │
 *   ├───────────────────────────────────────┤
 *   │ Decision context (gate metadata)       │
 *   │   - action_name + requesting agent     │
 *   │   - customer tenant_id                 │
 *   │   - gate_name + citation               │
 *   │   - required_role                      │
 *   │   - requested_at / expires_at          │
 *   │   - http/https fix_url (whitelisted)   │
 *   ├───────────────────────────────────────┤
 *   │ Status indicator (NOT an action box)   │
 *   │   - pending: "Waiting on customer EHR" │
 *   │   - resolved: status + role + when     │
 *   │   - expired: brick "Expired without    │
 *   │              callback"                 │
 *   └───────────────────────────────────────┘
 *
 * What we deliberately do NOT render
 * ----------------------------------
 *  * ``action_summary`` — backend strips it for dashboard callers
 *    (services/dashboard_views.py); the UI doesn't reference the field
 *    at all so a future serializer change can't accidentally leak PHI.
 *  * ``data_subject_id`` — same; stripped server-side. The customer
 *    tenant_id we DO render is the AI vendor's customer (hospital),
 *    not the patient.
 *  * ``reason_detail`` / ``input`` / arbitrary context blob — backend
 *    whitelists ``Approval.context`` to gate-metadata keys only; the
 *    UI doesn't attempt to read narrative fields off the context map
 *    so adding a PHI key to the whitelist by mistake would not leak
 *    through this panel.
 *  * Approve / Modify / Reject buttons — removed in W2.2. The HITL
 *    path is ScribeMD's in-band callback only.
 */

import * as React from "react";
import { X, ExternalLink } from "lucide-react";

import { SeverityBadge, type Severity } from "@/components/ui/severity-badge";
import {
  formatAbsoluteUTC,
  formatRelativeTime,
  formatTimeUntil,
} from "@/lib/utils";
import type { Approval, ApprovalStatus, RiskTier } from "@/lib/api-types";

const RISK_SEVERITY: Record<RiskTier, Severity> = {
  critical: "HIGH",
  high: "HIGH",
  medium: "MEDIUM",
  low: "LOW",
};

const RISK_LABEL: Record<RiskTier, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  medium: "MEDIUM",
  low: "LOW",
};

const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
  cancelled: "Cancelled",
};

function stringField(ctx: Record<string, unknown>, key: string): string | null {
  const v = ctx[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

/**
 * Whitelist URL schemes for the gate-pack-provided ``fix_url`` so a
 * compromised or buggy gate pack can't inject ``javascript:`` /
 * ``data:`` URIs that execute when a reviewer clicks the reference
 * link. ``Approval.context`` is a JSON blob written server-side by the
 * gate pack — the pack author is trusted by the org admin, but the
 * threat model includes a compromised pack scenario.
 *
 * Returns the URL when it parses as ``http://`` or ``https://``;
 * returns ``null`` otherwise so the caller can fall back to plain
 * text rendering.
 */
function safeHttpUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    if (u.protocol === "http:" || u.protocol === "https:") {
      return u.toString();
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Pull the most recent ``reviewer_role`` off the redacted decisions
 * list (see ``services/dashboard_views._redact_decision``). The
 * dashboard renders "Approved by attending_physician" without ever
 * touching the customer-side reviewer's identifier — that's left
 * stripped server-side for HIPAA min-necessary.
 *
 * Falls back to ``null`` for legacy votes whose ``approver`` field
 * didn't carry the role half (pre-W2.1 decisions written through the
 * legacy ``/v1/approvals/{id}/decide`` route).
 */
function latestReviewerRole(
  decisions: Approval["decisions"],
): string | null {
  for (let i = decisions.length - 1; i >= 0; i -= 1) {
    const vote = decisions[i];
    if (typeof vote.reviewer_role === "string" && vote.reviewer_role.length > 0) {
      return vote.reviewer_role;
    }
  }
  return null;
}

export interface ReviewDetailPanelProps {
  approval: Approval;
  onClose: () => void;
  /**
   * Customer display name resolved from the lookup map. Falls back to
   * the raw ``data_subject_id`` when no Customer row matches.
   */
  customerDisplayName?: string | null;
}

export function ReviewDetailPanel({
  approval,
  onClose,
  customerDisplayName,
}: ReviewDetailPanelProps) {
  const ctx = approval.context ?? {};
  const gateName = stringField(ctx, "gate_name");
  const requiredRole = stringField(ctx, "required_role");
  const citation = stringField(ctx, "citation");
  const rawFixUrl = stringField(ctx, "fix_url");
  // Only render as a clickable link when the URL is http/https. Other
  // schemes (javascript:, data:, file:) are rendered as plain text so
  // a compromised gate pack can't slip an XSS payload through the
  // reviewer's UI. See ``safeHttpUrl`` above for the threat-model note.
  const fixUrl = rawFixUrl ? safeHttpUrl(rawFixUrl) : null;

  const isExpiredByClock =
    !!approval.expires_at &&
    formatTimeUntil(approval.expires_at) === "expired";
  const isPending = approval.status === "pending";
  const reviewerRole = latestReviewerRole(approval.decisions);

  return (
    <aside
      role="complementary"
      aria-label="Review detail"
      data-slot="review-detail-panel"
      data-review-id={approval.id}
      className="flex h-full w-full flex-col border-l border-[color:var(--ink-4)] bg-[color:var(--paper)]"
    >
      <header className="flex items-start justify-between gap-3 border-b border-[color:var(--ink-4)] px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <SeverityBadge severity={RISK_SEVERITY[approval.risk_tier]}>
              {RISK_LABEL[approval.risk_tier]}
            </SeverityBadge>
            <span
              data-testid="review-detail-panel-status-tag"
              className="text-[12px] uppercase tracking-[0.06em] text-[color:var(--ink-3)]"
            >
              {STATUS_LABEL[approval.status]}
            </span>
          </div>
          <h2 className="truncate text-[16px] font-medium text-[color:var(--ink)]">
            {approval.action_name}
          </h2>
          <p className="mt-0.5 truncate text-[12px] text-[color:var(--ink-2)]">
            {approval.requested_by_agent}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close review detail"
          data-testid="review-detail-panel-close"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-[6px] text-[color:var(--ink-2)] transition-colors hover:bg-[color:var(--paper-3)] hover:text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
        >
          <X aria-hidden="true" className="size-4" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <section
          aria-label="Decision context"
          className="space-y-4 border-b border-[color:var(--ink-4)] pb-5"
        >
          <DetailRow label="Customer">
            {customerDisplayName ?? "—"}
          </DetailRow>

          {gateName ? (
            <DetailRow label="Gate">
              <span className="text-[13px] text-[color:var(--ink)]">
                {gateName}
              </span>
              {citation ? (
                <span className="ml-2 text-[12px] text-[color:var(--ink-2)]">
                  {citation}
                </span>
              ) : null}
            </DetailRow>
          ) : null}

          {requiredRole ? (
            <DetailRow label="Required role">
              <code className="rounded-[4px] bg-[color:var(--paper-3)] px-1.5 py-0.5 text-[12px] text-[color:var(--ink)]">
                {requiredRole}
              </code>
            </DetailRow>
          ) : null}

          {fixUrl ? (
            <DetailRow label="Reference">
              <a
                href={fixUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="review-detail-panel-fix-url"
                className="inline-flex items-center gap-1 text-[13px] text-[color:var(--ink)] underline decoration-[color:var(--ink-3)] underline-offset-2 hover:decoration-[color:var(--ink)]"
              >
                {fixUrl}
                <ExternalLink aria-hidden="true" className="size-3" />
              </a>
            </DetailRow>
          ) : rawFixUrl ? (
            // Non-http(s) scheme — render as inert text + an inline
            // note so the reviewer still sees what the gate pack
            // wrote, without giving the URL click-execute privileges.
            <DetailRow label="Reference">
              <span
                data-testid="review-detail-panel-fix-url-blocked"
                className="text-[13px] text-[color:var(--ink-3)]"
                title="Link not rendered: scheme is not http or https."
              >
                {rawFixUrl}
              </span>
            </DetailRow>
          ) : null}

          <DetailRow label="Requested">
            <time
              dateTime={approval.requested_at}
              title={formatAbsoluteUTC(approval.requested_at)}
              className="text-[13px] text-[color:var(--ink)] tabular-nums"
            >
              {formatRelativeTime(approval.requested_at)}
            </time>
            <span className="ml-2 text-[12px] text-[color:var(--ink-3)] tabular-nums">
              {formatAbsoluteUTC(approval.requested_at)}
            </span>
          </DetailRow>

          {approval.expires_at ? (
            <DetailRow label="Expires">
              <span
                className={
                  "text-[13px] tabular-nums " +
                  (isExpiredByClock
                    ? "text-[color:var(--brick)]"
                    : "text-[color:var(--ink)]")
                }
                title={formatAbsoluteUTC(approval.expires_at)}
              >
                {isExpiredByClock
                  ? "Expired"
                  : formatTimeUntil(approval.expires_at)}
              </span>
            </DetailRow>
          ) : null}
        </section>

        <section
          aria-label="Review status"
          data-testid="review-detail-panel-status-section"
          className="space-y-2 pt-5"
        >
          <h3 className="text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
            Review status
          </h3>
          <ReviewStatusIndicator
            approval={approval}
            isPending={isPending}
            isExpiredByClock={isExpiredByClock}
            reviewerRole={reviewerRole}
          />
        </section>
      </div>
    </aside>
  );
}

interface ReviewStatusIndicatorProps {
  approval: Approval;
  isPending: boolean;
  isExpiredByClock: boolean;
  reviewerRole: string | null;
}

/**
 * Read-only status block. Replaces the W2.2-removed Approve/Modify/
 * Reject action box.
 *
 * The vendor's compliance officer reads this to answer "did the
 * customer's clinician get to it yet, and if so what did they decide?"
 * — never to *take* the decision. That stays in-band per HIPAA scope.
 */
function ReviewStatusIndicator({
  approval,
  isPending,
  isExpiredByClock,
  reviewerRole,
}: ReviewStatusIndicatorProps) {
  // Treat clock-expired-but-still-pending rows as "expired" for the
  // status copy — the row will flip on the next backend sweeper pass.
  // Surfacing it early keeps the dashboard honest.
  if (approval.status === "expired" || (isPending && isExpiredByClock)) {
    return (
      <p
        data-testid="review-detail-panel-status-expired"
        className="rounded-[8px] bg-[color:var(--brick-bg)] px-4 py-3 text-[13px] text-[color:var(--brick)]"
      >
        Expired without a callback from the customer EHR. No clinician
        decision was recorded before the review window closed.
      </p>
    );
  }
  if (approval.status === "cancelled") {
    return (
      <p
        data-testid="review-detail-panel-status-cancelled"
        className="rounded-[8px] bg-[color:var(--paper-3)] px-4 py-3 text-[13px] text-[color:var(--ink-2)]"
      >
        Review was cancelled before a clinician decision was recorded.
      </p>
    );
  }
  if (approval.status === "approved" || approval.status === "rejected") {
    const verb = approval.status === "approved" ? "Approved" : "Rejected";
    const whenIso = approval.decided_at ?? approval.resolved_at;
    return (
      <div
        data-testid={
          approval.status === "approved"
            ? "review-detail-panel-status-approved"
            : "review-detail-panel-status-rejected"
        }
        className="space-y-1 rounded-[8px] bg-[color:var(--paper-3)] px-4 py-3"
      >
        <p className="text-[13px] font-medium text-[color:var(--ink)]">
          {verb} in the customer EHR
          {reviewerRole ? (
            <>
              {" "}
              by{" "}
              <code className="rounded-[4px] bg-[color:var(--paper)] px-1.5 py-0.5 text-[12px] text-[color:var(--ink)]">
                {reviewerRole}
              </code>
            </>
          ) : null}
          .
        </p>
        {whenIso ? (
          <p className="text-[12px] text-[color:var(--ink-3)] tabular-nums">
            <time
              dateTime={whenIso}
              title={formatAbsoluteUTC(whenIso)}
            >
              {formatRelativeTime(whenIso)}
            </time>
            <span className="ml-2">{formatAbsoluteUTC(whenIso)}</span>
          </p>
        ) : null}
      </div>
    );
  }
  // Pending — the only common case.
  return (
    <p
      data-testid="review-detail-panel-status-pending"
      className="rounded-[8px] bg-[color:var(--paper-3)] px-4 py-3 text-[13px] text-[color:var(--ink-2)]"
    >
      Pending in customer EHR — waiting for clinician callback. The
      Vera dashboard is read-only; clinician decisions are recorded
      in-band via the customer&rsquo;s EHR integration.
    </p>
  );
}

interface DetailRowProps {
  label: string;
  children: React.ReactNode;
}
function DetailRow({ label, children }: DetailRowProps) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-3)]">
        {label}
      </p>
      <div>{children}</div>
    </div>
  );
}
