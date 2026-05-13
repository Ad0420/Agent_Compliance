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
import { EmptyState } from "./section-error";
import type { DashboardViolation } from "@/lib/api-server";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
  high: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

function SeverityBadge({ severity }: { severity: string }) {
  const s = (severity ?? "").toLowerCase();
  const colorClass =
    SEVERITY_COLORS[s] ?? "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  return (
    <Badge
      variant="outline"
      className={`text-[10px] capitalize border ${colorClass}`}
    >
      {s || "—"}
    </Badge>
  );
}

export function ViolationsList({
  violations,
}: {
  violations: DashboardViolation[];
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <div>
          <CardTitle className="text-base">Recent policy violations</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Triggered policy checks the team should review.
          </p>
        </div>
        <Link
          href="/policies"
          className="text-xs text-emerald-400 hover:underline"
        >
          Manage policies →
        </Link>
      </CardHeader>
      <CardContent className="p-0">
        {violations.length === 0 ? (
          <div className="p-6">
            <EmptyState message="No policy violations in this window." />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Policy</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Triggered</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {violations.map((v) => {
                const resolved = !!v.resolved_at;
                return (
                  <TableRow key={v.id} className="hover:bg-accent/40">
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {v.policy_id ? v.policy_id.slice(0, 12) : "—"}
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={v.severity} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {v.triggered_at ? (
                        <span title={formatDate(v.triggered_at)}>
                          {formatRelativeTime(v.triggered_at)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${
                          resolved
                            ? "border-emerald-500/30 text-emerald-400"
                            : "border-amber-500/30 text-amber-400"
                        }`}
                      >
                        {resolved ? "Resolved" : "Open"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {v.record_id ? (
                        <Link
                          href={`/actions/${v.record_id}`}
                          className="text-xs text-emerald-400 hover:underline"
                        >
                          Investigate →
                        </Link>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
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
