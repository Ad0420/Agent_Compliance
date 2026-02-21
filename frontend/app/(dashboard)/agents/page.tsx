"use client";

import Link from "next/link";
import { useAgents } from "@/hooks/use-agents";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate } from "@/lib/utils";
import { Loader2 } from "lucide-react";

export default function AgentsPage() {
  const { data: agents, isLoading } = useAgents();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
        <p className="text-sm text-muted-foreground">Registered AI agents in your organization</p>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Metadata</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : !agents?.length ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No agents registered yet
                  </TableCell>
                </TableRow>
              ) : (
                agents.map((agent) => (
                  <TableRow key={agent.id} className="cursor-pointer hover:bg-accent/50">
                    <TableCell className="font-medium">
                      <Link href={`/agents/${agent.id}`} className="block">
                        {agent.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      <Link href={`/agents/${agent.id}`} className="block">
                        {agent.description || "—"}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      <Link href={`/agents/${agent.id}`} className="block">
                        {formatDate(agent.created_at)}
                      </Link>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <Link href={`/agents/${agent.id}`} className="block">
                        {Object.keys(agent.metadata).length} keys
                      </Link>
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
