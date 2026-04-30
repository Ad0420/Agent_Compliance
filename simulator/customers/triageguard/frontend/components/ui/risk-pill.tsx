/**
 * RiskPill — color-coded clinical risk tier indicator.
 *
 * Maps `low | medium | high | critical` to four distinct treatments. Used by
 * the session pipeline UI when an agent flags a triage decision that needs
 * nurse review (e.g. red-flag terms detected, AI level overridden).
 *
 * Color logic:
 *   low      -> moss    (calm, "this is fine")
 *   medium   -> taupe   (warm neutral, "look at this" — intentionally
 *                        unsaturated so the alarm has somewhere to go)
 *   high     -> amber   (hot, "you need to act")
 *   critical -> crimson (filled, the surface alarm — TriageGuard's
 *                        signature beat)
 *
 * High and critical are intentionally warm/red so they can't be missed even
 * at a glance. Critical is the only filled tier.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { riskTiers, type RiskTier } from "@/lib/design/tokens";

export interface RiskPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  tier: RiskTier;
  /** Override the default label ("Low" / "Medium" / "High" / "Critical"). */
  label?: string;
  /** Compact rendering — 18px tall, 11px text. Use in dense queue rows. */
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
