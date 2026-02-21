"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface JsonViewerProps {
  data: Record<string, unknown> | unknown[];
  title?: string;
  defaultExpanded?: boolean;
}

export function JsonViewer({ data, title, defaultExpanded = false }: JsonViewerProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);

  const isEmpty = !data || (typeof data === "object" && Object.keys(data).length === 0);

  if (isEmpty) {
    return title ? (
      <div className="rounded-lg border border-border bg-card p-3">
        <span className="text-sm font-medium text-muted-foreground">{title}</span>
        <span className="ml-2 text-xs text-muted-foreground">empty</span>
      </div>
    ) : null;
  }

  const jsonString = JSON.stringify(data, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between p-3 text-left hover:bg-accent/50"
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {title || "Data"}
          <span className="text-xs text-muted-foreground">
            ({Object.keys(data).length} {Object.keys(data).length === 1 ? "key" : "keys"})
          </span>
        </span>
      </button>
      {expanded && (
        <div className="relative border-t border-border">
          <button
            onClick={handleCopy}
            className="absolute right-2 top-2 rounded p-1 hover:bg-accent"
            title="Copy JSON"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5 text-muted-foreground" />}
          </button>
          <pre className={cn("overflow-auto p-4 text-xs font-mono max-h-96", "text-muted-foreground")}>
            {jsonString}
          </pre>
        </div>
      )}
    </div>
  );
}
