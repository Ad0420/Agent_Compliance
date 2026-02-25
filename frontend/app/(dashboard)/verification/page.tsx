"use client";

import { useState } from "react";
import { useChainVerification } from "@/hooks/use-verification";
import { useCheckpoints, useCreateCheckpoint, useVerifyCheckpoints } from "@/hooks/use-checkpoints";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { formatDate, truncateHash } from "@/lib/utils";
import { ShieldCheck, ShieldAlert, Plus, RefreshCw, Loader2, CheckCircle2, XCircle, FileDown } from "lucide-react";
import { exportPdf } from "@/lib/api-client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { CheckpointVerifyAllResponse } from "@/lib/api-types";

export default function VerificationPage() {
  const { isAdmin } = useAuth();
  const { data: chainStatus, isLoading: chainLoading, refetch: refetchChain } = useChainVerification();
  const { data: checkpointsData, isLoading: cpLoading } = useCheckpoints();
  const createCheckpoint = useCreateCheckpoint();
  const verifyCheckpoints = useVerifyCheckpoints();
  const [verifyResults, setVerifyResults] = useState<CheckpointVerifyAllResponse | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  const handleCreateCheckpoint = async () => {
    await createCheckpoint.mutateAsync();
    setCreateDialogOpen(false);
  };

  const handleVerifyAll = async () => {
    const result = await verifyCheckpoints.mutateAsync();
    setVerifyResults(result);
  };

  const handleDownloadPdf = async () => {
    setDownloadingPdf(true);
    try {
      await exportPdf();
      toast.success("Audit report downloaded");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "PDF generation failed");
    } finally {
      setDownloadingPdf(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Verification</h1>
        <p className="text-sm text-muted-foreground">Chain integrity and checkpoint management</p>
      </div>

      {/* Chain integrity hero */}
      <Card className={cn(
        "border",
        chainStatus?.is_valid === true && "border-emerald-500/30",
        chainStatus?.is_valid === false && "border-red-500/50",
      )}>
        <CardContent className="flex items-center justify-between p-6">
          <div className="flex items-center gap-4">
            {chainLoading ? (
              <Loader2 className="h-10 w-10 animate-spin text-muted-foreground" />
            ) : chainStatus?.is_valid ? (
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10">
                <ShieldCheck className="h-8 w-8 text-emerald-400" />
              </div>
            ) : (
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-500/10">
                <ShieldAlert className="h-8 w-8 text-red-400 animate-pulse" />
              </div>
            )}
            <div>
              <p className={cn(
                "text-xl font-bold",
                chainStatus?.is_valid ? "text-emerald-400" : chainStatus?.is_valid === false ? "text-red-400" : "",
              )}>
                {chainLoading ? "Verifying..." : chainStatus?.is_valid ? "Chain Integrity Verified" : `Chain Broken at Sequence ${chainStatus?.first_invalid_sequence}`}
              </p>
              <p className="text-sm text-muted-foreground">
                {chainStatus ? `${chainStatus.records_checked} records checked` : ""}
              </p>
              {chainStatus?.message && (
                <p className="mt-1 text-xs text-muted-foreground">{chainStatus.message}</p>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => refetchChain()} disabled={chainLoading}>
              <RefreshCw className={cn("mr-1 h-4 w-4", chainLoading && "animate-spin")} />
              Re-verify
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
            >
              {downloadingPdf ? (
                <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Generating...</>
              ) : (
                <><FileDown className="mr-1 h-4 w-4" /> Download Report</>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Checkpoints */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Checkpoints</h2>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleVerifyAll} disabled={verifyCheckpoints.isPending}>
            {verifyCheckpoints.isPending ? (
              <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Verifying...</>
            ) : (
              <><ShieldCheck className="mr-1 h-4 w-4" /> Verify All</>
            )}
          </Button>
          {isAdmin && (
            <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="mr-1 h-4 w-4" /> Create Checkpoint
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Create Checkpoint</DialogTitle>
                  <DialogDescription>
                    This will create a signed snapshot of the current chain state with a Merkle root proof.
                    The checkpoint will be published to the external store.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
                  <Button onClick={handleCreateCheckpoint} disabled={createCheckpoint.isPending}>
                    {createCheckpoint.isPending ? (
                      <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Creating...</>
                    ) : (
                      "Create Checkpoint"
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      {/* Verify results */}
      {verifyResults && (
        <Card className={cn("border", verifyResults.all_valid ? "border-emerald-500/30" : "border-red-500/50")}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              {verifyResults.all_valid ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
              ) : (
                <XCircle className="h-5 w-5 text-red-400" />
              )}
              <span className="font-medium">
                {verifyResults.all_valid ? "All checkpoints valid" : "Some checkpoints failed verification"}
              </span>
              <span className="text-sm text-muted-foreground">({verifyResults.total_checked} checked)</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Checkpoints table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Sequence</TableHead>
                <TableHead>Hash</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Signature</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cpLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !checkpointsData?.checkpoints.length ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    No checkpoints yet. Create one to snapshot the current chain state.
                  </TableCell>
                </TableRow>
              ) : (
                checkpointsData.checkpoints.map((cp) => (
                  <TableRow key={cp.id}>
                    <TableCell>
                      <Badge variant="outline" className="font-mono">#{cp.sequence_at_checkpoint}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {truncateHash(cp.hash_at_checkpoint)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(cp.created_at)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {truncateHash(cp.signature)}
                    </TableCell>
                    <TableCell>
                      {cp.is_valid === true ? (
                        <Badge className="bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/20">Valid</Badge>
                      ) : cp.is_valid === false ? (
                        <Badge className="bg-red-500/15 text-red-400 hover:bg-red-500/20">Invalid</Badge>
                      ) : (
                        <Badge variant="outline" className="text-muted-foreground">Unverified</Badge>
                      )}
                    </TableCell>
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
