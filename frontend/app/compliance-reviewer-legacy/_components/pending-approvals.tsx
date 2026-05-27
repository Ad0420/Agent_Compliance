import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { RiskTierBadge } from "./risk-tier-badge";
import { EmptyState } from "./section-error";
import type { DashboardApproval } from "@/lib/api-server";

export function PendingApprovals({
  approvals,
}: {
  approvals: DashboardApproval[];
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <div>
          <CardTitle className="text-base">Pending HITL approvals</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Human-in-the-loop decisions waiting on a reviewer.
          </p>
        </div>
        {/* The legacy /approvals page was retired in PR 0c. The Phase 2
            Review queue (PR set TBD) supersedes it. */}
      </CardHeader>
      <CardContent className="p-0">
        {approvals.length === 0 ? (
          <div className="p-6">
            <EmptyState message="No pending approvals. The HITL queue is clear." />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Action</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Approvers</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead className="text-right">Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {approvals.map((a) => {
                const approveCount = a.decisions.filter(
                  (d) => d.decision === "approve",
                ).length;
                return (
                  <TableRow key={a.id} className="hover:bg-accent/40">
                    <TableCell className="text-sm font-medium">
                      {a.action_name}
                      {/*
                        W2.2 — ``action_summary`` is a free-text PHI
                        carrier ("Commit note for encounter MRN-12345:
                        1 new diagnosis…"). The W1.2 dashboard
                        serializer already strips it for Clerk callers
                        so the field arrives null; we deliberately do
                        not render it even if a future serializer
                        change re-introduces the value. Defense in
                        depth.
                      */}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {a.requested_by_agent}
                    </TableCell>
                    <TableCell>
                      <RiskTierBadge tier={a.risk_tier} />
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px] tabular-nums">
                        {approveCount} / {a.approvers_required}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <span title={formatDate(a.requested_at)}>
                        {formatRelativeTime(a.requested_at)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      {/* Detail-view destination ships with the Phase 2 Review
                          queue. Until then we surface the approval id so users
                          can correlate against backend logs. */}
                      <span
                        className="text-xs text-muted-foreground font-mono"
                        title={a.id}
                      >
                        {a.id.slice(0, 8)}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
