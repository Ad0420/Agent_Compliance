"use client";

/**
 * Client island for the API keys page. Renders the table + the
 * create-key modal + the one-time raw-key reveal.
 *
 * Phase 1 PR 4 (Stream C item C5): the create dialog now exposes a
 * Sandbox / Production toggle. Switching to Production fetches the
 * org's BAA status from `/api/dashboard/baa-status` (which proxies
 * `GET /v1/organizations/me/baa-status`). When no active BAA exists,
 * the "Create live key" button is disabled and an `<EmptyState>`
 * deep-links into `/customers` where BAAs are uploaded.
 *
 * The initial list is hydrated from a server-component fetch (via
 * `initialKeys`) so the first paint shows real data. After mutations
 * we re-fetch through the same server route handlers (`/api/dashboard/...`)
 * so the Clerk session token never has to be exposed to the client.
 */
import { useEffect, useState, useTransition } from "react";
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
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Plus,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  Loader2,
} from "lucide-react";

type ApiKeyKind = "test" | "live";

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  kind: ApiKeyKind;
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

// FastAPI wraps our structured error envelopes under a top-level
// ``detail`` key. Pull the code+detail back out so we can show the
// human-readable string and act on the machine code.
interface BackendErrorEnvelope {
  detail?:
    | string
    | {
        code?: string;
        detail?: string;
        fix_url?: string;
      };
  error?: string;
}

function extractErrorMessage(body: BackendErrorEnvelope): string {
  const d = body.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof d.detail === "string") {
    return d.detail;
  }
  if (typeof body.error === "string") return body.error;
  return "Failed to create key.";
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
  // Phase 1 PR 4: default Sandbox. Production is opt-in so the safer tier
  // is also the path of least resistance.
  const [newKeyKind, setNewKeyKind] = useState<ApiKeyKind>("test");
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [saveAck, setSaveAck] = useState(false);
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null);

  // BAA status: null = not yet fetched, undefined = fetch in progress,
  // boolean = fetched. The tri-state lets us show a loading shimmer the
  // first time the operator opens the Production tab without flashing
  // the EmptyState before the fetch resolves.
  const [baaActive, setBaaActive] = useState<boolean | null>(null);
  const [baaLoading, setBaaLoading] = useState(false);

  useEffect(() => {
    // Only fetch when (a) the dialog is open, (b) Production is selected,
    // and (c) we haven't already fetched. This avoids hitting the backend
    // on every dialog mount — most operators stay in Sandbox.
    if (!createOpen || newKeyKind !== "live" || baaActive !== null) return;
    let cancelled = false;
    setBaaLoading(true);
    fetch("/api/dashboard/baa-status")
      .then((res) => (res.ok ? res.json() : { active: false }))
      .then((data: { active?: boolean }) => {
        if (!cancelled) setBaaActive(Boolean(data?.active));
      })
      .catch(() => {
        if (!cancelled) setBaaActive(false);
      })
      .finally(() => {
        if (!cancelled) setBaaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [createOpen, newKeyKind, baaActive]);

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
        body: JSON.stringify({
          name: newKeyName,
          permissions: newKeyPerms,
          kind: newKeyKind,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as BackendErrorEnvelope;
        setCreateError(extractErrorMessage(body));
        // If the backend says no BAA, flip our cached state so the
        // EmptyState renders on the next render cycle.
        const detail = body.detail;
        if (
          detail &&
          typeof detail === "object" &&
          (detail.code === "baa_required" || detail.code === "baa_expired")
        ) {
          setBaaActive(false);
        }
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
          kind: created.kind,
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
    setNewKeyKind("test");
    setCreateError(null);
    setSaveAck(false);
    setCopied(false);
    // Reset baaActive too so the next open re-fetches in case the operator
    // uploaded a BAA in a different tab.
    setBaaActive(null);
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

  // Production tab is gated on BAA presence. Sandbox tab is always
  // enabled. We don't disable the submit button on Sandbox, regardless
  // of BAA state.
  const productionBlocked =
    newKeyKind === "live" && baaActive === false && !baaLoading;
  const canSubmit =
    Boolean(newKeyName.trim()) &&
    newKeyPerms.length > 0 &&
    !creating &&
    !productionBlocked &&
    !(newKeyKind === "live" && baaLoading);

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
                    <p className="text-xs text-muted-foreground">
                      Tier: <KindBadge kind={createdKey.kind} inline />
                    </p>
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
                    <Tabs
                      value={newKeyKind}
                      onValueChange={(v) => setNewKeyKind(v as ApiKeyKind)}
                    >
                      <TabsList className="grid w-full grid-cols-2">
                        <TabsTrigger value="test">Sandbox</TabsTrigger>
                        <TabsTrigger value="live">Production</TabsTrigger>
                      </TabsList>
                    </Tabs>

                    {newKeyKind === "live" && baaLoading ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Checking BAA status…
                      </div>
                    ) : null}

                    {productionBlocked ? (
                      <EmptyState
                        title="No active Business Associate Agreement on file"
                        subtitle="Production keys require a signed BAA covering your customer. Upload one on the Customers page, then return here."
                        ctaLabel="Go to Customers"
                        ctaHref="/customers"
                      />
                    ) : (
                      <>
                        <div>
                          <label className="text-sm font-medium">Name</label>
                          <Input
                            value={newKeyName}
                            onChange={(e) => setNewKeyName(e.target.value)}
                            placeholder={
                              newKeyKind === "live"
                                ? "e.g. production-agent"
                                : "e.g. dev-laptop"
                            }
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <label className="text-sm font-medium">
                            Permissions
                          </label>
                          <div className="mt-2 flex gap-2">
                            {PERMISSIONS.map((perm) => (
                              <Button
                                key={perm}
                                size="sm"
                                variant={
                                  newKeyPerms.includes(perm)
                                    ? "default"
                                    : "outline"
                                }
                                onClick={() => togglePerm(perm)}
                              >
                                {perm}
                              </Button>
                            ))}
                          </div>
                        </div>
                        {newKeyKind === "live" && baaActive === true && (
                          <p className="text-xs text-emerald-400">
                            BAA on file — production key allowed.
                          </p>
                        )}
                        {createError && (
                          <p className="text-sm text-red-400" role="alert">
                            {createError}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={handleCloseCreate}>
                      Cancel
                    </Button>
                    {!productionBlocked && (
                      <Button onClick={handleCreate} disabled={!canSubmit}>
                        {creating ? (
                          <>
                            <Loader2 className="mr-1 h-4 w-4 animate-spin" />{" "}
                            Creating…
                          </>
                        ) : newKeyKind === "live" ? (
                          "Create production key"
                        ) : (
                          "Create sandbox key"
                        )}
                      </Button>
                    )}
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
                <TableHead>Tier</TableHead>
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
                    colSpan={canRevoke ? 7 : 6}
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
                    <TableCell>
                      <KindBadge kind={key.kind} />
                    </TableCell>
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

function KindBadge({ kind, inline }: { kind: ApiKeyKind; inline?: boolean }) {
  // Sandbox keys are visually de-emphasised (neutral grey) so production
  // keys read as more weighty in the table — they're the ones an operator
  // actually needs to be careful about.
  if (kind === "live") {
    return (
      <Badge
        className={
          inline
            ? "ml-1 bg-emerald-500/15 text-[10px] text-emerald-400"
            : "bg-emerald-500/15 text-[10px] text-emerald-400"
        }
      >
        Production
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className={
        inline
          ? "ml-1 text-[10px] text-muted-foreground"
          : "text-[10px] text-muted-foreground"
      }
    >
      Sandbox
    </Badge>
  );
}
