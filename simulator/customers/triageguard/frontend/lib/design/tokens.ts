/**
 * TriageGuard design tokens.
 *
 * Single source of truth for the brand palette, type scale, spacing, radii,
 * and shadow tokens used across the customer demo. The CSS layer in
 * `app/globals.css` mirrors these values as CSS custom properties so Tailwind
 * utilities resolve to the same numbers — keep the two in sync.
 *
 * Vera (the underlying audit substrate) is dark-slate + emerald.
 * ScribeMD (the first customer) is warm-cream + cobalt.
 * TriageGuard is deliberately a third vocabulary: cool ivory + deep teal,
 * with crimson reserved for the "escalate to ER" beat. See LOOK.md for the
 * three-way contrast brief.
 */

export const colors = {
  // Surface — warm ivory, slightly cooler than ScribeMD's cream so the two
  // products read as different even on swatch comparison.
  paper: "#FBF8F1",
  paper2: "#F4EFE4",
  paper3: "#E8E1D1",
  surface: "#FFFFFF",
  hairline: "#E2DCCD",

  // Ink — cool, slightly desaturated near-black. Distinct from ScribeMD's
  // warm "#1B1A17" — TriageGuard's ink has a faint blue-green undertone that
  // matches the teal accent.
  ink: "#0E1A1A",
  ink2: "#2E3A3A",
  ink3: "#5C6868",
  ink4: "#8E9897",

  // Teal — the primary clinical accent. Reads as surgical/Mayo, not Vera's
  // emerald glow. WCAG AA on paper and surface.
  teal: "#0F766E",
  tealDeep: "#0B5650", // pressed / hover
  tealSoft: "#CDE8E4", // pill / chip background
  tealInk: "#042F2E", // text on tealSoft (AAA, ratio ~11.2)

  // Crimson — urgent escalation. The signature TriageGuard beat: the system
  // is calm 95% of the time; when crimson appears, the nurse moves.
  crimson: "#B91C1C",
  crimsonSoft: "#FBE0E0",
  crimsonDeep: "#7F1D1D", // pressed destructive / escalate

  // Risk-tier neutrals — calmer, intentionally unsaturated relative to the
  // crimson critical tier so the alarm has somewhere to go.
  moss: "#2F6A3D", // low risk
  mossSoft: "#DCEAD8",
  taupe: "#6E4E2E", // medium risk — warm neutral, not an alarm color
  taupeSoft: "#EFE3D2",
  amber: "#92400E", // high risk
  amberSoft: "#FCE7C5",
} as const;

export const radii = {
  sm: "0.375rem",
  md: "0.5rem",
  lg: "0.75rem",
  // TriageGuard's signature: card corners are rounded-xl (1rem), tighter than
  // ScribeMD's rounded-2xl tiles. Reads as a structured worksheet, not a
  // floaty marketing card.
  xl: "1rem",
  "2xl": "1.25rem",
  "3xl": "1.5rem",
  full: "9999px",
} as const;

export const shadows = {
  // Tighter, lower-spread shadows than ScribeMD's. Pairs with a hairline
  // border on most surfaces — the "case file" stack.
  none: "none",
  sm: "0 1px 2px rgba(14, 26, 26, 0.05)",
  md: "0 1px 3px rgba(14, 26, 26, 0.06), 0 4px 16px rgba(14, 26, 26, 0.05)",
  lg: "0 2px 6px rgba(14, 26, 26, 0.07), 0 12px 32px rgba(14, 26, 26, 0.08)",
  inset: "inset 0 1px 2px rgba(14, 26, 26, 0.06)",
  // Teal focus ring — accessibility halo for keyboard users.
  ring: "0 0 0 4px rgba(15, 118, 110, 0.18)",
} as const;

export const spacing = {
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
  // Display / wordmark — DM Serif Display. Sharper, more editorial than
  // ScribeMD's Source Serif 4; entirely different vocabulary from Vera's
  // Geist Sans.
  serif: '"DM Serif Display", "Iowan Old Style", Georgia, serif',
  // Monospace for record IDs (case IDs, license numbers, decision IDs).
  mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
} as const;

// Risk tier mapping — used by RiskPill and any badge that surfaces a risk
// level. The contract is four tiers; do not invent a fifth.
//
//   low      -> moss   (calm, "this is fine")
//   medium   -> taupe  (warm neutral, "look at this")
//   high     -> amber  (hot, "you need to act")
//   critical -> crimson filled (alarm — the signature beat)
export const riskTiers = {
  low: {
    label: "Low",
    bg: colors.mossSoft,
    fg: colors.moss,
    ring: "rgba(47, 106, 61, 0.32)",
  },
  medium: {
    label: "Medium",
    bg: colors.taupeSoft,
    fg: colors.taupe,
    ring: "rgba(110, 78, 46, 0.32)",
  },
  high: {
    label: "High",
    bg: colors.amberSoft,
    fg: colors.amber,
    ring: "rgba(146, 64, 14, 0.32)",
  },
  critical: {
    label: "Critical",
    bg: colors.crimson,
    fg: "#FFFFFF",
    ring: "rgba(185, 28, 28, 0.55)",
  },
} as const;

export type RiskTier = keyof typeof riskTiers;
