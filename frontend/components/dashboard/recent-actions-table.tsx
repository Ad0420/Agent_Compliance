"use client";

import Link from "next/link";
import { useActions } from "@/hooks/use-actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/shared/status-badge";
import { formatRelativeTime, formatDuration } from "@/lib/utils";
import { ArrowRight } from "lucide-react";

export function RecentActionsTable() {
  const { data, isLoading } = useActions({ limit: 10 });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-4">
        <CardTitle className="text-base">Recent Actions</CardTitle>
        <Link href="/actions" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          View all <ArrowRight className="h-3 w-3" />
        </Link>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Result</TableHead>
              <TableHead className="text-right">Duration</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 5 }).map((_, j) => (
                    <TableCell key={j}>
                      <div className="h-4 w-20 animate-pulse rounded bg-accent" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : data?.records.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  No actions recorded yet
                </TableCell>
              </TableRow>
            ) : (
              data?.records.map((action) => (
                <TableRow key={action.id} className="cursor-pointer hover:bg-accent/50">
                  <TableCell className="text-xs text-muted-foreground">
                    <Link href={`/actions/${action.id}`} className="block">
                      {formatRelativeTime(action.action_timestamp)}
                    </Link>
                  </TableCell>
                  <TableCell className="font-medium text-sm">
                    <Link href={`/actions/${action.id}`} className="block">
                      {action.action_name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    <Link href={`/actions/${action.id}`} className="block">
                      {action.agent_name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link href={`/actions/${action.id}`} className="block">
                      <StatusBadge result={action.result} />
                    </Link>
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground font-mono">
                    <Link href={`/actions/${action.id}`} className="block">
                      {formatDuration(action.duration_ms)}
                    </Link>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
