"use client";

/**
 * Interactive replacement for the static "Your organization is being
 * provisioned" message. Posts to `/api/dashboard/sync-membership` (which
 * proxies the backend's reconcile endpoint), then `router.refresh()`s the
 * server component on success so the api-keys table renders.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

export function ProvisioningCard() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  async function handleSync() {
    setError(null);
    try {
      const res = await fetch("/api/dashboard/sync-membership", {
        method: "POST",
      });
      if (res.ok) {
        startTransition(() => router.refresh());
        return;
      }
      const body = (await res.json().catch(() => null)) as
        | { detail?: string; error?: string }
        | null;
      const message =
        body?.detail ??
        body?.error ??
        `Sync failed (${res.status}). Try again in a moment.`;
      setError(message);
    } catch {
      setError("Could not reach the sync endpoint. Check your connection.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Your account isn&apos;t fully set up yet
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-muted-foreground">
        <p>
          We don&apos;t have a record of your membership in this organization
          yet. This usually clears up on its own within a few seconds, but if
          you&apos;re seeing this for more than a minute, try syncing
          manually.
        </p>
        {error ? <p className="text-red-400">{error}</p> : null}
        <div className="flex items-center gap-3">
          <Button onClick={handleSync} disabled={isPending}>
            {isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Syncing&hellip;
              </>
            ) : (
              "Sync from Clerk"
            )}
          </Button>
          <span className="text-xs">
            Still stuck?{" "}
            <a
              className="underline"
              href="mailto:support@usevera.xyz"
            >
              Contact support
            </a>
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
