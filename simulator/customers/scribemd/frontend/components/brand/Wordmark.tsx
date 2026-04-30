/**
 * ScribeMD wordmark — glyph + serif lockup.
 *
 * The wordmark pairs the waveform glyph with "ScribeMD" set in Source Serif 4.
 * The serif is the most direct visual contrast with Vera's Geist Sans-only
 * vocabulary — within 2 seconds you should be able to tell them apart on a
 * screenshare. "MD" is rendered slightly tighter and in cobalt to read like a
 * clinical credential.
 *
 * Sizes: "sm" (24px glyph), "md" (32px), "lg" (40px), "xl" (64px). All sizes
 * tested in the look book (app/page.tsx).
 */

import * as React from "react";
import { Glyph } from "./Glyph";
import { cn } from "@/lib/utils";

export interface WordmarkProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: "sm" | "md" | "lg" | "xl";
  /** When true, render the glyph only (used for compact placements). */
  glyphOnly?: boolean;
  /** Tagline rendered under the lockup. Optional — usually only on splash pages. */
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
            "font-serif font-semibold tracking-tight leading-none text-[var(--ink)]",
            s.text,
          )}
          style={{ letterSpacing: "-0.02em" }}
        >
          Scribe
          <span style={{ color: "var(--cobalt)", letterSpacing: "-0.04em" }}>
            MD
          </span>
        </span>
      </div>
      {tagline && (
        <span className="mt-1.5 ml-[calc(var(--glyph-gap)+0.25rem)] font-sans text-xs text-[var(--ink-3)] tracking-wide">
          Ambient AI scribe for the modern hospital.
        </span>
      )}
    </div>
  );
}
