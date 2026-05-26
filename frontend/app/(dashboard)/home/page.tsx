"use client";

/**
 * /home — Phase 1 PR 12 Home page (Stream F item F1).
 *
 * Replaces the PR #192 stub-redirect with the real Home surface. Per
 * `dashboard-design.md` §Screen 1 — Home, the page exists for the daily
 * 30-second check: the compliance lead should be able to confirm "nothing
 * is broken" in 5 seconds, glance at recent activity, and close the tab.
 *
 * Three sections in this PR (every section uses the small-caps editorial
 * header pattern from `dashboard-design-system.md`):
 *
 *   1. Needs your attention — EmptyState in v1; Phase 2+ will hydrate
 *      with expiring BAAs, pending reviews, webhook failures.
 *   2. Chain integrity — Wave 3D.1 ``ChainIntegrityTile`` reads the
 *      ``GET /v1/dashboard/chain-integrity`` aggregate (status + latest
 *      checkpoint + chain depth + KMS key + cadence) so the Home tile
 *      stays in lockstep with the topbar pill on every load.
 *   3. Recent activity — last 5 ActionRecord rows across the org with a
 *      "See all →" affordance. Each row links to the customer detail stub
 *      at /customers/{tenant_id}. (Limit dropped from 20 → 5 per PR #198
 *      review: the daily 30-second check is "scan, leave", not "scroll".)
 *
 * NO greeting chrome, NO marketing copy, NO charts. The compliance
 * officer wants to leave the dashboard, not be entertained.
 */

import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { useActions } from "@/hooks/use-actions";
import { useChainVerification } from "@/hooks/use-verification";
import { useChainIntegrity } from "@/hooks/use-chain-integrity";
import { StatusDot } from "@/components/ui/status-indicator";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading } from "@/components/ui/loading";
import { ChainIntegrityTile } from "@/components/home/chain-integrity-tile";
import { ResumeSetupBanner } from "@/components/wizard/resume-setup-banner";
import { formatRelativeTime } from "@/lib/utils";
import type { ActionRecord } from "@/lib/api-types";

const RECENT_ACTIVITY_LIMIT = 5;

/**
 * Full date + time formatter. Per spec: "Counsel reads exact dates, not
 * '13 months away'." Uses tabular-nums via CSS so digit columns align.
 */
function formatFullTimestamp(iso: string): string {
  const d = new Date(iso);
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/**
 * Best-effort tenant_id lookup on an ActionRecord. The Customer
 * auto-discovery work (PR 3) records tenant_id under
 * `metadata.tenant_id` for the standard middleware path; older records
 * may not have it. When missing, we still render the row (without a
 * customer link) rather than dropping it.
 */
function getTenantId(action: ActionRecord): string | null {
  const meta = action.metadata as Record<string, unknown> | null | undefined;
  const fromMeta = meta && typeof meta["tenant_id"] === "string" ? (meta["tenant_id"] as string) : null;
  if (fromMeta) return fromMeta;
  const envt = action.environment as Record<string, unknown> | null | undefined;
  const fromEnv = envt && typeof envt["tenant_id"] === "string" ? (envt["tenant_id"] as string) : null;
  return fromEnv;
}

export default function HomePage() {
  const { organization, isLoading: authLoading } = useAuth();
  const { data: chain, isLoading: chainLoading } = useChainVerification();
  const { data: integrity, isLoading: integrityLoading } = useChainIntegrity();
  const { data: actionsData, isLoading: actionsLoading } = useActions({ limit: RECENT_ACTIVITY_LIMIT });

  const actions = actionsData?.records ?? [];
  const latestAction = actions[0];

  // Org-wide "empty everywhere" state — no chain history yet AND no
  // recorded actions. Per `dashboard-design.md`: "Empty when there's
  // nothing to do (StatusDot ok-green only, no other chrome)".
  const hasAnyActivity = actions.length > 0;
  const isFullyEmpty =
    !chainLoading &&
    !actionsLoading &&
    chain !== undefined &&
    chain.records_checked === 0 &&
    !hasAnyActivity;

  return (
    <div className="mx-auto max-w-5xl space-y-12 py-2">
      {/* ───────────────── Page header ───────────────── */}
      <header className="space-y-3">
        <h1
          className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]"
          data-testid="home-org-name"
        >
          {authLoading ? (
            <span
              aria-busy="true"
              className="inline-flex items-center text-[color:var(--ink-3)]"
            >
              <Loading.Spinner size={16} label="Loading organization" />
            </span>
          ) : (
            organization?.name ?? "Your organization"
          )}
        </h1>
        <p className="text-sm text-[color:var(--ink-2)]">
          {latestAction
            ? `Last activity ${formatRelativeTime(latestAction.action_timestamp)}.`
            : "No activity recorded yet."}
        </p>
      </header>

      {isFullyEmpty ? (
        <section aria-label="Status">
          <StatusDot variant="ok" label="Nothing to do." />
        </section>
      ) : (
        <>
          {/* ───────────────── Resume setup banner ─────────────────
              Phase 1 PR 14 (Stream F item F5) — Codex D4.
              Shown when SDK has captured ≥1 action AND wizard is incomplete.
              Renders ABOVE "Needs your attention" so it's the first
              non-greeting block the operator sees on a return visit. */}
          <ResumeSetupBanner />

          {/* ───────────────── Needs your attention ───────────────── */}
          <section aria-labelledby="needs-attention-heading" className="space-y-4">
            <SectionHeader id="needs-attention-heading">Needs your attention</SectionHeader>
            {/* Phase 1: no actionable items yet — Phase 2 will populate this with pending reviews / expiring BAAs / webhook failures. */}
            <EmptyState
              title="Nothing needs your attention"
              subtitle="Pending reviews, expiring BAAs, and webhook failures will appear here."
            />
          </section>

          {/* ───────────────── Chain integrity ─────────────────
              Phase 3 Wave 3D.1 — full tile with status indicator,
              latest checkpoint, chain depth, KMS key, cadence, and a
              "Download evidence bundle" CTA. Reads from the
              ``GET /v1/dashboard/chain-integrity`` aggregate so the
              tile and the topbar pill (``useChainVerification``) stay
              consistent without duplicating chain math. */}
          <section aria-labelledby="chain-integrity-heading" className="space-y-4">
            <SectionHeader id="chain-integrity-heading">Chain integrity</SectionHeader>
            <ChainIntegrityTile
              loading={integrityLoading}
              data={integrity}
            />
          </section>

          {/* ───────────────── Recent activity ───────────────── */}
          <section aria-labelledby="recent-activity-heading" className="space-y-4">
            <SectionHeader id="recent-activity-heading">Recent activity</SectionHeader>
            <RecentActivityList loading={actionsLoading} actions={actions} />
          </section>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Small primitives kept inline — they exist only for this page surface
// and don't justify their own files. If Phase 2 reuses any of them we'll
// promote them into components/ui.
// ─────────────────────────────────────────────────────────────────────

function SectionHeader({ id, children }: { id?: string; children: React.ReactNode }) {
  // Inter 12px, weight 600, tracking 0.10em, uppercase — the small-caps
  // editorial pattern from dashboard-design-system.md §Section header.
  return (
    <h2
      id={id}
      className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--ink-2)]"
    >
      {children}
    </h2>
  );
}

function RecentActivityList({
  loading,
  actions,
}: {
  loading: boolean;
  actions: ActionRecord[];
}) {
  if (loading) {
    return (
      <div
        aria-busy="true"
        className="flex justify-center py-8 text-[color:var(--ink-3)]"
        data-testid="recent-activity-loading"
      >
        <Loading.Spinner size={20} label="Loading recent activity" />
      </div>
    );
  }

  if (actions.length === 0) {
    return (
      <EmptyState
        title="No activity yet"
        subtitle="Connect the SDK to start capturing decisions."
      />
    );
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-[color:var(--ink-4)] border-y border-[color:var(--ink-4)]" data-testid="recent-activity-list">
        {actions.map((action) => {
          const tenantId = getTenantId(action);
          const rowContent = (
            <div className="grid grid-cols-[140px_1fr_auto] items-baseline gap-4 py-3">
              <span className="text-[13px] text-[color:var(--ink-2)] tabular-nums">
                {formatFullTimestamp(action.action_timestamp)}
              </span>
              <span className="min-w-0 text-[14px] text-[color:var(--ink)]">
                <span className="font-medium">{action.action_name}</span>
                {action.action_description ? (
                  <span className="ml-2 text-[color:var(--ink-2)]">{action.action_description}</span>
                ) : null}
              </span>
              <span className="text-[12px] text-[color:var(--ink-3)] uppercase tracking-[0.06em]">
                {action.agent_name}
              </span>
            </div>
          );

          if (tenantId) {
            return (
              <li key={action.id}>
                <Link
                  href={`/customers/${encodeURIComponent(tenantId)}`}
                  className="block transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[color:var(--ink)]"
                >
                  {rowContent}
                </Link>
              </li>
            );
          }
          return <li key={action.id}>{rowContent}</li>;
        })}
      </ul>
      {/* TODO(Phase 2): link to /activity once that page ships. */}
      <div className="text-right">
        <Link
          href="/customers"
          className="text-[13px] text-[color:var(--ink-2)] hover:text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
        >
          See all →
        </Link>
      </div>
    </div>
  );
}
