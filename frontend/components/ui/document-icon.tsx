"use client";

/**
 * DocumentIcon — Phase 1 PR 0b component primitive.
 *
 * The "page with folded corner" silhouette used in document lists, the
 * Compliance Insights table, and attached-PDF references. Per
 * `dashboard-design-system.md` §Document / file icon: filled, single colour
 * — a muted red roughly `#C44A3A`. This is the ONE exception in the icon
 * library where a coloured glyph is allowed (every other icon inherits the
 * surrounding text colour).
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface DocumentIconProps extends React.SVGAttributes<SVGSVGElement> {
  /** Pixel size. Default 20, matches the spec's 16-24 range. */
  size?: 16 | 18 | 20 | 24 | 32;
  /**
   * Optional small label rendered on top of the icon (e.g., "PDF", "CSV").
   * Renders as inline white text on the body of the page silhouette.
   */
  label?: string;
  /** Override the muted-red fill colour if needed. Default `#C44A3A`. */
  color?: string;
}

export function DocumentIcon({
  size = 20,
  label,
  color = "#C44A3A",
  className,
  ...rest
}: DocumentIconProps) {
  return (
    <svg
      role="img"
      aria-label={label ? `${label} document` : "Document"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("inline-block shrink-0", className)}
      {...rest}
    >
      {/* Page silhouette with folded corner */}
      <path
        d="M5 2.75A1.75 1.75 0 0 1 6.75 1h7.69c.46 0 .91.18 1.24.51l4.31 4.31c.33.33.51.78.51 1.24V21.25A1.75 1.75 0 0 1 18.75 23H6.75A1.75 1.75 0 0 1 5 21.25V2.75Z"
        fill={color}
      />
      {/* Folded corner highlight */}
      <path
        d="M14 1.5v4.25c0 .69.56 1.25 1.25 1.25h4.25L14 1.5Z"
        fill={color}
        fillOpacity="0.55"
      />
      {/* Optional label text (PDF / CSV / etc.) */}
      {label ? (
        <text
          x="12"
          y="17"
          textAnchor="middle"
          fontFamily="'Inter Tight', system-ui, sans-serif"
          fontSize="6"
          fontWeight="700"
          fill="#FFFFFF"
          letterSpacing="0.04em"
        >
          {label.slice(0, 3).toUpperCase()}
        </text>
      ) : null}
    </svg>
  );
}
