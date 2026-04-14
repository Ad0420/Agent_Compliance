"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import {
  usePolicies,
  useCreatePolicy,
  useUpdatePolicy,
  useDeletePolicy,
  useViolations,
  useResolveViolation,
} from "@/hooks/use-policies";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import {
  Plus,
  Trash2,
  Check,
  Loader2,
  ShieldAlert,
  ToggleLeft,
  ToggleRight,
  ExternalLink,
  X,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";
import type {
  Policy,
  PolicyViolation,
  PolicyCreateInput,
  PolicySeverity,
  ConditionType,
  PolicyAction,
  ViolationQueryParams,
} from "@/lib/api-types";

// ── Severity styling ──────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<PolicySeverity, string> = {
  critical: "bg-red-500/15 text-red-400",
  high: "bg-orange-500/15 text-orange-400",
  medium: "bg-amber-500/15 text-amber-400",
  low: "bg-emerald-500/15 text-emerald-400",
};

const CONDITION_LABELS: Record<ConditionType, string> = {
  unknown_agent: "Unknown Agent",
  missing_reasoning: "Missing Reasoning",
  failure_rate: "Failure Rate",
  high_failure_burst: "High Failure Burst",
  consecutive_failures: "Consecutive Failures",
};

const CONDITION_DESCRIPTIONS: Record<ConditionType, string> = {
  unknown_agent: "Fires when the agent is not registered for this org",
  missing_reasoning: "Fires when data_subject_id is set but reasoning is empty",
  failure_rate: "Fires when failure rate exceeds threshold over a rolling window",
  high_failure_burst: "Fires when too many failures occur within 60 seconds",
  consecutive_failures: "Fires when the same agent fails N times in a row",
};

const ALL_VALUE = "__all__";

// ── Create/Edit Policy Dialog ─────────────────────────────────────────────

function PolicyFormDialog({
  open,
  onOpenChange,
  editPolicy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editPolicy?: Policy;
}) {
  const createPolicy = useCreatePolicy();
  const updatePolicy = useUpdatePolicy();

  const [name, setName] = useState(editPolicy?.name ?? "");
  const [description, setDescription] = useState(editPolicy?.description ?? "");
  const [conditionType, setConditionType] = useState<ConditionType>(
    editPolicy?.condition_type ?? "unknown_agent"
  );
  const [action, setAction] = useState<PolicyAction>(editPolicy?.action ?? "flag");
  const [severity, setSeverity] = useState<PolicySeverity>(editPolicy?.severity ?? "medium");
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(editPolicy?.condition_params ?? {}).map(([k, v]) => [k, String(v)])
    )
  );

  const isEditing = !!editPolicy;
  const isPending = createPolicy.isPending || updatePolicy.isPending;

  // Reset condition params when condition type changes
  const handleConditionTypeChange = (value: ConditionType) => {
    setConditionType(value);
    setParams({});
  };

  const getParamFields = () => {
    switch (conditionType) {
      case "failure_rate":
        return [
          { key: "threshold", label: "Threshold (0–1)", placeholder: "0.5", hint: "e.g. 0.5 = fire when >50% fail" },
          { key: "window", label: "Window (# records)", placeholder: "50", hint: "look at last N records" },
        ];
      case "high_failure_burst":
        return [
          { key: "threshold", label: "Max failures in 60s", placeholder: "5", hint: "fire when ≥ N failures in 60 seconds" },
        ];
      case "consecutive_failures":
        return [
          { key: "threshold", label: "Consecutive failures", placeholder: "3", hint: "fire when same agent fails N times in a row" },
        ];
      default:
        return [];
    }
  };

  const handleSubmit = async () => {
    const condition_params: Record<string, unknown> = {};
    getParamFields().forEach(({ key }) => {
      if (params[key] !== undefined && params[key] !== "") {
        condition_params[key] = Number(params[key]);
      }
    });

    try {
      if (isEditing) {
        await updatePolicy.mutateAsync({
          id: editPolicy.id,
          input: { name: name.trim(), description: description.trim() || undefined, condition_params, action, severity },
        });
        toast.success("Policy updated");
      } else {
        await createPolicy.mutateAsync({
          name: name.trim(),
          description: description.trim() || undefined,
          condition_type: conditionType,
          condition_params,
          action,
          severity,
        });
        toast.success("Policy created");
      }
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save policy");
    }
  };

  const paramFields = getParamFields();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Policy" : "Create Policy"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update this policy's settings."
              : "Define a rule to automatically detect compliance issues."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="text-sm font-medium">Name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Missing Reasoning Check"
              className="mt-1"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-sm font-medium">
              Description{" "}
              <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this policy detect?"
              className="mt-1"
            />
          </div>

          {/* Condition type — only editable on create */}
          {!isEditing && (
            <div>
              <label className="text-sm font-medium">Condition Type</label>
              <Select
                value={conditionType}
                onValueChange={(v) => handleConditionTypeChange(v as ConditionType)}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(CONDITION_LABELS) as ConditionType[]).map((type) => (
                    <SelectItem key={type} value={type}>
                      {CONDITION_LABELS[type]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-1 text-xs text-muted-foreground">
                {CONDITION_DESCRIPTIONS[conditionType]}
              </p>
            </div>
          )}

          {/* Dynamic params */}
          {paramFields.length > 0 && (
            <div className="space-y-3 rounded-md border border-border bg-accent/30 p-3">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Parameters
              </p>
              {paramFields.map(({ key, label, placeholder, hint }) => (
                <div key={key}>
                  <label className="text-sm font-medium">{label}</label>
                  <Input
                    type="number"
                    value={params[key] ?? ""}
                    onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
                    placeholder={placeholder}
                    className="mt-1"
                  />
                  <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
                </div>
              ))}
            </div>
          )}

          {/* Severity + Action row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium">Severity</label>
              <Select value={severity} onValueChange={(v) => setSeverity(v as PolicySeverity)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["critical", "high", "medium", "low"] as PolicySeverity[]).map((s) => (
                    <SelectItem key={s} value={s}>
                      <span className={cn("capitalize", SEVERITY_COLORS[s].split(" ")[1])}>{s}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium">Action</label>
              <Select value={action} onValueChange={(v) => setAction(v as PolicyAction)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="flag">Flag only</SelectItem>
                  <SelectItem value="email">Flag + Email alert</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!name.trim() || isPending}>
            {isPending ? (
              <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Saving...</>
            ) : isEditing ? (
              "Save changes"
            ) : (
              "Create policy"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Policies Tab ──────────────────────────────────────────────────────────

function PoliciesTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading } = usePolicies();
  const updatePolicy = useUpdatePolicy();
  const deletePolicy = useDeletePolicy();

  const [createOpen, setCreateOpen] = useState(false);
  const [editPolicy, setEditPolicy] = useState<Policy | undefined>(undefined);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const handleToggleActive = async (policy: Policy) => {
    try {
      await updatePolicy.mutateAsync({ id: policy.id, input: { is_active: !policy.is_active } });
      toast.success(policy.is_active ? "Policy deactivated" : "Policy activated");
    } catch {
      toast.error("Failed to update policy");
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deletePolicy.mutateAsync(id);
      toast.success("Policy deleted");
      setDeleteConfirm(null);
    } catch {
      toast.error("Failed to delete policy");
      setDeleteConfirm(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {data?.total ?? 0} {data?.total === 1 ? "policy" : "policies"}
        </p>
        {isAdmin && (
          <>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" /> Create Policy
            </Button>
            <PolicyFormDialog open={createOpen} onOpenChange={setCreateOpen} />
          </>
        )}
      </div>

      {editPolicy && (
        <PolicyFormDialog
          open={!!editPolicy}
          onOpenChange={(open) => { if (!open) setEditPolicy(undefined); }}
          editPolicy={editPolicy}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Condition</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                {isAdmin && <TableHead className="w-24" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: isAdmin ? 7 : 6 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !data?.policies.length ? (
                <TableRow>
                  <TableCell colSpan={isAdmin ? 7 : 6} className="py-12 text-center text-muted-foreground text-sm">
                    No policies yet.{isAdmin ? " Create one to start monitoring." : ""}
                  </TableCell>
                </TableRow>
              ) : (
                data.policies.map((policy) => (
                  <TableRow key={policy.id} className={cn(!policy.is_active && "opacity-50")}>
                    <TableCell>
                      <div>
                        <p className="font-medium text-sm">{policy.name}</p>
                        {policy.description && (
                          <p className="text-xs text-muted-foreground">{policy.description}</p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div>
                        <p className="text-sm">{CONDITION_LABELS[policy.condition_type]}</p>
                        {Object.keys(policy.condition_params).length > 0 && (
                          <p className="text-xs text-muted-foreground font-mono">
                            {Object.entries(policy.condition_params)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(", ")}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={cn(
                          "text-xs",
                          policy.action === "email"
                            ? "bg-blue-500/15 text-blue-400"
                            : "bg-zinc-500/15 text-zinc-400"
                        )}
                      >
                        {policy.action === "email" ? "Flag + Email" : "Flag"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={cn("text-xs capitalize", SEVERITY_COLORS[policy.severity])}>
                        {policy.severity}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {policy.is_active ? (
                        <Badge className="bg-emerald-500/15 text-emerald-400 text-xs">Active</Badge>
                      ) : (
                        <Badge variant="outline" className="text-muted-foreground text-xs">Inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(policy.created_at)}
                    </TableCell>
                    {isAdmin && (
                      <TableCell>
                        <div className="flex items-center gap-1">
                          {/* Edit */}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditPolicy(policy)}
                            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          {/* Toggle active */}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleToggleActive(policy)}
                            disabled={updatePolicy.isPending}
                            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                            title={policy.is_active ? "Deactivate" : "Activate"}
                          >
                            {policy.is_active ? (
                              <ToggleRight className="h-4 w-4 text-emerald-400" />
                            ) : (
                              <ToggleLeft className="h-4 w-4" />
                            )}
                          </Button>
                          {/* Delete */}
                          {deleteConfirm === policy.id ? (
                            <div className="flex gap-1">
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleDelete(policy.id)}
                                disabled={deletePolicy.isPending}
                                className="h-7 text-xs px-2"
                              >
                                Delete
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setDeleteConfirm(null)}
                                className="h-7 w-7 p-0"
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setDeleteConfirm(policy.id)}
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-red-400"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Violations Tab ────────────────────────────────────────────────────────

function ViolationsTab({ isAdmin }: { isAdmin: boolean }) {
  const [severityFilter, setSeverityFilter] = useState<string>(ALL_VALUE);
  const [resolvedFilter, setResolvedFilter] = useState<string>(ALL_VALUE);
  const [offset, setOffset] = useState(0);
  const [resolveId, setResolveId] = useState<string | null>(null);
  const [resolveNote, setResolveNote] = useState("");

  // Fetch all policies once so we can look up names per violation row
  const { data: policiesData } = usePolicies();

  const resolveViolation = useResolveViolation();

  const queryParams: ViolationQueryParams = {
    limit: 50,
    offset,
    ...(severityFilter !== ALL_VALUE && { severity: severityFilter as PolicySeverity }),
    ...(resolvedFilter === "open" && { resolved: false }),
    ...(resolvedFilter === "resolved" && { resolved: true }),
  };

  const { data, isLoading } = useViolations(queryParams);

  const hasFilters = severityFilter !== ALL_VALUE || resolvedFilter !== ALL_VALUE;

  const clearFilters = () => {
    setSeverityFilter(ALL_VALUE);
    setResolvedFilter(ALL_VALUE);
    setOffset(0);
  };

  const handleResolve = async (id: string) => {
    try {
      await resolveViolation.mutateAsync({ id, resolved_by: resolveNote.trim() || undefined });
      toast.success("Violation marked as resolved");
      setResolveId(null);
      setResolveNote("");
    } catch {
      toast.error("Failed to resolve violation");
      setResolveId(null);
      setResolveNote("");
    }
  };

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={severityFilter}
          onValueChange={(v) => { setSeverityFilter(v); setOffset(0); }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="All Severities" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All Severities</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
            <SelectItem value="low">Low</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={resolvedFilter}
          onValueChange={(v) => { setResolvedFilter(v); setOffset(0); }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="All" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="resolved">Resolved</SelectItem>
          </SelectContent>
        </Select>

        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 h-4 w-4" /> Clear
          </Button>
        )}

        <p className="ml-auto text-sm text-muted-foreground">
          {data?.total ?? 0} {data?.total === 1 ? "violation" : "violations"}
        </p>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Policy</TableHead>
                <TableHead>Condition</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Triggered</TableHead>
                <TableHead>Record</TableHead>
                <TableHead>Status</TableHead>
                {isAdmin && <TableHead className="w-28" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: isAdmin ? 7 : 6 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !data?.violations.length ? (
                <TableRow>
                  <TableCell colSpan={isAdmin ? 7 : 6} className="py-12 text-center text-muted-foreground text-sm">
                    {hasFilters ? "No violations match your filters." : "No violations recorded yet."}
                  </TableCell>
                </TableRow>
              ) : (
                data.violations.map((v) => (
                  <TableRow key={v.id} className={cn(v.resolved_at && "opacity-60")}>
                    <TableCell>
                      <span className="text-sm font-medium">
                        {policiesData?.policies.find((p) => p.id === v.policy_id)?.name
                          ?? (v.policy_id ? "Deleted policy" : "—")}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {(() => {
                        const ct = policiesData?.policies.find((p) => p.id === v.policy_id)?.condition_type;
                        return ct ? CONDITION_LABELS[ct] : "—";
                      })()}
                    </TableCell>
                    <TableCell>
                      <Badge className={cn("text-xs capitalize", SEVERITY_COLORS[v.severity])}>
                        {v.severity}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(v.triggered_at)}
                    </TableCell>
                    <TableCell>
                      {v.record_id ? (
                        <Link
                          href={`/actions/${v.record_id}`}
                          className="flex items-center gap-1 text-xs text-blue-400 hover:underline font-mono"
                        >
                          {v.record_id.slice(0, 8)}…
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {v.resolved_at ? (
                        <div>
                          <Badge className="bg-emerald-500/15 text-emerald-400 text-xs">Resolved</Badge>
                          {v.resolved_by && (
                            <p className="text-xs text-muted-foreground mt-0.5">by {v.resolved_by}</p>
                          )}
                        </div>
                      ) : (
                        <Badge variant="outline" className="text-amber-400 border-amber-500/30 text-xs">
                          Open
                        </Badge>
                      )}
                    </TableCell>
                    {isAdmin && (
                      <TableCell>
                        {!v.resolved_at && (
                          resolveId === v.id ? (
                            <div className="flex flex-col gap-1.5 min-w-[160px]">
                              <Input
                                placeholder="Resolved by (optional)"
                                value={resolveNote}
                                onChange={(e) => setResolveNote(e.target.value)}
                                className="h-7 text-xs"
                              />
                              <div className="flex gap-1">
                                <Button
                                  size="sm"
                                  onClick={() => handleResolve(v.id)}
                                  disabled={resolveViolation.isPending}
                                  className="h-7 text-xs flex-1"
                                >
                                  {resolveViolation.isPending ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <><Check className="mr-1 h-3 w-3" /> Resolve</>
                                  )}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => { setResolveId(null); setResolveNote(""); }}
                                  className="h-7 w-7 p-0"
                                >
                                  <X className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setResolveId(v.id)}
                              className="h-7 text-xs"
                            >
                              Resolve
                            </Button>
                          )
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Pagination */}
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
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function PoliciesPage() {
  const { isAdmin } = useAuth();
  const { data: policiesData } = usePolicies();
  const { data: violationsData } = useViolations({ resolved: false });

  const openViolations = violationsData?.total ?? 0;
  const activePolicies = policiesData?.policies.filter((p) => p.is_active).length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Policies</h1>
        <p className="text-sm text-muted-foreground">
          Automated compliance rules — evaluated against every action record at write time
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Policies</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{activePolicies}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Open Violations</CardTitle>
          </CardHeader>
          <CardContent>
            <p className={cn("text-3xl font-bold", openViolations > 0 && "text-amber-400")}>
              {openViolations}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Evaluation</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-emerald-400" />
              <p className="text-sm text-muted-foreground">Real-time, at write time</p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">Results are baked into each record's hash</p>
          </CardContent>
        </Card>
      </div>

      {/* Open violations alert */}
      {openViolations > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <ShieldAlert className="h-5 w-5 shrink-0 text-amber-400" />
          <p className="text-sm text-amber-400">
            <span className="font-semibold">{openViolations} open {openViolations === 1 ? "violation" : "violations"}</span>
            {" "}— review and resolve in the Violations tab.
          </p>
        </div>
      )}

      {/* Tabs */}
      <Tabs defaultValue="policies">
        <TabsList>
          <TabsTrigger value="policies">
            Policies
            {policiesData?.total ? (
              <span className="ml-1.5 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-medium">
                {policiesData.total}
              </span>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="violations">
            Violations
            {openViolations > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                {openViolations}
              </span>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="policies" className="mt-4">
          <PoliciesTab isAdmin={isAdmin} />
        </TabsContent>

        <TabsContent value="violations" className="mt-4">
          <ViolationsTab isAdmin={isAdmin} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
