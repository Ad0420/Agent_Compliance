/**
 * TriageGuard glyph — a stylized stethoscope-pulse hybrid.
 *
 * Two earpiece dots at the top connect through a thin curving tube into a
 * horizontal pulse line at the bottom. Reads as "ambient listening that
 * becomes a triage decision". Distinct from ScribeMD's pure waveform glyph
 * and from Vera's ShieldCheck.
 *
 * Renders cleanly at 24/32/40/64px (tested in app/page.tsx — the look book
 * has a sizes row that demonstrates each).
 */

import * as React from "react";

export interface GlyphProps extends React.SVGAttributes<SVGSVGElement> {
  size?: number;
  /** Tone — "primary" uses teal; "ink" inverts to dark for use on light pills;
   *  "white" inverts to white for use on filled teal/crimson surfaces. */
  tone?: "primary" | "ink" | "white";
}

export function Glyph({
  size = 32,
  tone = "primary",
  className,
  ...rest
}: GlyphProps) {
  // tile = the squircle background; mark = the stethoscope-pulse strokes.
  const tile =
    tone === "primary" ? "#FFFFFF" : tone === "ink" ? "#FBF8F1" : "#0F766E";
  const mark =
    tone === "primary" ? "#0F766E" : tone === "ink" ? "#0E1A1A" : "#FFFFFF";

  return (
    <svg
      role="img"
      aria-label="TriageGuard glyph"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...rest}
    >
      {/* Squircle frame — slightly tighter corner radius than ScribeMD's tile
          (rx 8 vs rx 9) so the brand shapes don't look identical at a glance. */}
      <rect x="0" y="0" width="32" height="32" rx="8" fill={tile} />

      {/* Stethoscope arc — left earpiece down to a U-bend, up to right
          earpiece. Stroke-only (no fill) so the form reads as instrumental. */}
      <path
        d="M9 6.5 V12 Q9 17 16 17 Q23 17 23 12 V6.5"
        fill="none"
        stroke={mark}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Earpiece dots */}
      <circle cx="9" cy="6.5" r="1.5" fill={mark} />
      <circle cx="23" cy="6.5" r="1.5" fill={mark} />

      {/* Pulse line — flat baseline, peak in the middle, flat baseline. The
          peak is offset slightly right of center so it reads like a real ECG
          spike rather than a perfect chevron. */}
      <path
        d="M4.5 24 H11 L13.5 19 L16 27 L18.5 21 L21 24 H27.5"
        fill="none"
        stroke={mark}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
