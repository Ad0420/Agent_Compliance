"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChevronDown, ChevronRight, FileSearch } from "lucide-react";
import { formatDate } from "@/lib/utils";
import { EmptyState } from "./section-error";
import type { ComplianceReviewTrailEntry } from "@/lib/api-server";

/**
 * Audit-of-audit panel: surfaces the compliance team's own activity on the
 * dashboard. Collapsed by default — most reviewers don't need to see their
 * own log on every visit, but it has to be one click away so they can
 * demonstrate their work to auditors.
 */
export function ReviewTrailSection({
  entries,
  visible,
}: {
  entries: ComplianceReviewTrailEntry[];
  visible: boolean;
}) {
  const [open, setOpen] = useState(false);

  if (!visible) {
    // User doesn't have permission to see the review trail (e.g. developer).
    return null;
  }

  return (
    <Card>
      <CardHeader
        className="pb-3 cursor-pointer select-none"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {open ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            <FileSearch className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">Reviewer audit trail</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              {entries.length} recent entries
            </Badge>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                setOpen((v) => !v);
              }}
            >
              {open ? "Hide" : "Show"}
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-1 ml-6">
          Audit-of-audit: every read/export your compliance team performed in
          this dashboard. Show this to your auditor as evidence the team
          actually reviewed the records.
        </p>
      </CardHeader>
      {open ? (
        <CardContent className="p-0">
          {entries.length === 0 ? (
            <div className="p-6">
              <EmptyState message="No reviewer activity recorded yet." />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Reviewer</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Path</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="text-xs text-muted-foreground">
                      {e.occurred_at ? formatDate(e.occurred_at) : "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {e.clerk_user_id ? e.clerk_user_id.slice(0, 14) : "—"}
                    </TableCell>
                    <TableCell className="text-xs">{e.action}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {e.target_type ?? "—"}
                      {e.target_id ? (
                        <span className="ml-1 opacity-70">
                          {e.target_id.slice(0, 8)}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground max-w-[200px] truncate">
                      {e.http_method ? `${e.http_method} ` : ""}
                      {e.http_path ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      ) : null}
    </Card>
  );
}
