"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useAction } from "@/hooks/use-actions";
import { verifyRecord } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/shared/status-badge";
import { JsonViewer } from "@/components/shared/json-viewer";
import { formatDate, formatDuration, truncateHash } from "@/lib/utils";
import { ArrowLeft, ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import type { RecordVerification } from "@/lib/api-types";

export default function ActionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: action, isLoading } = useAction(id);
  const [verification, setVerification] = useState<RecordVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const result = await verifyRecord(id);
      setVerification(result);
    } catch {
      setVerification(null);
    } finally {
      setVerifying(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!action) {
    return (
      <div className="py-20 text-center text-muted-foreground">Action not found</div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/actions">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-1 h-4 w-4" /> Back
          </Button>
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold">{action.action_name}</h1>
            <StatusBadge result={action.result} />
          </div>
          <p className="text-sm text-muted-foreground">{formatDate(action.action_timestamp)}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Action details */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Identity</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Agent" value={action.agent_name} />
              <Row label="Agent Version" value={action.agent_version} />
              <Row label="Model" value={action.model_id} />
              <Row label="Action Type" value={action.action_type} />
              <Row label="Target System" value={action.target_system} />
              <Row label="Target Resource" value={action.target_resource} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Result</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Result" value={<StatusBadge result={action.result} />} />
              <Row label="Duration" value={formatDuration(action.duration_ms)} />
              <Row label="Authorized By" value={action.authorized_by} />
              {action.error_message && (
                <div>
                  <p className="text-xs text-muted-foreground">Error</p>
                  <p className="mt-0.5 rounded bg-red-500/10 p-2 text-xs text-red-400 font-mono">
                    {action.error_message}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Chain integrity */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Chain Integrity</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Sequence Number</p>
                <Badge variant="outline" className="mt-1 font-mono">#{action.sequence_number}</Badge>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Record Hash</p>
                <p className="mt-1 font-mono text-xs break-all text-muted-foreground">{action.record_hash}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Previous Hash</p>
                <p className="mt-1 font-mono text-xs break-all text-muted-foreground">{action.previous_hash}</p>
              </div>

              <Button size="sm" variant="outline" onClick={handleVerify} disabled={verifying} className="mt-2">
                {verifying ? (
                  <><Loader2 className="mr-1 h-3 w-3 animate-spin" /> Verifying...</>
                ) : (
                  <><ShieldCheck className="mr-1 h-3 w-3" /> Verify This Record</>
                )}
              </Button>

              {verification && (
                <div className={`mt-2 rounded-lg p-3 text-sm ${
                  verification.record_hash_valid && verification.chain_link_valid
                    ? "bg-emerald-500/10 text-emerald-400"
                    : "bg-red-500/10 text-red-400"
                }`}>
                  <div className="flex items-center gap-2">
                    {verification.record_hash_valid && verification.chain_link_valid ? (
                      <ShieldCheck className="h-4 w-4" />
                    ) : (
                      <ShieldAlert className="h-4 w-4" />
                    )}
                    <span className="font-medium">
                      {verification.record_hash_valid && verification.chain_link_valid ? "Verified" : "Verification Failed"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs">{verification.message}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* JSON sections */}
      <div className="space-y-3">
        <JsonViewer data={action.input_data} title="Input Data" />
        <JsonViewer data={action.outcome} title="Outcome" />
        <JsonViewer data={action.reasoning} title="Reasoning" />
        <JsonViewer data={action.metadata} title="Metadata" />
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode | string | null }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
