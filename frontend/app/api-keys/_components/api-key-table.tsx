"use client";

/**
 * Client island for the API keys page. Renders the table + the
 * create-key modal + the one-time raw-key reveal.
 *
 * The initial list is hydrated from a server-component fetch (via
 * `initialKeys`) so the first paint shows real data. After mutations
 * we re-fetch through the same server route handlers (`/api/dashboard/...`)
 * so the Clerk session token never has to be exposed to the client.
 */
import { useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Plus,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  Loader2,
} from "lucide-react";

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  created_at: string;
  revoked_at: string | null;
  expires_at: string | null;
  is_active: boolean;
}

interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}

interface Props {
  initialKeys: ApiKey[];
  canMint: boolean;
  canRevoke: boolean;
}

const PERMISSIONS = ["read", "write", "admin"] as const;

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function ApiKeyTable({ initialKeys, canMint, canRevoke }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [keys, setKeys] = useState<ApiKey[]>(initialKeys);
  // Deep-link: /api-keys?create=1 opens the create dialog on mount so the
  // first-run empty state on /dashboard (coming in E4) can jump straight
  // into key creation. Gated on canMint so non-admins don't see a dialog
  // they can't submit.
  const [createOpen, setCreateOpen] = useState(
    canMint && searchParams.get("create") === "1",
  );
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyPerms, setNewKeyPerms] = useState<string[]>(["read", "write"]);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [saveAck, setSaveAck] = useState(false);
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null);

  const togglePerm = (perm: string) => {
    setNewKeyPerms((prev) =>
      prev.includes(perm) ? prev.filter((p) => p !== perm) : [...prev, perm],
    );
  };

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch("/api/dashboard/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newKeyName, permissions: newKeyPerms }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail =
          typeof body?.error === "string"
            ? body.error
            : `Failed to create key (${res.status})`;
        setCreateError(detail);
        return;
      }
      const created = (await res.json()) as ApiKeyCreated;
      setCreatedKey(created);
      setSaveAck(false);
      // Optimistically prepend so the table reflects the new key when the
      // user closes the modal. Server refresh below catches up authoritative
      // state.
      setKeys((prev) => [
        {
          id: created.id,
          name: created.name,
          key_prefix: created.key_prefix,
          permissions: created.permissions,
          created_at: created.created_at,
          revoked_at: null,
          expires_at: created.expires_at,
          is_active: true,
        },
        ...prev,
      ]);
      startTransition(() => router.refresh());
    } finally {
      setCreating(false);
    }
  };

  const handleCloseCreate = () => {
    setCreateOpen(false);
    setCreatedKey(null);
    setNewKeyName("");
    setNewKeyPerms(["read", "write"]);
    setCreateError(null);
    setSaveAck(false);
    setCopied(false);
  };

  const handleCopy = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey.raw_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevoke = async (id: string) => {
    setRevoking(id);
    try {
      const res = await fetch(`/api/dashboard/api-keys/${id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setKeys((prev) =>
          prev.map((k) =>
            k.id === id
              ? { ...k, revoked_at: new Date().toISOString(), is_active: false }
              : k,
          ),
        );
        setRevokeConfirm(null);
        startTransition(() => router.refresh());
      }
    } finally {
      setRevoking(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">API Keys</h2>
        {canMint && (
          <Dialog
            open={createOpen}
            onOpenChange={(open) =>
              open ? setCreateOpen(true) : handleCloseCreate()
            }
          >
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-1 h-4 w-4" /> Create API Key
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
                      <span className="text-sm text-amber-400">
                        This key will only be shown once. Anyone with it can act
                        as your org.
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Input
                        value={createdKey.raw_key}
                        readOnly
                        className="font-mono text-xs"
                      />
                      <Button size="sm" variant="outline" onClick={handleCopy}>
                        {copied ? (
                          <Check className="h-4 w-4 text-emerald-400" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={saveAck}
                        onChange={(e) => setSaveAck(e.target.checked)}
                      />
                      I&apos;ve saved my API key somewhere safe.
                    </label>
                  </div>
                  <DialogFooter>
                    <Button onClick={handleCloseCreate} disabled={!saveAck}>
                      Done
                    </Button>
                  </DialogFooter>
                </>
              ) : (
                <>
                  <DialogHeader>
                    <DialogTitle>Create API Key</DialogTitle>
                    <DialogDescription>
                      Generate a new API key for your organization.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium">Name</label>
                      <Input
                        value={newKeyName}
                        onChange={(e) => setNewKeyName(e.target.value)}
                        placeholder="e.g. production-agent"
                        className="mt-1"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium">Permissions</label>
                      <div className="mt-2 flex gap-2">
                        {PERMISSIONS.map((perm) => (
                          <Button
                            key={perm}
                            size="sm"
                            variant={
                              newKeyPerms.includes(perm) ? "default" : "outline"
                            }
                            onClick={() => togglePerm(perm)}
                          >
                            {perm}
                          </Button>
                        ))}
                      </div>
                    </div>
                    {createError && (
                      <p className="text-sm text-red-400" role="alert">
                        {createError}
                      </p>
                    )}
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={handleCloseCreate}>
                      Cancel
                    </Button>
                    <Button
                      onClick={handleCreate}
                      disabled={
                        !newKeyName.trim() ||
                        newKeyPerms.length === 0 ||
                        creating
                      }
                    >
                      {creating ? (
                        <>
                          <Loader2 className="mr-1 h-4 w-4 animate-spin" />{" "}
                          Creating…
                        </>
                      ) : (
                        "Create"
                      )}
                    </Button>
                  </DialogFooter>
                </>
              )}
            </DialogContent>
          </Dialog>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Prefix</TableHead>
                <TableHead>Permissions</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Status</TableHead>
                {canRevoke && <TableHead className="w-16" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={canRevoke ? 6 : 5}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No API keys yet.
                    {canMint && " Click “Create API Key” to mint one."}
                  </TableCell>
                </TableRow>
              ) : (
                keys.map((key) => (
                  <TableRow
                    key={key.id}
                    className={!key.is_active ? "opacity-50" : undefined}
                  >
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {key.key_prefix}…
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {key.permissions.map((p) => (
                          <Badge key={p} className="text-[10px]">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(key.created_at)}
                    </TableCell>
                    <TableCell>
                      {key.is_active ? (
                        <Badge className="bg-emerald-500/15 text-emerald-400">
                          Active
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-muted-foreground">
                          Revoked
                        </Badge>
                      )}
                    </TableCell>
                    {canRevoke && (
                      <TableCell>
                        {key.is_active &&
                          (revokeConfirm === key.id ? (
                            <div className="flex gap-1">
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleRevoke(key.id)}
                                disabled={revoking === key.id}
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
                          ))}
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {!canMint && (
        <p className="text-xs text-muted-foreground">
          You can view this org&apos;s API keys but not create or revoke them.
          An admin must mint keys.
        </p>
      )}
    </div>
  );
}
