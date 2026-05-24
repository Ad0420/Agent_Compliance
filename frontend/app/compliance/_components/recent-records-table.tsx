import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, truncateHash } from "@/lib/utils";
import { RiskTierBadge } from "./risk-tier-badge";
import { EmptyState } from "./section-error";

interface RecentRecord {
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
  // Derived risk_tier — backend doesn't surface it on action records; we
  // surface a fallback tier from result (blocked → high, failure → medium).
}

function deriveRisk(result: string | null | undefined): string {
  switch ((result ?? "").toLowerCase()) {
    case "blocked":
      return "high";
    case "failure":
      return "medium";
    case "success":
      return "low";
    default:
      return "low";
  }
}

const RESULT_COLORS: Record<string, string> = {
  success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  failure: "bg-red-500/15 text-red-400 border-red-500/30",
  blocked: "bg-orange-500/15 text-orange-400 border-orange-500/30",
};

function ResultBadge({ result }: { result: string | null | undefined }) {
  const r = (result ?? "").toLowerCase();
  const colorClass = RESULT_COLORS[r] ?? "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  return (
    <Badge variant="outline" className={`text-[10px] capitalize ${colorClass}`}>
      {r || "—"}
    </Badge>
  );
}

export function RecentRecordsTable({
  records,
}: {
  records: RecentRecord[];
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <div>
          <CardTitle className="text-base">Recent high-risk activity</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Failed or blocked actions, surfaced first.
          </p>
        </div>
        <Badge variant="outline" className="text-xs">
          {records.length} shown
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {records.length === 0 ? (
          <div className="p-6">
            <EmptyState message="No high-risk activity in this window — your agents are behaving." />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">Seq</TableHead>
                <TableHead>Timestamp</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Result</TableHead>
                <TableHead>Data subject</TableHead>
                <TableHead>Hash</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((r) => {
                // /actions/<id> deep links were retired with the legacy
                // dashboard in PR 0c. The Phase 4 audit-trail PDF surfaces
                // per-record evidence; until then we render the row as
                // plain cells with a truncated id (via the Seq column tooltip)
                // so users can correlate against backend logs.
                const ts = r.action_timestamp ?? r.recorded_at ?? null;
                return (
                  <TableRow key={r.id} className="hover:bg-accent/40">
                    <TableCell
                      className="font-mono text-xs text-muted-foreground"
                      title={r.id}
                    >
                      #{r.sequence_number ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {ts ? formatDate(ts) : "—"}
                    </TableCell>
                    <TableCell className="text-sm">{r.agent_name ?? "—"}</TableCell>
                    <TableCell className="text-sm">{r.action_name ?? "—"}</TableCell>
                    <TableCell>
                      <RiskTierBadge tier={deriveRisk(r.result ?? null)} />
                    </TableCell>
                    <TableCell>
                      <ResultBadge result={r.result} />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground max-w-[120px] truncate">
                      {r.data_subject_id
                        ? truncateHash(r.data_subject_id, 6)
                        : "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {r.record_hash ? truncateHash(r.record_hash) : "—"}
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
