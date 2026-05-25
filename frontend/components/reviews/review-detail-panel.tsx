"use client";

/**
 * ReviewDetailPanel — Wave 2D PR C2.
 *
 * Pattern B split work surface (per
 * dashboard-design-system.md §Layout patterns line 219+): the page wraps
 * the table in the left content area, and renders this panel as the
 * fixed-width right panel (360-420px) when a row is selected.
 *
 * Anatomy
 * =======
 *   ┌───────────────────────────────────────┐
 *   │ Review header (action + close)         │
 *   ├───────────────────────────────────────┤
 *   │ Decision context (left content)        │
 *   │   - agent + action + summary           │
 *   │   - gate citation + fix_url link       │
 *   │   - input data (collapsible JSON view) │
 *   │   - requested at / expires at          │
 *   ├───────────────────────────────────────┤
 *   │ Action box (Approve / Modify / Reject) │
 *   │   (CompleteReviewForm)                 │
 *   └───────────────────────────────────────┘
 *
 * The "context" we render on the left is the Approval row from
 * /v1/approvals — Approval.context carries gate metadata (gate_name,
 * required_role, citation, fix_url) once Wave 2B A2 lands; older
 * approvals just show the basic action / agent / data subject.
 */

import * as React from "react";
import { X, ExternalLink, ChevronDown, ChevronRight } from "lucide-react";

import { CompleteReviewForm } from "./complete-review-form";
import { SeverityBadge, type Severity } from "@/components/ui/severity-badge";
import {
  formatAbsoluteUTC,
  formatRelativeTime,
  formatTimeUntil,
} from "@/lib/utils";
import type { Approval, RiskTier } from "@/lib/api-types";

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
  const [inputExpanded, setInputExpanded] = React.useState(false);

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
  const reasonDetail = stringField(ctx, "reason_detail");

  // Renderable preview of the action's input data when the gate
  // payload is included on Approval.context (Wave 2B may serialise the
  // request payload here for the reviewer's benefit). Bounded format
  // so a pathological 1 MB payload doesn't blow up the right panel.
  const inputData = (ctx as { input?: unknown }).input;
  const hasInput = inputData !== undefined && inputData !== null;
  const inputJson = hasInput
    ? JSON.stringify(inputData, null, 2).slice(0, 8000)
    : null;

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
            <span className="text-[12px] uppercase tracking-[0.06em] text-[color:var(--ink-3)]">
              Pending review
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
            {customerDisplayName ?? approval.data_subject_id ?? "—"}
          </DetailRow>

          {approval.action_summary ? (
            <DetailRow label="Summary">
              <p className="text-[13px] text-[color:var(--ink)] leading-relaxed">
                {approval.action_summary}
              </p>
            </DetailRow>
          ) : null}

          {reasonDetail ? (
            <DetailRow label="Reason">
              <p className="text-[13px] text-[color:var(--ink)] leading-relaxed">
                {reasonDetail}
              </p>
            </DetailRow>
          ) : null}

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
                  (formatTimeUntil(approval.expires_at) === "expired"
                    ? "text-[color:var(--brick)]"
                    : "text-[color:var(--ink)]")
                }
                title={formatAbsoluteUTC(approval.expires_at)}
              >
                {formatTimeUntil(approval.expires_at) === "expired"
                  ? "Expired"
                  : formatTimeUntil(approval.expires_at)}
              </span>
            </DetailRow>
          ) : null}

          {hasInput && inputJson ? (
            <div>
              <button
                type="button"
                onClick={() => setInputExpanded((v) => !v)}
                aria-expanded={inputExpanded}
                data-testid="review-detail-panel-input-toggle"
                className="inline-flex items-center gap-1 text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)] hover:text-[color:var(--ink)]"
              >
                {inputExpanded ? (
                  <ChevronDown aria-hidden="true" className="size-3" />
                ) : (
                  <ChevronRight aria-hidden="true" className="size-3" />
                )}
                Input data
              </button>
              {inputExpanded ? (
                <pre
                  data-testid="review-detail-panel-input-json"
                  className="mt-2 max-h-72 overflow-auto rounded-[8px] bg-[color:var(--paper-3)] px-3 py-2 text-[12px] text-[color:var(--ink)] leading-relaxed"
                >
                  <code>{inputJson}</code>
                </pre>
              ) : null}
            </div>
          ) : null}
        </section>

        <section
          aria-label="Record decision"
          className="space-y-4 pt-5"
        >
          <h3 className="text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
            Record decision
          </h3>
          <CompleteReviewForm
            approval={approval}
            onSuccess={onClose}
            onTerminalError={onClose}
          />
        </section>
      </div>
    </aside>
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
