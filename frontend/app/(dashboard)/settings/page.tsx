"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { useOrganization } from "@/hooks/use-organization";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/use-api-keys";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";
import { getKeyPrefix } from "@/lib/auth";
import { PERMISSION_COLORS } from "@/lib/constants";
import { Plus, Trash2, Copy, Check, AlertTriangle, Loader2, Bell } from "lucide-react";
import { cn } from "@/lib/utils";
import { updateAlertEmail } from "@/lib/api-client";

export default function SettingsPage() {
  const { isAdmin } = useAuth();
  const { data: org } = useOrganization();
  const { data: apiKeys, isLoading: keysLoading } = useApiKeys();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();
  const queryClient = useQueryClient();

  const [alertEmailInput, setAlertEmailInput] = useState<string>("");
  const [alertEmailSaved, setAlertEmailSaved] = useState(false);

  const alertEmailMutation = useMutation({
    mutationFn: (email: string | null) => updateAlertEmail(email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["organization"] });
      setAlertEmailSaved(true);
      setTimeout(() => setAlertEmailSaved(false), 2500);
    },
  });

  const handleSaveAlertEmail = () => {
    const trimmed = alertEmailInput.trim();
    alertEmailMutation.mutate(trimmed || null);
  };

  const handleClearAlertEmail = () => {
    setAlertEmailInput("");
    alertEmailMutation.mutate(null);
  };

  const [createOpen, setCreateOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyPerms, setNewKeyPerms] = useState<string[]>(["read", "write"]);
  const [newKeyExpiry, setNewKeyExpiry] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null);

  const handleCreateKey = async () => {
    const result = await createApiKey.mutateAsync({
      name: newKeyName,
      permissions: newKeyPerms,
      ...(newKeyExpiry ? { expires_at: new Date(newKeyExpiry).toISOString() } : {}),
    });
    setCreatedKey(result.raw_key);
  };

  const handleCopyKey = async () => {
    if (createdKey) {
      await navigator.clipboard.writeText(createdKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleCloseCreate = () => {
    setCreateOpen(false);
    setCreatedKey(null);
    setNewKeyName("");
    setNewKeyPerms(["read", "write"]);
    setNewKeyExpiry("");
  };

  const handleRevoke = async (id: string) => {
    await revokeApiKey.mutateAsync(id);
    setRevokeConfirm(null);
  };

  const togglePerm = (perm: string) => {
    setNewKeyPerms((prev) =>
      prev.includes(perm) ? prev.filter((p) => p !== perm) : [...prev, perm],
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Organization and API key management</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Org info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Organization</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Name</span>
              <span className="font-medium">{org?.name ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">ID</span>
              <span className="font-mono text-xs">{org?.id ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Created</span>
              <span>{org ? formatDate(org.created_at) : "—"}</span>
            </div>
          </CardContent>
        </Card>

        {/* Current key info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Current Session</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">API Key</span>
              <span className="font-mono text-xs">{getKeyPrefix()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Permission Level</span>
              <Badge className={cn(PERMISSION_COLORS[isAdmin ? "admin" : "read"])}>
                {isAdmin ? "admin" : "read/write"}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tamper alert email */}
      {isAdmin && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-base">Tamper Alert Email</CardTitle>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Vera will send an email here if chain verification or checkpoint verification detects tampering.
              Required for EU AI Act Art. 73 incident notification readiness.
            </p>
          </CardHeader>
          <CardContent className="space-y-3">
            {org?.alert_email && (
              <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm">
                <Check className="h-4 w-4 text-emerald-400 shrink-0" />
                <span className="text-emerald-400 font-mono text-xs">{org.alert_email}</span>
              </div>
            )}
            <div className="flex gap-2">
              <Input
                type="email"
                value={alertEmailInput}
                onChange={(e) => setAlertEmailInput(e.target.value)}
                placeholder={org?.alert_email ?? "security@yourcompany.com"}
                className="text-sm"
              />
              <Button
                size="sm"
                onClick={handleSaveAlertEmail}
                disabled={!alertEmailInput.trim() || alertEmailMutation.isPending}
              >
                {alertEmailMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : alertEmailSaved ? (
                  <><Check className="mr-1 h-4 w-4 text-emerald-400" /> Saved</>
                ) : (
                  "Save"
                )}
              </Button>
              {org?.alert_email && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleClearAlertEmail}
                  disabled={alertEmailMutation.isPending}
                  className="text-muted-foreground"
                >
                  Clear
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* API Keys management (admin only) */}
      {isAdmin && (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">API Keys</h2>
            <Dialog open={createOpen} onOpenChange={(open) => { if (!open) handleCloseCreate(); else setCreateOpen(true); }}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="mr-1 h-4 w-4" /> Create Key
                </Button>
              </DialogTrigger>
              <DialogContent>
                {createdKey ? (
                  <>
                    <DialogHeader>
                      <DialogTitle>API Key Created</DialogTitle>
                      <DialogDescription>
                        Copy this key now. It will not be shown again.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                        <span className="text-sm text-amber-400">This key will only be shown once</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Input value={createdKey} readOnly className="font-mono text-xs" />
                        <Button size="sm" variant="outline" onClick={handleCopyKey}>
                          {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                    <DialogFooter>
                      <Button onClick={handleCloseCreate}>Done</Button>
                    </DialogFooter>
                  </>
                ) : (
                  <>
                    <DialogHeader>
                      <DialogTitle>Create API Key</DialogTitle>
                      <DialogDescription>Create a new API key for your organization.</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div>
                        <label className="text-sm font-medium">Name</label>
                        <Input
                          value={newKeyName}
                          onChange={(e) => setNewKeyName(e.target.value)}
                          placeholder="e.g., production-agent"
                          className="mt-1"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium">Expiry date <span className="text-muted-foreground font-normal">(optional)</span></label>
                        <Input
                          type="date"
                          value={newKeyExpiry}
                          onChange={(e) => setNewKeyExpiry(e.target.value)}
                          className="mt-1"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium">Permissions</label>
                        <div className="mt-2 flex gap-2">
                          {["read", "write", "admin"].map((perm) => (
                            <Button
                              key={perm}
                              size="sm"
                              variant={newKeyPerms.includes(perm) ? "default" : "outline"}
                              onClick={() => togglePerm(perm)}
                            >
                              {perm}
                            </Button>
                          ))}
                        </div>
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={handleCloseCreate}>Cancel</Button>
                      <Button
                        onClick={handleCreateKey}
                        disabled={!newKeyName.trim() || newKeyPerms.length === 0 || createApiKey.isPending}
                      >
                        {createApiKey.isPending ? (
                          <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Creating...</>
                        ) : (
                          "Create"
                        )}
                      </Button>
                    </DialogFooter>
                  </>
                )}
              </DialogContent>
            </Dialog>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Key Prefix</TableHead>
                    <TableHead>Permissions</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-16" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keysLoading ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-8 text-center">
                        <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  ) : !apiKeys?.length ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                        No API keys
                      </TableCell>
                    </TableRow>
                  ) : (
                    apiKeys.map((key) => (
                      <TableRow key={key.id} className={cn(!key.is_active && "opacity-50")}>
                        <TableCell className={cn("font-medium", !key.is_active && "line-through")}>
                          {key.name}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{key.key_prefix}</TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {key.permissions.map((p) => (
                              <Badge key={p} className={cn("text-[10px]", PERMISSION_COLORS[p])}>
                                {p}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(key.created_at)}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {key.expires_at ? formatDate(key.expires_at) : "Never"}
                        </TableCell>
                        <TableCell>
                          {key.is_active ? (
                            <Badge className="bg-emerald-500/15 text-emerald-400">Active</Badge>
                          ) : (
                            <Badge variant="outline" className="text-muted-foreground">Revoked</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {key.is_active && (
                            revokeConfirm === key.id ? (
                              <div className="flex gap-1">
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  onClick={() => handleRevoke(key.id)}
                                  disabled={revokeApiKey.isPending}
                                  className="h-7 text-xs"
                                >
                                  Confirm
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => setRevokeConfirm(null)}
                                  className="h-7 text-xs"
                                >
                                  Cancel
                                </Button>
                              </div>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setRevokeConfirm(key.id)}
                                className="h-7 text-muted-foreground hover:text-red-400"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )
                          )}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
