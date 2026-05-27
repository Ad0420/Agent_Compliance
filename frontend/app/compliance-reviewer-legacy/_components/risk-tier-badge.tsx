import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const RISK_COLORS: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400 border-red-500/30",
  high: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

export function RiskTierBadge({
  tier,
  className,
}: {
  tier: string | null | undefined;
  className?: string;
}) {
  const key = (tier ?? "low").toLowerCase();
  const colorClass = RISK_COLORS[key] ?? RISK_COLORS.low;
  return (
    <Badge
      variant="outline"
      className={cn("text-xs capitalize border", colorClass, className)}
    >
      {key}
    </Badge>
  );
}
