"use client";

import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationControlsProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
}

export function PaginationControls({ total, limit, offset, onPageChange }: PaginationControlsProps) {
  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex items-center justify-between py-4">
      <span className="text-sm text-muted-foreground">
        Showing {start}–{end} of {total}
      </span>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          disabled={!hasPrev}
        >
          <ChevronLeft className="mr-1 h-4 w-4" />
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(offset + limit)}
          disabled={!hasNext}
        >
          Next
          <ChevronRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
