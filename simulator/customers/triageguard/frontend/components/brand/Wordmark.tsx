/**
 * TriageGuard wordmark — glyph + DM Serif Display lockup.
 *
 * The wordmark pairs the stethoscope-pulse glyph with "TriageGuard" set in
 * DM Serif Display. The serif's high-contrast strokes plus the teal "Guard"
 * suffix make this read as a clinical product rather than a tech brand.
 *
 * Sizes: "sm" (24px glyph), "md" (32px), "lg" (40px), "xl" (64px). All sizes
 * tested in the look book (app/page.tsx) and verified to read cleanly at
 * each step.
 */

import * as React from "react";
import { Glyph } from "./Glyph";
import { cn } from "@/lib/utils";

export interface WordmarkProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: "sm" | "md" | "lg" | "xl";
  /** Glyph only — for tight placements (favicons, sidebar collapse). */
  glyphOnly?: boolean;
  /** Tagline rendered under the lockup. Optional — splash / footer use. */
  tagline?: boolean;
}

const sizeMap = {
  sm: { glyph: 24, text: "text-lg", gap: "gap-2" },
  md: { glyph: 32, text: "text-2xl", gap: "gap-2.5" },
  lg: { glyph: 40, text: "text-3xl", gap: "gap-3" },
  xl: { glyph: 64, text: "text-5xl", gap: "gap-4" },
} as const;

export function Wordmark({
  size = "md",
  glyphOnly,
  tagline,
  className,
  ...rest
}: WordmarkProps) {
  const s = sizeMap[size];

  if (glyphOnly) {
    return (
      <div className={cn("inline-flex", className)} {...rest}>
        <Glyph size={s.glyph} />
      </div>
    );
  }

  return (
    <div className={cn("inline-flex flex-col", className)} {...rest}>
      <div className={cn("inline-flex items-center", s.gap)}>
        <Glyph size={s.glyph} />
        <span
          className={cn(
            "font-serif font-normal tracking-tight leading-none text-[var(--ink)]",
            s.text,
          )}
          style={{ letterSpacing: "-0.015em" }}
        >
          Triage
          <span style={{ color: "var(--teal)" }}>Guard</span>
        </span>
      </div>
      {tagline && (
        <span className="mt-1.5 font-sans text-xs text-[var(--ink-3)] tracking-wide">
          AI triage for the telehealth front door.
        </span>
      )}
    </div>
  );
}
