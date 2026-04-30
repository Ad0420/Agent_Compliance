/**
 * ScribeMD design tokens.
 *
 * Single source of truth for the brand palette, type scale, spacing, radii, and
 * shadow tokens used across the customer demo. The CSS layer in `app/globals.css`
 * mirrors these values as CSS custom properties so Tailwind utilities resolve to
 * the same numbers — keep the two in sync.
 *
 * Vera (the underlying audit substrate) is dark-slate + emerald. ScribeMD is
 * deliberately the visual opposite: cream paper, cobalt accent, warm amber for
 * risk. See LOOK.md for the full contrast brief.
 */

export const colors = {
  // Surface — warm cream, never pure white. Reads as a hospital letterhead.
  paper: "#FAF7F2",
  paper2: "#F1ECE2",
  paper3: "#E6DFD0",
  surface: "#FFFFFF", // raised cards on the cream surface
  hairline: "#E2DCCD",

  // Ink — desaturated near-black, warmer than Vera's slate.
  ink: "#1B1A17", // primary body text, AAA on paper
  ink2: "#3F3D38",
  ink3: "#6E6A60",
  ink4: "#A09B8E",

  // Cobalt — clinical, trustworthy primary. Distinct from Vera's emerald/teal.
  cobalt: "#2E5BD8",
  cobaltDeep: "#1E3FA8", // pressed / hover state
  cobaltSoft: "#E5ECFB", // pill / chip background
  cobaltInk: "#15296A", // text on cobaltSoft
  indigo: "#4338CA", // secondary lockup accent

  // Warm peach / amber — risk + attention. Replaces hairline-emerald accents.
  amber: "#C2410C", // risk text on amberSoft
  amberSoft: "#FBE6CF",
  amberPaper: "#FDF2E2",

  // Coral — high / critical risk. Warmer and more clinical than pure red.
  coral: "#B42318",
  coralSoft: "#FCD9D2",

  // Calm green — low risk only (NOT emerald-400/500/600 — those are Vera's).
  // This is a sage, washed clinical tone.
  sage: "#4F7C5A",
  sageSoft: "#DCEAD8",

  // Status / utility neutrals
  slateSoft: "#EFECE3",
  slateInk: "#56524A",
} as const;

export const radii = {
  sm: "0.5rem",
  md: "0.75rem",
  lg: "1rem",
  xl: "1.25rem",
  // ScribeMD's signature: card corners are rounded-2xl, much softer than Vera's
  // 0.5rem hairline cards.
  "2xl": "1.5rem",
  "3xl": "2rem",
  full: "9999px",
} as const;

export const shadows = {
  // Soft, layered shadows. Replaces Vera's hairline borders with depth.
  none: "none",
  sm: "0 1px 2px rgba(27, 26, 23, 0.04), 0 1px 1px rgba(27, 26, 23, 0.03)",
  md: "0 2px 6px rgba(27, 26, 23, 0.05), 0 8px 24px rgba(27, 26, 23, 0.06)",
  lg: "0 4px 12px rgba(27, 26, 23, 0.07), 0 18px 40px rgba(27, 26, 23, 0.10)",
  // Inset for input fields — lets them sit "into" the paper.
  inset: "inset 0 1px 2px rgba(27, 26, 23, 0.06)",
  // Cobalt focus ring — accessibility halo for keyboard users.
  ring: "0 0 0 4px rgba(46, 91, 216, 0.18)",
} as const;

export const spacing = {
  // 4px base scale, like Tailwind's default.
  xs: "0.25rem",
  sm: "0.5rem",
  md: "0.75rem",
  base: "1rem",
  lg: "1.5rem",
  xl: "2rem",
  "2xl": "3rem",
  "3xl": "4rem",
} as const;

export const typography = {
  // Body / UI — Inter (loaded via next/font in app/layout.tsx).
  sans: '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif',
  // Display / wordmark — Source Serif 4. Instantly distinguishes from Vera's Geist Sans.
  serif: '"Source Serif 4", "Source Serif Pro", "Iowan Old Style", Georgia, serif',
  // Monospace for record IDs, NPI numbers, etc.
  mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
} as const;

// Risk tier mapping — used by RiskPill and any badge that surfaces a risk level.
// low -> sage, medium -> amber, high -> coral, critical -> coral with stronger ink.
export const riskTiers = {
  low: {
    label: "Low",
    bg: colors.sageSoft,
    fg: colors.sage,
    ring: "rgba(79, 124, 90, 0.32)",
  },
  medium: {
    label: "Medium",
    bg: colors.amberSoft,
    fg: colors.amber,
    ring: "rgba(194, 65, 12, 0.32)",
  },
  high: {
    label: "High",
    bg: colors.coralSoft,
    fg: colors.coral,
    ring: "rgba(180, 35, 24, 0.32)",
  },
  critical: {
    label: "Critical",
    bg: colors.coral,
    fg: "#FFFFFF",
    ring: "rgba(180, 35, 24, 0.55)",
  },
} as const;

export type RiskTier = keyof typeof riskTiers;
