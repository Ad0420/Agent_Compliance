/**
 * RiskPill — color-coded clinical risk tier indicator.
 *
 * Maps `low | medium | high | critical` to four distinct treatments. Used by
 * the encounter pipeline UI when an agent flags an action that needs human
 * review (e.g. controlled substance order extracted from transcript).
 *
 * Color logic:
 *   low      -> sage   (calm, "this is fine")
 *   medium   -> amber  (warm, "look at this")
 *   high     -> coral  (hot, "you need to act")
 *   critical -> coral filled (alarm)
 *
 * High and critical are intentionally warm/red so they can't be missed even at
 * a glance. Low is a clinical sage rather than vivid green — keeps the surface
 * calm at rest.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { riskTiers, type RiskTier } from "@/lib/design/tokens";

export interface RiskPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  tier: RiskTier;
  /** Override the default label ("Low" / "Medium" / "High" / "Critical"). */
  label?: string;
  /** Compact rendering — 18px tall, 11px text. Use in dense tables. */
  compact?: boolean;
  /** Show a leading status dot. Defaults to true. */
  showDot?: boolean;
}

export function RiskPill({
  tier,
  label,
  compact,
  showDot = true,
  className,
  style,
  ...rest
}: RiskPillProps) {
  const t = riskTiers[tier];
  const text = label ?? t.label;

  return (
    <span
      role="status"
      aria-label={`Risk: ${text}`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-sans font-medium",
        compact ? "h-5 px-2 text-[11px]" : "h-6 px-2.5 text-xs",
        className,
      )}
      style={{
        backgroundColor: t.bg,
        color: t.fg,
        boxShadow: `inset 0 0 0 1px ${t.ring}`,
        ...style,
      }}
      {...rest}
    >
      {showDot && (
        <span
          aria-hidden
          className="size-1.5 rounded-full"
          style={{ backgroundColor: t.fg }}
        />
      )}
      {text}
    </span>
  );
}
