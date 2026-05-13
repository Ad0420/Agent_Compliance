import Link from "next/link";
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
            Human-in-the-loop decisions waiting on a reviewer. The Approvals
            page is where reviewers actually decide.
          </p>
        </div>
        <Link
          href="/approvals"
          className="text-xs text-emerald-400 hover:underline"
        >
          View all approvals →
        </Link>
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
                      {a.action_summary ? (
                        <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
                          {a.action_summary}
                        </p>
                      ) : null}
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
                      <Link
                        href={`/approvals?focus=${encodeURIComponent(a.id)}`}
                        className="text-xs text-emerald-400 hover:underline"
                      >
                        View details
                      </Link>
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
