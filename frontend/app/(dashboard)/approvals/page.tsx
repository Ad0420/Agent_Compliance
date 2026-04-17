"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import {
  useApprovals,
  useDecideApproval,
  useCancelApproval,
} from "@/hooks/use-approvals";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import {
  Check,
  Loader2,
  X,
  ExternalLink,
  ShieldAlert,
  Ban,
  UserCheck,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import type {
  Approval,
  ApprovalStatus,
  RiskTier,
  ApprovalQueryParams,
} from "@/lib/api-types";

// ── Styling ────────────────────────────────────────────────────────────────

const RISK_COLORS: Record<RiskTier, string> = {
  critical: "bg-red-500/15 text-red-400",
  high: "bg-orange-500/15 text-orange-400",
  medium: "bg-amber-500/15 text-amber-400",
  low: "bg-emerald-500/15 text-emerald-400",
};

const STATUS_COLORS: Record<ApprovalStatus, string> = {
  pending: "bg-amber-500/15 text-amber-400",
  approved: "bg-emerald-500/15 text-emerald-400",
  rejected: "bg-red-500/15 text-red-400",
  expired: "bg-zinc-500/15 text-zinc-400",
  cancelled: "bg-zinc-500/15 text-zinc-400",
};

const ALL_VALUE = "__all__";

// ── Decision Dialog ────────────────────────────────────────────────────────

function DecisionDialog({
  approval,
  decision,
  onClose,
}: {
  approval: Approval | null;
  decision: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const decide = useDecideApproval();
  const [approver, setApprover] = useState("");
  const [note, setNote] = useState("");

  const open = !!approval && !!decision;
  const isApprove = decision === "approve";

  const handleSubmit = async () => {
    if (!approval || !decision || !approver.trim()) return;
    try {
      await decide.mutateAsync({
        id: approval.id,
        input: {
          decision,
          approver: approver.trim(),
          note: note.trim() || undefined,
        },
      });
      toast.success(
        decision === "approve" ? "Approved" : "Rejected",
      );
      setApprover("");
      setNote("");
      onClose();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to record decision");
    }
  };

  if (!approval || !decision) return null;

  const alreadyVoted = approval.decisions.some(
    (d) => d.approver === approver.trim() && approver.trim().length > 0,
  );
  const remainingVotes = approval.approvers_required -
    approval.decisions.filter((d) => d.decision === "approve").length;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isApprove ? "Approve action" : "Reject action"}
          </DialogTitle>
          <DialogDescription>
            {isApprove
              ? `Your vote will be cryptographically signed and written to the audit chain.${
                  approval.approvers_required > 1
                    ? ` ${remainingVotes} ${remainingVotes === 1 ? "vote" : "votes"} still required.`
                    : ""
                }`
              : "Rejection is terminal — the approval will be resolved immediately and the action blocked."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 rounded-md border border-border bg-accent/30 p-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Action</p>
            <p className="font-medium">{approval.action_name}</p>
            {approval.action_summary && (
              <p className="text-xs text-muted-foreground mt-0.5">{approval.action_summary}</p>
            )}
          </div>
          <div className="flex gap-4">
            <div>
              <p className="text-xs text-muted-foreground">Agent</p>
              <p className="font-mono text-xs">{approval.requested_by_agent}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Risk</p>
              <Badge className={cn("text-xs capitalize", RISK_COLORS[approval.risk_tier])}>
                {approval.risk_tier}
              </Badge>
            </div>
          </div>
          {approval.data_subject_id && (
            <div>
              <p className="text-xs text-muted-foreground">Data subject</p>
              <p className="font-mono text-xs">{approval.data_subject_id}</p>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">Approver identity *</label>
            <Input
              value={approver}
              onChange={(e) => setApprover(e.target.value)}
              placeholder="e.g., jane.doe@company.com"
              className="mt-1"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Use an identifier that uniquely identifies you (email or username).
            </p>
            {alreadyVoted && (
              <p className="mt-1 text-xs text-red-400">
                This approver has already voted on this approval.
              </p>
            )}
          </div>
          <div>
            <label className="text-sm font-medium">
              Note <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Reasoning for your decision..."
              rows={3}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!approver.trim() || alreadyVoted || decide.isPending}
            className={cn(
              isApprove
                ? "bg-emerald-500/90 hover:bg-emerald-500 text-black"
                : "bg-red-500/90 hover:bg-red-500 text-white",
            )}
          >
            {decide.isPending ? (
              <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Submitting...</>
            ) : isApprove ? (
              <><Check className="mr-1 h-4 w-4" /> Confirm approve</>
            ) : (
              <><X className="mr-1 h-4 w-4" /> Confirm reject</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Approval Detail Dialog ─────────────────────────────────────────────────

function DetailDialog({
  approval,
  onClose,
}: {
  approval: Approval | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!approval} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        {approval && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {approval.action_name}
                <Badge className={cn("text-xs capitalize", STATUS_COLORS[approval.status])}>
                  {approval.status}
                </Badge>
                <Badge className={cn("text-xs capitalize", RISK_COLORS[approval.risk_tier])}>
                  {approval.risk_tier}
                </Badge>
              </DialogTitle>
              <DialogDescription>
                Approval {approval.id.slice(0, 8)}… · requested {formatRelativeTime(approval.requested_at)}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 text-sm">
              {approval.action_summary && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Summary</p>
                  <p className="mt-1">{approval.action_summary}</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Agent</p>
                  <p className="mt-1 font-mono text-xs">{approval.requested_by_agent}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Approvers required</p>
                  <p className="mt-1">{approval.approvers_required}</p>
                </div>
                {approval.data_subject_id && (
                  <div>
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Data subject</p>
                    <p className="mt-1 font-mono text-xs">{approval.data_subject_id}</p>
                  </div>
                )}
                {approval.expires_at && (
                  <div>
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Expires</p>
                    <p className="mt-1">{formatDate(approval.expires_at)}</p>
                  </div>
                )}
              </div>

              {/* Chain links */}
              <div className="flex flex-wrap gap-2 text-xs">
                {approval.request_record_id && (
                  <Link
                    href={`/actions/${approval.request_record_id}`}
                    className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 hover:bg-accent/70"
                  >
                    Request record
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                )}
                {approval.resolution_record_id && (
                  <Link
                    href={`/actions/${approval.resolution_record_id}`}
                    className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 hover:bg-accent/70"
                  >
                    Resolution record
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                )}
              </div>

              {/* Context */}
              {Object.keys(approval.context).length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Context</p>
                  <pre className="mt-1 overflow-x-auto rounded-md border border-border bg-accent/30 p-3 text-xs">
                    {JSON.stringify(approval.context, null, 2)}
                  </pre>
                </div>
              )}

              {/* Decisions trail */}
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">
                  Decisions ({approval.decisions.length})
                </p>
                {approval.decisions.length === 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">No votes yet.</p>
                ) : (
                  <div className="mt-1 space-y-2">
                    {approval.decisions.map((d, i) => (
                      <div
                        key={i}
                        className="rounded-md border border-border bg-accent/30 p-3"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Badge
                              className={cn(
                                "text-xs capitalize",
                                d.decision === "approve"
                                  ? "bg-emerald-500/15 text-emerald-400"
                                  : d.decision === "reject"
                                    ? "bg-red-500/15 text-red-400"
                                    : "bg-zinc-500/15 text-zinc-400",
                              )}
                            >
                              {d.decision}
                            </Badge>
                            <span className="text-sm font-medium">{d.approver}</span>
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {formatDate(d.decided_at)}
                          </span>
                        </div>
                        {d.note && (
                          <p className="mt-2 text-xs text-muted-foreground">{d.note}</p>
                        )}
                        {d.signature && (
                          <p className="mt-1 font-mono text-[10px] text-muted-foreground/70 break-all">
                            sig: {d.signature.slice(0, 32)}… · key: {d.key_id}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Pending Tab ────────────────────────────────────────────────────────────

function PendingTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading } = useApprovals({ status: "pending", limit: 100 });
  const cancel = useCancelApproval();

  const [decisionTarget, setDecisionTarget] = useState<{
    approval: Approval;
    decision: "approve" | "reject";
  } | null>(null);
  const [detail, setDetail] = useState<Approval | null>(null);
  const [cancelConfirm, setCancelConfirm] = useState<string | null>(null);

  const handleCancel = async (id: string) => {
    try {
      await cancel.mutateAsync(id);
      toast.success("Approval cancelled");
      setCancelConfirm(null);
    } catch {
      toast.error("Failed to cancel approval");
      setCancelConfirm(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {data?.total ?? 0} pending {data?.total === 1 ? "approval" : "approvals"}
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Action</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Votes</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Expires</TableHead>
                {isAdmin && <TableHead className="w-48" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: isAdmin ? 7 : 6 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !data?.approvals.length ? (
                <TableRow>
                  <TableCell
                    colSpan={isAdmin ? 7 : 6}
                    className="py-12 text-center text-muted-foreground text-sm"
                  >
                    No pending approvals. When an agent requests human review, it will appear here.
                  </TableCell>
                </TableRow>
              ) : (
                data.approvals.map((a) => {
                  const approveCount = a.decisions.filter((d) => d.decision === "approve").length;
                  return (
                    <TableRow key={a.id}>
                      <TableCell>
                        <button
                          onClick={() => setDetail(a)}
                          className="text-left hover:underline"
                        >
                          <p className="font-medium text-sm">{a.action_name}</p>
                          {a.action_summary && (
                            <p className="text-xs text-muted-foreground line-clamp-1">
                              {a.action_summary}
                            </p>
                          )}
                        </button>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {a.requested_by_agent}
                      </TableCell>
                      <TableCell>
                        <Badge className={cn("text-xs capitalize", RISK_COLORS[a.risk_tier])}>
                          {a.risk_tier}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm">
                        {approveCount}/{a.approvers_required}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatRelativeTime(a.requested_at)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {a.expires_at ? formatRelativeTime(a.expires_at) : "—"}
                      </TableCell>
                      {isAdmin && (
                        <TableCell>
                          {cancelConfirm === a.id ? (
                            <div className="flex gap-1">
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleCancel(a.id)}
                                disabled={cancel.isPending}
                                className="h-7 text-xs px-2"
                              >
                                Confirm cancel
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setCancelConfirm(null)}
                                className="h-7 w-7 p-0"
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-1">
                              <Button
                                size="sm"
                                onClick={() => setDecisionTarget({ approval: a, decision: "approve" })}
                                className="h-7 text-xs bg-emerald-500/90 hover:bg-emerald-500 text-black"
                              >
                                <Check className="mr-1 h-3 w-3" /> Approve
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setDecisionTarget({ approval: a, decision: "reject" })}
                                className="h-7 text-xs border-red-500/30 text-red-400 hover:bg-red-500/10"
                              >
                                <X className="mr-1 h-3 w-3" /> Reject
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setCancelConfirm(a.id)}
                                title="Cancel approval request"
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                              >
                                <Ban className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <DecisionDialog
        approval={decisionTarget?.approval ?? null}
        decision={decisionTarget?.decision ?? null}
        onClose={() => setDecisionTarget(null)}
      />
      <DetailDialog approval={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

// ── History Tab ────────────────────────────────────────────────────────────

function HistoryTab() {
  const [statusFilter, setStatusFilter] = useState<string>(ALL_VALUE);
  const [riskFilter, setRiskFilter] = useState<string>(ALL_VALUE);
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<Approval | null>(null);

  const queryParams: ApprovalQueryParams = {
    limit: 50,
    offset,
    ...(statusFilter !== ALL_VALUE && { status: statusFilter as ApprovalStatus }),
    ...(riskFilter !== ALL_VALUE && { risk_tier: riskFilter as RiskTier }),
  };

  const { data, isLoading } = useApprovals(queryParams);

  const hasFilters = statusFilter !== ALL_VALUE || riskFilter !== ALL_VALUE;

  const clearFilters = () => {
    setStatusFilter(ALL_VALUE);
    setRiskFilter(ALL_VALUE);
    setOffset(0);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={statusFilter}
          onValueChange={(v) => { setStatusFilter(v); setOffset(0); }}
        >
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="All Statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All Statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
            <SelectItem value="expired">Expired</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={riskFilter}
          onValueChange={(v) => { setRiskFilter(v); setOffset(0); }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="All Risks" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All Risks</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
            <SelectItem value="low">Low</SelectItem>
          </SelectContent>
        </Select>

        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 h-4 w-4" /> Clear
          </Button>
        )}

        <p className="ml-auto text-sm text-muted-foreground">
          {data?.total ?? 0} {data?.total === 1 ? "approval" : "approvals"}
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Action</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Resolved</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !data?.approvals.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-12 text-center text-muted-foreground text-sm">
                    {hasFilters ? "No approvals match your filters." : "No approvals yet."}
                  </TableCell>
                </TableRow>
              ) : (
                data.approvals.map((a) => (
                  <TableRow
                    key={a.id}
                    onClick={() => setDetail(a)}
                    className="cursor-pointer"
                  >
                    <TableCell>
                      <p className="font-medium text-sm">{a.action_name}</p>
                      {a.action_summary && (
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {a.action_summary}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {a.requested_by_agent}
                    </TableCell>
                    <TableCell>
                      <Badge className={cn("text-xs capitalize", RISK_COLORS[a.risk_tier])}>
                        {a.risk_tier}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={cn("text-xs capitalize", STATUS_COLORS[a.status])}>
                        {a.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(a.requested_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {a.resolved_at ? formatDate(a.resolved_at) : "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {data && data.total > 50 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {offset + 1}–{Math.min(offset + 50, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - 50))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + 50 >= data.total}
              onClick={() => setOffset((o) => o + 50)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <DetailDialog approval={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function ApprovalsPage() {
  const { isAdmin } = useAuth();

  // Fetch summary data separately so counts don't depend on tab being active
  const { data: pendingData } = useApprovals({ status: "pending", limit: 1 });
  const { data: allData } = useApprovals({ limit: 1 });

  const pendingCount = pendingData?.total ?? 0;
  const totalCount = allData?.total ?? 0;

  const criticalPending = useMemo(
    () =>
      pendingData?.approvals.filter((a) => a.risk_tier === "critical").length ?? 0,
    [pendingData],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Approvals</h1>
        <p className="text-sm text-muted-foreground">
          Human-in-the-loop review for high-risk agent actions. Every decision is
          cryptographically signed and written to the audit chain.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pending Review
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className={cn("text-3xl font-bold", pendingCount > 0 && "text-amber-400")}>
              {pendingCount}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Approvals
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{totalCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Oversight
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <UserCheck className="h-4 w-4 text-emerald-400" />
              <p className="text-sm text-muted-foreground">
                EU AI Act Art. 14 compliant
              </p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Signed decisions · dual-approval ready
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Critical-pending alert */}
      {criticalPending > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-red-500/30 bg-red-500/5 px-4 py-3">
          <ShieldAlert className="h-5 w-5 shrink-0 text-red-400" />
          <p className="text-sm text-red-400">
            <span className="font-semibold">
              {criticalPending} critical {criticalPending === 1 ? "approval" : "approvals"}
            </span>{" "}
            awaiting review. These represent the highest-risk agent actions.
          </p>
        </div>
      )}

      {/* Admin-only hint */}
      {!isAdmin && (
        <div className="flex items-center gap-3 rounded-md border border-border bg-accent/30 px-4 py-3">
          <Clock className="h-5 w-5 shrink-0 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            You have read-only access. An admin API key is required to approve or reject requests.
          </p>
        </div>
      )}

      {/* Tabs */}
      <Tabs defaultValue="pending">
        <TabsList>
          <TabsTrigger value="pending">
            Pending
            {pendingCount > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                {pendingCount}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="pending" className="mt-4">
          <PendingTab isAdmin={isAdmin} />
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <HistoryTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
