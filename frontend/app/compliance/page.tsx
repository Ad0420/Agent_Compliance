/**
 * /compliance — Clerk-authenticated compliance reviewer landing page (F2).
 *
 * The wedge promise: when a developer hands this URL to compliance, the
 * compliance team can use the dashboard without help. Default view is the
 * last 30 days of high-risk decisions, HITL approvals, and policy
 * violations. Filters encode into `searchParams` so the URL itself is the
 * saved view.
 *
 * Lives OUTSIDE the `(dashboard)` route group on purpose: the legacy
 * dashboard layout uses localStorage `ProtectedRoute`, which doesn't gate
 * on Clerk. This page is Clerk-only — middleware enforces the auth, the
 * page reads `auth()` server-side, and the backend `compliance_review_audit`
 * middleware records every reviewer hit.
 *
 * Data fetching: each backend call is wrapped in try/catch so a single
 * failing route (e.g. `/review-trail` for a developer, who lacks
 * `admin`/`compliance_reviewer`) degrades to an inline error banner
 * rather than crashing the whole page.
 */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ShieldAlert, UserCheck, AlertTriangle, Activity } from "lucide-react";

import {
  getClerkBackendToken,
  getClerkSessionSummary,
} from "@/lib/auth-server";
import {
  getComplianceSummary,
  getComplianceRecent,
  getComplianceReviewTrail,
  getPendingApprovals,
  getRecentViolations,
  VeraApiError,
  type ComplianceSummary,
  type ComplianceReviewTrailEntry,
  type DashboardApproval,
  type DashboardViolation,
} from "@/lib/api-server";

import { StatCard } from "./_components/stat-card";
import { RangeSelector } from "./_components/range-selector";
import { ExportPdfButton } from "./_components/export-pdf-button";
import { CopyLinkButton } from "./_components/copy-link-button";
import { RecentRecordsTable } from "./_components/recent-records-table";
import { PendingApprovals } from "./_components/pending-approvals";
import { ViolationsList } from "./_components/violations-list";
import { ReviewTrailSection } from "./_components/review-trail-section";
import { SectionError } from "./_components/section-error";

export const dynamic = "force-dynamic";

const ALLOWED_RANGES = new Set(["7", "30", "90", "180"]);

interface ComplianceRecentRecord {
  id: string;
  sequence_number?: number | string;
  recorded_at?: string | null;
  action_timestamp?: string | null;
  agent_name?: string | null;
  action_name?: string | null;
  action_type?: string | null;
  result?: string | null;
  data_subject_id?: string | null;
  record_hash?: string | null;
}

function parseRange(raw: string | undefined): string {
  if (raw && ALLOWED_RANGES.has(raw)) return raw;
  return "30";
}

function describeError(err: unknown): string {
  if (err instanceof VeraApiError) {
    if (err.status === 401) return "Your Clerk session has expired.";
    if (err.status === 403) {
      return "You don't have permission for this view. Ask an admin to grant the compliance_reviewer role.";
    }
    if (err.status === 404) return "The backend route is not available.";
    return `Backend error (${err.status}). Try refreshing.`;
  }
  return err instanceof Error ? err.message : "Could not reach the backend.";
}

export default async function CompliancePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const rawRange = typeof params.range === "string" ? params.range : undefined;
  const range = parseRange(rawRange);
  const rangeDays = parseInt(range, 10);

  const session = await getClerkSessionSummary();
  if (!session) {
    return <SignInPrompt />;
  }
  const token = await getClerkBackendToken();
  if (!token) {
    return <SignInPrompt />;
  }
  if (!session.orgId) {
    return <NoActiveOrg />;
  }

  const clerkRole = session.orgRole ?? "";
  const isAdmin = clerkRole === "org:admin" || clerkRole === "admin";
  const isComplianceReviewer =
    clerkRole === "org:compliance_reviewer" ||
    clerkRole === "compliance_reviewer";
  // We let developers reach this page too — the backend will 403 the
  // review-trail section but the rest still loads. Keeping the dashboard
  // accessible to developers (per `_READ_ROLES` on the backend) means a
  // dev handing the URL to compliance is also the URL the dev can sanity-
  // check themselves.
  const reviewTrailVisible = isAdmin || isComplianceReviewer;

  // Pretty role label — only shown if we can identify it.
  const roleLabel = isAdmin
    ? "Admin"
    : isComplianceReviewer
      ? "Compliance reviewer"
      : clerkRole.replace(/^org:/, "") || "Member";

  // ── Fetch everything in parallel, but isolate each failure ─────────────
  const summaryP = getComplianceSummary(rangeDays).then(
    (data) => ({ ok: true as const, data }),
    (err) => ({ ok: false as const, err: describeError(err) }),
  );
  const recentP = getComplianceRecent(20).then(
    (data) => ({ ok: true as const, data }),
    (err) => ({ ok: false as const, err: describeError(err) }),
  );
  const approvalsP = getPendingApprovals(10).then(
    (data) => ({ ok: true as const, data }),
    (err) => ({ ok: false as const, err: describeError(err) }),
  );
  const violationsP = getRecentViolations(10).then(
    (data) => ({ ok: true as const, data }),
    (err) => ({ ok: false as const, err: describeError(err) }),
  );
  // Only fetch review-trail when the user is authorised to see it; the
  // backend will 403 developers and we don't want to spend a round trip
  // just to throw it away.
  const trailP: Promise<
    | { ok: true; data: { records: ComplianceReviewTrailEntry[]; count: number } }
    | { ok: false; err: string }
  > = reviewTrailVisible
    ? getComplianceReviewTrail(20).then(
        (data) => ({ ok: true as const, data }),
        (err) => ({ ok: false as const, err: describeError(err) }),
      )
    : Promise.resolve({ ok: true as const, data: { records: [], count: 0 } });

  const [summaryRes, recentRes, approvalsRes, violationsRes, trailRes] =
    await Promise.all([summaryP, recentP, approvalsP, violationsP, trailP]);

  const summary: ComplianceSummary | null = summaryRes.ok
    ? summaryRes.data
    : null;
  const recentRecords: ComplianceRecentRecord[] = recentRes.ok
    ? (recentRes.data.records as unknown as ComplianceRecentRecord[])
    : [];
  const approvals: DashboardApproval[] = approvalsRes.ok
    ? approvalsRes.data.approvals
    : [];
  const violations: DashboardViolation[] = violationsRes.ok
    ? violationsRes.data.violations
    : [];
  const trail: ComplianceReviewTrailEntry[] = trailRes.ok
    ? trailRes.data.records
    : [];

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      {/* Header */}
      <header className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">
              Compliance review
            </h1>
            <Badge variant="outline" className="text-[10px] capitalize">
              {roleLabel}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {session.email ?? "Signed in"} ·{" "}
            <span className="font-mono text-xs">
              org {session.orgId.slice(0, 10)}
            </span>{" "}
            · last {rangeDays} days
          </p>
          <p className="text-xs text-muted-foreground">
            Looking for the regulatory reference?{" "}
            <Link
              href="/regulations/eu-ai-act"
              className="text-emerald-400 hover:underline"
            >
              EU AI Act &amp; Colorado SB 24-205 guide →
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RangeSelector value={range} />
          <CopyLinkButton />
          <ExportPdfButton range={range} />
        </div>
      </header>

      {/* Summary cards */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryRes.ok && summary ? (
          <>
            <StatCard
              label="High-risk decisions"
              value={summary.high_risk_decisions}
              icon={<ShieldAlert className="h-4 w-4" />}
              tone={summary.high_risk_decisions > 0 ? "warn" : "neutral"}
              hint={`Tier high or critical · last ${summary.window_days}d`}
            />
            <StatCard
              label="HITL approvals taken"
              value={summary.hitl_approvals_taken}
              icon={<UserCheck className="h-4 w-4" />}
              tone="neutral"
              hint="Approved or rejected in window"
            />
            <StatCard
              label="Policy violations"
              value={summary.policy_violations}
              icon={<AlertTriangle className="h-4 w-4" />}
              tone={summary.policy_violations > 0 ? "danger" : "good"}
              hint="Triggered in window"
            />
            <StatCard
              label="Window"
              value={`${summary.window_days}d`}
              icon={<Activity className="h-4 w-4" />}
              tone="neutral"
              hint="Use the range selector to change"
            />
          </>
        ) : summaryRes.ok ? null : (
          <div className="sm:col-span-2 lg:col-span-4">
            <SectionError message={summaryRes.err} />
          </div>
        )}
      </section>

      {/* Recent high-risk records */}
      <section>
        {recentRes.ok ? (
          <RecentRecordsTable records={recentRecords} />
        ) : (
          <SectionError message={recentRes.err} />
        )}
      </section>

      {/* Pending approvals */}
      <section>
        {approvalsRes.ok ? (
          <PendingApprovals approvals={approvals} />
        ) : (
          <SectionError message={approvalsRes.err} />
        )}
      </section>

      {/* Violations */}
      <section>
        {violationsRes.ok ? (
          <ViolationsList violations={violations} />
        ) : (
          <SectionError message={violationsRes.err} />
        )}
      </section>

      {/* Reviewer audit trail (only when authorised) */}
      <section>
        {trailRes.ok ? (
          <ReviewTrailSection
            entries={trail}
            visible={reviewTrailVisible}
          />
        ) : reviewTrailVisible ? (
          <SectionError message={trailRes.err} />
        ) : null}
      </section>

      {/* Footer / saved-view hint */}
      <footer className="rounded-md border border-dashed border-border p-4 text-xs text-muted-foreground">
        <p>
          <strong className="text-foreground">Saved views:</strong> the
          current URL captures the time range and any filters. Copy it with
          the button above to share with regulators, your CTO, or an
          auditor — they&apos;ll need Clerk access to your organization to
          open it.
        </p>
      </footer>
    </main>
  );
}

function SignInPrompt() {
  return (
    <main className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>Sign in required</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            The compliance dashboard is gated behind Clerk authentication.
            Sign in with your organization&apos;s account to continue.
          </p>
          <Link
            href="/login"
            className="text-emerald-400 underline-offset-2 hover:underline"
          >
            Go to sign-in →
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}

function NoActiveOrg() {
  return (
    <main className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>No active organization</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            You&apos;re signed in but no organization is selected. Use the
            organization switcher in your Clerk user menu to select or
            create an org, then return here.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
