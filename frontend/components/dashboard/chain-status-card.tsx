"use client";

import { useChainVerification } from "@/hooks/use-verification";
import { Card, CardContent } from "@/components/ui/card";
import { ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Chain integrity card.
 *
 * Status colours come from the warm-paper status tokens defined in
 * `globals.css` under `.dashboard` (`--olive`, `--amber`, `--brick`).
 * Inside the dashboard scope these render as oxidised olive / warm amber
 * / oxidised brick; outside the scope the tokens fall back to undefined
 * and the colour is inherited from the surrounding theme, but this
 * component is only ever rendered inside `(dashboard)/` routes.
 */
export function ChainStatusCard() {
  const { data, isLoading, error } = useChainVerification();

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-4 p-6">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Verifying chain integrity...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="border-[var(--amber)]/30">
        <CardContent className="flex items-center gap-4 p-6">
          <ShieldAlert className="h-8 w-8 text-[var(--amber)]" />
          <div>
            <p className="text-sm font-medium">Unable to verify chain</p>
            <p className="text-xs text-muted-foreground">Could not connect to verification endpoint</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn("border", data.is_valid ? "border-[var(--olive)]/30" : "border-[var(--brick)]/50")}>
      <CardContent className="flex items-center gap-4 p-6">
        {data.is_valid ? (
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--olive-bg)]">
            <ShieldCheck className="h-7 w-7 text-[var(--olive)]" />
          </div>
        ) : (
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--brick-bg)]">
            <ShieldAlert className="h-7 w-7 text-[var(--brick)] animate-pulse" />
          </div>
        )}
        <div>
          <p
            className={cn(
              "font-display text-lg",
              data.is_valid ? "text-[var(--olive)]" : "text-[var(--brick)]",
            )}
          >
            {data.is_valid ? "Chain Integrity Verified" : `CHAIN BROKEN at sequence ${data.first_invalid_sequence}`}
          </p>
          <p className="text-sm text-muted-foreground">
            {data.records_checked} records checked &middot; {data.message}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
