/**
 * ScribeMD glyph — a stylized clinical waveform fused with the terminal of an "S".
 *
 * The glyph reads as: a calm sound wave (ambient listening) that rises into a
 * single confident pulse (the chart entry), framed inside a soft squircle. No
 * shields, no checkmarks — those belong to Vera. The waveform metaphor leans
 * into ScribeMD's value prop: it heard the visit, it wrote the note.
 *
 * Renders cleanly at 24px, 32px, and 64px (tested in app/page.tsx — the look
 * book has a sizes row that demonstrates each).
 */

import * as React from "react";

export interface GlyphProps extends React.SVGAttributes<SVGSVGElement> {
  size?: number;
  /** Tone — "primary" uses cobalt; "ink" inverts to dark for use on light pills. */
  tone?: "primary" | "ink" | "white";
}

export function Glyph({
  size = 32,
  tone = "primary",
  className,
  ...rest
}: GlyphProps) {
  const fill =
    tone === "primary" ? "#2E5BD8" : tone === "ink" ? "#1B1A17" : "#FFFFFF";
  const wave =
    tone === "primary" ? "#FFFFFF" : tone === "ink" ? "#FAF7F2" : "#2E5BD8";

  return (
    <svg
      role="img"
      aria-label="ScribeMD glyph"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...rest}
    >
      {/* Squircle — clinical, calm. Rounded enough to feel like a UI tile. */}
      <rect x="0" y="0" width="32" height="32" rx="9" fill={fill} />
      {/* Waveform: small bars rising into one tall confident pulse. The rightmost
          bar sits a hair higher to read like the dot on an "i" / pulse spike. */}
      <g fill={wave}>
        <rect x="6" y="14" width="2" height="4" rx="1" />
        <rect x="9.5" y="12" width="2" height="8" rx="1" />
        <rect x="13" y="9" width="2" height="14" rx="1" />
        <rect x="16.5" y="6" width="2" height="20" rx="1" />
        <rect x="20" y="11" width="2" height="10" rx="1" />
        <rect x="23.5" y="13" width="2" height="6" rx="1" />
      </g>
    </svg>
  );
}
