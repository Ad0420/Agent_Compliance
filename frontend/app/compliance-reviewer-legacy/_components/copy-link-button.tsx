"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Check, Link2 } from "lucide-react";
import { toast } from "sonner";

/**
 * Copies the current page URL — including all `?range=`, `?severity=`, etc.
 * filters — to the clipboard. The URL IS the saved view: a regulator or
 * stakeholder can paste it back into the browser and (once authenticated
 * as a compliance reviewer) land on the exact same filtered dashboard.
 */
export function CopyLinkButton() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (typeof window === "undefined") return;
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Saved-view URL copied to clipboard");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — copy from the address bar instead");
    }
  };

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            type="button"
            onClick={handleCopy}
            className="gap-1.5"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <Link2 className="h-3.5 w-3.5" />
            )}
            <span className="text-xs">
              {copied ? "Copied" : "Copy shareable link"}
            </span>
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-xs text-xs">
          This URL captures your current filters — share with regulators or
          your CTO. Anyone with the link still needs Clerk access to your
          organization to view the data.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
