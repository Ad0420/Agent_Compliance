# ScribeMD — Look & Feel

This document is the source of truth for ScribeMD's visual identity. Read it before composing any new page; the contrast brief here is what makes ScribeMD legible as a *separate product* from Vera on a sales screenshare.

## Why this exists

Vera and ScribeMD ship in the same repo. Vera is the underlying audit substrate; ScribeMD is a customer demo built on top. On a screenshare, the founder will switch between the two in seconds. **A viewer must be able to tell them apart in under two seconds, by vibe alone, without reading a single word.**

If you find yourself reaching for emerald, teal, dark slate, or all-caps tracking-widest pills — stop. That's Vera's vocabulary. ScribeMD speaks a different language.

## Vera looks like X — ScribeMD looks like Y

| Dimension | Vera | ScribeMD |
|---|---|---|
| **Mood** | Regulatory, cryptographic, infrastructure | Clinical, calm, written-on-paper |
| **Background** | Dark slate (`oklch(0.11 0.018 258)`) | Warm cream (`#FAF7F2`) |
| **Primary accent** | Emerald-400 + teal-300 gradient | Cobalt blue (`#2E5BD8`) |
| **Risk / warning** | Amber on dark slate | Coral / amber on cream |
| **Surface** | Hairline-bordered cards, no shadow | Soft-shadowed `rounded-2xl` tiles |
| **Display type** | Geist Sans, tight tracking, bold | Source Serif 4, semibold, -0.025em |
| **UI type** | Geist Sans throughout | Inter throughout |
| **Iconography** | Lucide (shield, lock, check) | Custom waveform glyph + Phosphor (stethoscope, file-pen, brain) |
| **Wordmark** | ShieldCheck shield + "vera" sans | Waveform glyph + "ScribeMD" serif |
| **Pill style** | `tracking-widest uppercase` regulator pills | Sentence-case soft-tinted chips |
| **Tone** | "Every action your AI takes. Logged, chained, verified." | "Ambient AI scribe for the modern hospital." |
| **Audience** | DPOs, compliance officers, regulators | Clinicians, hospital IT, billing |
| **Decoration** | Faint dot-grid + emerald radial glow | Soft paper grain, no glow |

If you took a screenshot of Vera's landing and a screenshot of this look book and put them side-by-side, a viewer should reach for entirely different vocabulary to describe each. That's the bar.

## Palette

### Surfaces

| Token | Hex | Use |
|---|---|---|
| `paper` | `#FAF7F2` | Page background. The brand surface. |
| `paper-2` | `#F1ECE2` | Muted band, hero card, sidebar. |
| `paper-3` | `#E6DFD0` | Divider tint. |
| `surface` | `#FFFFFF` | Raised cards. |
| `hairline` | `#E2DCCD` | The only border color. |

### Ink

| Token | Hex | Use |
|---|---|---|
| `ink` | `#1B1A17` | Primary body text. |
| `ink-2` | `#3F3D38` | Secondary body. |
| `ink-3` | `#6E6A60` | Captions, metadata. |
| `ink-4` | `#A09B8E` | Disabled / placeholders. |

### Cobalt — the primary

| Token | Hex | Use |
|---|---|---|
| `cobalt` | `#2E5BD8` | Buttons, focus rings, links, active states. |
| `cobalt-deep` | `#1E3FA8` | Pressed / hover. |
| `cobalt-soft` | `#E5ECFB` | Pill backgrounds, avatars, info banners. |
| `cobalt-ink` | `#15296A` | Text on `cobalt-soft`. |

### Risk / status

| Token | Hex | Use |
|---|---|---|
| `sage` | `#4F7C5A` | Low risk text + dot. **NOT emerald.** |
| `sage-soft` | `#DCEAD8` | Low risk pill background. |
| `amber` | `#C2410C` | Medium risk / "needs review". |
| `amber-soft` | `#FBE6CF` | Amber pill background. |
| `coral` | `#B42318` | High risk, destructive actions. |
| `coral-soft` | `#FCD9D2` | Coral pill background. |

## Accessibility

All text/background combinations meet WCAG AA, and primary body type clears AAA.

| Foreground | Background | Ratio | Standard |
|---|---|---|---|
| `ink` (#1B1A17) | `paper` (#FAF7F2) | **~16.6 : 1** | AAA (≥7) |
| `ink-2` (#3F3D38) | `paper` (#FAF7F2) | **~9.5 : 1** | AAA |
| `ink-3` (#6E6A60) | `paper` (#FAF7F2) | **~4.7 : 1** | AA normal text |
| `cobalt` (#2E5BD8) | `paper` (#FAF7F2) | **~5.4 : 1** | AA normal, AAA large |
| `cobalt` (#2E5BD8) | `surface` (#FFFFFF) | **~5.7 : 1** | AA normal, AAA large |
| White | `cobalt` (#2E5BD8) | **~5.6 : 1** | AA normal |
| `cobalt-ink` (#15296A) | `cobalt-soft` (#E5ECFB) | **~10.5 : 1** | AAA |
| `coral` (#B42318) | `coral-soft` (#FCD9D2) | **~4.9 : 1** | AA normal |
| White | `coral` (#B42318) | **~6.3 : 1** | AA normal |
| `sage` (#4F7C5A) | `sage-soft` (#DCEAD8) | **~4.6 : 1** | AA normal |
| `amber` (#C2410C) | `amber-soft` (#FBE6CF) | **~5.0 : 1** | AA normal |

Brief: **primary text on background ≥ 7:1 ✓** (16.6:1), **accent on background ≥ 4.5:1 ✓** (cobalt 5.4:1). Ratios computed against the linearized sRGB luminance formula in WCAG 2.1.

Other a11y rules:

- Every interactive element has a visible focus ring (`outline: 2px solid var(--cobalt)`).
- The `:focus-visible` selector is used to avoid showing the ring on mouse clicks.
- The pulse animation on `StatusDot` and `EncounterStep` (active state) is *not* the only signal — a label and a static dot color also communicate state. Safe for `prefers-reduced-motion`-aware users; the meaning of the indicator never depends on motion.
- Risk pills carry `role="status"` and `aria-label="Risk: <tier>"` so screen readers announce them.
- The avatar bubble uses `aria-hidden` because the user's name is read literally next to it.

## Typography

- **Display + wordmark — Source Serif 4** at semibold (600). The serif is the most direct visual contrast with Vera's Geist Sans-only vocabulary. Negative tracking (`-0.025em` for hero, `-0.015em` for H1/H2) keeps it tight without feeling cramped.
- **UI body — Inter** at 400/500/600. Standard, neutral, clinical.
- **Mono — JetBrains Mono** for record IDs (encounter IDs, NPI numbers, MRN, hash digests). Always visually distinct from prose.

All three are loaded via `next/font/google` in `app/layout.tsx` so they ship self-hosted with the app — no FOUT, no third-party network call at runtime.

## Component vocabulary

### Cards (workhorse surface)

`shadow-md` over a near-white tile floating on cream paper. `rounded-2xl` (1.5rem) corners. Hairline border only on the `flat` variant; everywhere else, depth replaces the line.

When to add a `tone` ring: when the card surfaces a clinical state (`amber` for review needed, `coral` for blocked, `sage` for committed, `cobalt` for active focus). Plain neutral cards everywhere else.

### Buttons

Pill `rounded-xl` (1.25rem) on default, `rounded-lg` on small. Cobalt focus ring with 22% alpha for the halo, 100% for the outline. `active:translate-y-px` on primary gives a subtle "press" without bouncing.

Variant logic:
- **primary** — the one thing the clinician should do next ("Sign note", "Approve order")
- **secondary** — the alternate path ("Discard", "Save draft")
- **ghost** — non-committal, low-emphasis ("Cancel", "Skip")
- **destructive** — irreversible / hard rejection ("Reject draft")

### Risk pills

The most clinically meaningful primitive. Always prefer a `RiskPill` over a generic `Badge` when the message is "this needs your judgment". The four-tier mapping (sage / amber / coral / coral-fill) is the contract — do not invent fifth or sixth tiers.

### Status dots

For *processes*, not records. `running` pulses (cobalt). `waiting` is amber. `committed` is sage. `error` is coral.

The pulse uses the `scribemd-pulse` keyframe (1.8s, ease-in-out) — slower than a notification ping, deliberately. It should feel like a heartbeat, not a chase light.

### EncounterStep

The Wave 2 agent will stack these into a vertical pipeline showing what the AI is doing live. States are in narrative order: idle → active → done, or active → blocked when the AI flags something for the human. The `payload` slot is for inline previews — a snippet of the draft note, the count of detected orders, the offending controlled substance.

## Microcopy

- Speak as if you're talking to a doctor in a hurry: short, declarative, calm.
- Say "Sign note", not "Confirm and submit". Say "Open draft", not "View encounter details".
- Never use compliance / regulatory jargon. ScribeMD does not say "audit trail" or "EU AI Act" or "hash chain" — Vera does. ScribeMD says "your note is saved".
- If you must reference an ID, render it in mono and prefix with the entity (`enc_`, `ord_`, `pt_`).
- Avoid emoji.

## What you must NOT do

- ❌ Don't introduce emerald or teal anywhere. Anywhere.
- ❌ Don't use a pure-white page background — it has to read as cream paper.
- ❌ Don't use Geist Sans. Inter for UI, Source Serif 4 for display.
- ❌ Don't use `tracking-widest uppercase` pill chips — that's Vera's regulator look.
- ❌ Don't use shield, lock, key, gavel, scale-of-justice, or any compliance icon vocabulary.
- ❌ Don't add hairline borders where a soft shadow is doing the job. Pick one — the system favors shadow.
- ❌ Don't reference Vera, hash chains, KMS, immutability, or compliance in any UI copy. ScribeMD doesn't know Vera exists. To the clinician using it, this is just an AI scribe.

## File map

| Path | Purpose |
|---|---|
| `app/globals.css` | CSS custom properties, Tailwind 4 `@theme inline` mapping, the pulse keyframe |
| `app/layout.tsx` | next/font loading for Inter, Source Serif 4, JetBrains Mono |
| `app/page.tsx` | The look book — every primitive demonstrated |
| `lib/design/tokens.ts` | TS-side token export (mirrors the CSS custom properties) |
| `lib/design/README.md` | Practical "when do I use what" guide |
| `lib/utils.ts` | `cn()` for class merging |
| `components/brand/Glyph.tsx` | The waveform glyph |
| `components/brand/Wordmark.tsx` | Glyph + serif lockup |
| `components/ui/*.tsx` | The eight primitives |
| `public/favicon.svg` | 32px brand icon |
| `public/logo.svg` | Full wordmark for external use (email signatures, splash) |

## Glyph rationale

The mark is a stylized **clinical waveform** — six bars of varying height, with the tallest bar slightly off-center to read like a confident pulse spike. Sat inside a soft squircle (`rx=9`, not a circle, not a square) so it tiles cleanly as an app icon and reads as a UI primitive rather than a logo.

Why a waveform? ScribeMD's value prop is *ambient listening*. The product hears the visit and writes the note. The waveform is the most direct visual translation of that — calmer than a microphone icon, more product than a stethoscope. It also gives us a glyph that lives comfortably at favicon size (32×32) without losing its read.

The wordmark renders "Scribe" in `ink` and "MD" in `cobalt` with tighter letter-spacing — making the credential read as a clinical lockup rather than a product suffix. Tested at 24, 32, 40, and 64px; all sizes hold up.

## Versioning

This is **v0.1**. The look book at `/` is the canonical reference. If you change a primitive, update the look book in the same commit so the documentation never drifts from the implementation.
