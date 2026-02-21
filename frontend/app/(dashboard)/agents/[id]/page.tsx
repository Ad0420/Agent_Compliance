"use client";

import { use } from "react";
import Link from "next/link";
import { useAgent } from "@/hooks/use-agents";
import { useActions } from "@/hooks/use-actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/shared/status-badge";
import { JsonViewer } from "@/components/shared/json-viewer";
import { formatDate, formatDuration } from "@/lib/utils";
import { ArrowLeft, Loader2 } from "lucide-react";

export default function AgentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: agent, isLoading: agentLoading } = useAgent(id);
  const { data: actionsData } = useActions(
    agent ? { agent_name: agent.name, limit: 50 } : undefined,
  );

  if (agentLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!agent) {
    return <div className="py-20 text-center text-muted-foreground">Agent not found</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/agents">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-1 h-4 w-4" /> Back
          </Button>
        </Link>
        <div>
          <h1 className="text-xl font-bold">{agent.name}</h1>
          <p className="text-sm text-muted-foreground">{agent.description || "No description"}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Agent ID</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-xs break-all">{agent.id}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Created</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{formatDate(agent.created_at)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Total Actions</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{actionsData?.total ?? "—"}</p>
          </CardContent>
        </Card>
      </div>

      {Object.keys(agent.metadata).length > 0 && (
        <JsonViewer data={agent.metadata} title="Metadata" defaultExpanded />
      )}

      <div>
        <h2 className="mb-4 text-lg font-semibold">Recent Actions</h2>
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!actionsData?.records.length ? (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      No actions for this agent
                    </TableCell>
                  </TableRow>
                ) : (
                  actionsData.records.map((action) => (
                    <TableRow key={action.id} className="cursor-pointer hover:bg-accent/50">
                      <TableCell className="text-xs text-muted-foreground">
                        <Link href={`/actions/${action.id}`}>{formatDate(action.action_timestamp)}</Link>
                      </TableCell>
                      <TableCell className="font-medium text-sm">
                        <Link href={`/actions/${action.id}`}>{action.action_name}</Link>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{action.action_type}</TableCell>
                      <TableCell><StatusBadge result={action.result} /></TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground font-mono">
                        {formatDuration(action.duration_ms)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
