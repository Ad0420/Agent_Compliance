import { cn } from "@/lib/utils";
import { RESULT_COLORS } from "@/lib/constants";

export function StatusBadge({ result }: { result: string }) {
  const colors = RESULT_COLORS[result] || RESULT_COLORS.pending;
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", colors.bg, colors.text)}>
      {result}
    </span>
  );
}
