"use client";

import { useState } from "react";
import Link from "next/link";
import { useActions } from "@/hooks/use-actions";
import { useAgents } from "@/hooks/use-agents";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/shared/status-badge";
import { PaginationControls } from "@/components/shared/pagination-controls";
import { formatDate, formatDuration, truncateHash } from "@/lib/utils";
import { Search, X } from "lucide-react";
import type { ActionQueryParams } from "@/lib/api-types";

const ALL_VALUE = "__all__";

export default function ActionsPage() {
  const [filters, setFilters] = useState<ActionQueryParams>({ limit: 50, offset: 0 });
  const [searchInput, setSearchInput] = useState("");
  const { data, isLoading } = useActions(filters);
  const { data: agents } = useAgents();

  const updateFilter = (key: keyof ActionQueryParams, value: string | number | undefined) => {
    setFilters((prev) => ({ ...prev, [key]: value, offset: 0 }));
  };

  const handleSearch = () => {
    updateFilter("search", searchInput || undefined);
  };

  const clearFilters = () => {
    setFilters({ limit: 50, offset: 0 });
    setSearchInput("");
  };

  const hasFilters = filters.agent_name || filters.action_type || filters.result || filters.search;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Actions</h1>
        <p className="text-sm text-muted-foreground">Browse and filter all recorded agent actions</p>
      </div>

      {/* Filter bar */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search action name..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-9"
            />
          </div>
          <Select value={filters.agent_name || ALL_VALUE} onValueChange={(v) => updateFilter("agent_name", v === ALL_VALUE ? undefined : v)}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All Agents" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>All Agents</SelectItem>
              {agents?.map((a) => (
                <SelectItem key={a.id} value={a.name}>{a.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={filters.action_type || ALL_VALUE} onValueChange={(v) => updateFilter("action_type", v === ALL_VALUE ? undefined : v)}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>All Types</SelectItem>
              <SelectItem value="function_call">Function Call</SelectItem>
              <SelectItem value="llm_call">LLM Call</SelectItem>
              <SelectItem value="api_call">API Call</SelectItem>
              <SelectItem value="decision">Decision</SelectItem>
              <SelectItem value="tool_use">Tool Use</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.result || ALL_VALUE} onValueChange={(v) => updateFilter("result", v === ALL_VALUE ? undefined : v)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="All Results" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>All Results</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="failure">Failure</SelectItem>
            </SelectContent>
          </Select>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="mr-1 h-4 w-4" /> Clear
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Actions table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">Seq</TableHead>
                <TableHead>Timestamp</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead>Hash</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 8 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-16 animate-pulse rounded bg-accent" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : data?.records.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-12 text-center text-muted-foreground">
                    No actions found
                  </TableCell>
                </TableRow>
              ) : (
                data?.records.map((action) => (
                  <TableRow key={action.id} className="cursor-pointer hover:bg-accent/50">
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      <Link href={`/actions/${action.id}`} className="block">
                        #{action.sequence_number}
                      </Link>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <Link href={`/actions/${action.id}`} className="block">
                        {formatDate(action.action_timestamp)}
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
                    <TableCell className="text-xs text-muted-foreground">
                      <Link href={`/actions/${action.id}`} className="block">
                        {action.action_type}
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
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      <Link href={`/actions/${action.id}`} className="block">
                        {truncateHash(action.record_hash)}
                      </Link>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {data && data.total > 0 && (
        <PaginationControls
          total={data.total}
          limit={data.limit}
          offset={data.offset}
          onPageChange={(offset) => setFilters((prev) => ({ ...prev, offset }))}
        />
      )}
    </div>
  );
}
