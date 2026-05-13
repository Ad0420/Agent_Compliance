import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function SectionError({ message }: { message: string }) {
  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardContent className="flex items-start gap-3 p-4">
        <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-sm font-medium text-amber-400">
            Could not load this section
          </p>
          <p className="text-xs text-muted-foreground">{message}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-dashed border-border px-4 py-8 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
