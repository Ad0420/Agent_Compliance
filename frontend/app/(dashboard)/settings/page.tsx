"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { useOrganization } from "@/hooks/use-organization";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { formatDate, cn } from "@/lib/utils";
import { PERMISSION_COLORS } from "@/lib/constants";
import { Check, Loader2, Bell, Key } from "lucide-react";
import { updateAlertEmail } from "@/lib/api-client";

/**
 * /settings — org info + tamper-alert email (admin-only).
 *
 * Post-E4 cleanup: the duplicate API-key create/list/revoke UI that used to
 * live here was deleted. /api-keys is now the single surface for API-key
 * management. This page links there instead of re-implementing the same
 * table against a parallel set of endpoints.
 */
export default function SettingsPage() {
  const { isAdmin } = useAuth();
  const { data: org } = useOrganization();
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Organization and account configuration</p>
      </div>

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
          <div className="flex justify-between">
            <span className="text-muted-foreground">Your role</span>
            <Badge className={cn(PERMISSION_COLORS[isAdmin ? "admin" : "read"])}>
              {isAdmin ? "admin" : "member"}
            </Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Key className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">API Keys</CardTitle>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Manage the API keys your SDK uses to record actions.
          </p>
        </CardHeader>
        <CardContent>
          <Button asChild size="sm">
            <Link href="/api-keys">Open API Keys →</Link>
          </Button>
        </CardContent>
      </Card>

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
    </div>
  );
}
