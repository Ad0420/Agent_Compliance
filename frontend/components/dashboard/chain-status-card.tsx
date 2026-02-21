"use client";

import { useChainVerification } from "@/hooks/use-verification";
import { Card, CardContent } from "@/components/ui/card";
import { ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

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
      <Card className="border-amber-500/30">
        <CardContent className="flex items-center gap-4 p-6">
          <ShieldAlert className="h-8 w-8 text-amber-400" />
          <div>
            <p className="text-sm font-medium">Unable to verify chain</p>
            <p className="text-xs text-muted-foreground">Could not connect to verification endpoint</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn("border", data.is_valid ? "border-emerald-500/30" : "border-red-500/50")}>
      <CardContent className="flex items-center gap-4 p-6">
        {data.is_valid ? (
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/10">
            <ShieldCheck className="h-7 w-7 text-emerald-400" />
          </div>
        ) : (
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10">
            <ShieldAlert className="h-7 w-7 text-red-400 animate-pulse" />
          </div>
        )}
        <div>
          <p className={cn("text-lg font-semibold", data.is_valid ? "text-emerald-400" : "text-red-400")}>
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
