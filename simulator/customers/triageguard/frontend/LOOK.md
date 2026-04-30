# TriageGuard — Look & Feel

This document is the source of truth for TriageGuard's visual identity. Read it before composing any new page; the contrast brief here is what makes TriageGuard legible as a *third distinct product* — alongside Vera and ScribeMD — on a sales screenshare.

## Why this exists

Vera, ScribeMD, and TriageGuard ship in the same repo. Vera is the underlying audit substrate; ScribeMD is the ambient-scribe customer demo; TriageGuard is the AI-triage customer demo. On a screenshare, the founder will switch between all three in seconds. **A viewer must be able to tell them apart in under two seconds, by vibe alone, without reading a single word.**

If you find yourself reaching for emerald or dark slate — stop, that's Vera. Reaching for cobalt or cream-paper-with-a-soft-shadow tile — stop, that's ScribeMD. TriageGuard speaks a third language.

## Vera looks like X — ScribeMD looks like Y — TriageGuard looks like Z

| Dimension | Vera | ScribeMD | **TriageGuard** |
|---|---|---|---|
| **Mood** | Regulatory, cryptographic, infrastructure | Clinical, calm, written-on-paper | **Decisive, on-call, queue-driven** |
| **Background** | Dark slate (`oklch(0.11 0.018 258)`) | Warm cream (`#FAF7F2`) | **Cool ivory (`#FBF8F1`)** — same paper family as ScribeMD but greyer |
| **Primary accent** | Emerald-400 + teal-300 gradient | Cobalt blue (`#2E5BD8`) | **Deep teal (`#0F766E`)** — surgical, not Vera's emerald glow |
| **Risk / warning** | Amber on dark slate | Coral / amber on cream | **Crimson (`#B91C1C`)** for *escalation* — louder than ScribeMD's coral because escalation is the actual product event |
| **Surface** | Hairline-bordered cards, no shadow | Soft-shadowed `rounded-2xl` tiles | **Hairline + soft shadow `rounded-xl` "case file" cards** |
| **Display type** | Geist Sans, tight tracking, bold | Source Serif 4, semibold, -0.025em | **DM Serif Display, regular, -0.02em** — sharper / more editorial |
| **UI type** | Geist Sans throughout | Inter throughout | **Inter throughout** (body face is shared with ScribeMD; the differentiator is the display + accents, not the body) |
| **Iconography** | Lucide (shield, lock, check) | Custom waveform glyph + Phosphor | **Custom stethoscope-pulse glyph** (no third-party icon library) |
| **Wordmark** | ShieldCheck shield + "vera" sans | Waveform glyph + "ScribeMD" serif | **Stethoscope-pulse + DM Serif "TriageGuard"** with teal "Guard" suffix |
| **Pill style** | `tracking-widest uppercase` regulator pills | Sentence-case soft-tinted chips | **Sentence-case pill, optional leading dot, thin inset rule** |
| **Microcopy tone** | "Every action your AI takes. Logged, chained, verified." | "Ambient AI scribe for the modern hospital." | **Triage-nurse imperative**: "Confirm AI level", "Escalate to ER", "No escalation — patient routed to self-care" |
| **Audience** | DPOs, compliance officers, regulators | Clinicians, hospital IT, billing | **On-call nurses, telehealth ops, queue managers** |
| **Decoration** | Faint dot-grid + emerald radial glow | Soft paper grain, no glow | **Faint hairline cross-rule grid** (case-file ruling) |

Side-by-side screenshots of all three products should produce three different vocabulary lists. That's the bar.

## Why teal (and not the *other* greens)

Teal is in the green family but is materially different from Vera's emerald. Vera's emerald is bright, glowing, radial — it reads as "system online, hash chain green-light". TriageGuard's teal `#0F766E` is darker, more desaturated, and sits next to the ink rather than radiating off it — it reads as a *surgical* color, the green of operating-room scrubs and Mayo-clinic letterhead. Place them next to each other and the difference is instant.

Crucially, TriageGuard never uses gradient teal-to-emerald or any radial glow. The teal is a flat solid every place it appears.

## Palette

### Surfaces

| Token | Hex | Use |
|---|---|---|
| `paper` | `#FBF8F1` | Page background. The brand surface. |
| `paper-2` | `#F4EFE4` | Muted band, hero card, sidebar. |
| `paper-3` | `#E8E1D1` | Divider tint. |
| `surface` | `#FFFFFF` | Raised cards. |
| `hairline` | `#E2DCCD` | The only border color. |

### Ink

| Token | Hex | Use |
|---|---|---|
| `ink` | `#0E1A1A` | Primary body text. AAA on paper. |
| `ink-2` | `#2E3A3A` | Secondary body. |
| `ink-3` | `#5C6868` | Captions, metadata. |
| `ink-4` | `#8E9897` | Disabled / placeholders. |

The ink palette is intentionally cool (slight blue-green undertone), where ScribeMD's ink (`#1B1A17`) is warm. Stack a paragraph of TriageGuard ink next to a paragraph of ScribeMD ink and you can feel the temperature difference.

### Teal — the primary

| Token | Hex | Use |
|---|---|---|
| `teal` | `#0F766E` | Buttons, focus rings, links, active rails. |
| `teal-deep` | `#0B5650` | Pressed / hover. |
| `teal-soft` | `#CDE8E4` | Pill backgrounds, avatars. |
| `teal-ink` | `#042F2E` | Text on `teal-soft`. |

### Crimson — urgent escalation

| Token | Hex | Use |
|---|---|---|
| `crimson` | `#B91C1C` | Critical risk tier, "Escalate to ER" CTA, blocked rails. |
| `crimson-soft` | `#FBE0E0` | Critical pill background. |
| `crimson-deep` | `#7F1D1D` | Pressed escalate / destructive button. |

### Risk-tier neutrals

| Token | Hex | Use |
|---|---|---|
| `moss` | `#2F6A3D` | Low risk text + dot. **NOT emerald.** |
| `moss-soft` | `#DCEAD8` | Low risk pill background. |
| `taupe` | `#6E4E2E` | Medium risk — warm neutral, intentionally unsaturated. |
| `taupe-soft` | `#EFE3D2` | Medium pill background. |
| `amber` | `#92400E` | High risk text + dot. |
| `amber-soft` | `#FCE7C5` | High pill background. |

The four risk tiers are calibrated so the system sits calm at rest (low/medium look almost neutral), and crimson/critical pulls the eye unambiguously when it appears. Critical is the only filled tier — that's the surface alarm.

## Accessibility

All text/background combinations meet WCAG AA, and primary body type clears AAA. Ratios computed against the linearized sRGB luminance formula in WCAG 2.1.

| Foreground | Background | Ratio | Standard |
|---|---|---|---|
| `ink` (#0E1A1A) | `paper` (#FBF8F1) | **16.76 : 1** | AAA (≥7) |
| `ink-2` (#2E3A3A) | `paper` (#FBF8F1) | **11.11 : 1** | AAA |
| `ink-3` (#5C6868) | `paper` (#FBF8F1) | **5.45 : 1** | AA |
| `teal` (#0F766E) | `paper` (#FBF8F1) | **5.16 : 1** | AA |
| `teal` (#0F766E) | `surface` (#FFFFFF) | **5.47 : 1** | AA |
| White | `teal` (#0F766E) | **5.47 : 1** | AA — primary button |
| `teal-ink` (#042F2E) | `teal-soft` (#CDE8E4) | **11.20 : 1** | AAA |
| `crimson` (#B91C1C) | `paper` (#FBF8F1) | **6.10 : 1** | AA |
| White | `crimson` (#B91C1C) | **6.47 : 1** | AA — escalate button |
| `crimson` (#B91C1C) | `crimson-soft` (#FBE0E0) | **5.19 : 1** | AA — critical pill |
| `amber` (#92400E) | `amber-soft` (#FCE7C5) | **5.87 : 1** | AA |
| `moss` (#2F6A3D) | `moss-soft` (#DCEAD8) | **5.17 : 1** | AA |
| `taupe` (#6E4E2E) | `taupe-soft` (#EFE3D2) | **5.07 : 1** | AA |

Brief: **primary text on background ≥ 7:1 ✓** (16.76:1), **accents on background ≥ 4.5:1 ✓** (teal 5.16:1, crimson 6.10:1).

Other a11y rules:

- Every interactive element has a visible focus ring (`outline: 2px solid var(--teal)` plus an 18% halo).
- The `:focus-visible` selector avoids showing the ring on mouse clicks.
- The pulse animation on `StatusDot` (running) and `SessionStep` (active) is *decoration only* — color and label always communicate state independently. The `.triage-pulse` class is suppressed under `@media (prefers-reduced-motion: reduce)`.
- Risk pills carry `role="status"` and `aria-label="Risk: <tier>"` so screen readers announce them.
- The avatar bubble uses `aria-hidden` because the user's name is read literally next to it.

## Typography

- **Display + wordmark — DM Serif Display** at regular (400). High-contrast modern serif; sharper and more editorial than ScribeMD's Source Serif 4 and entirely different from Vera's Geist Sans. Negative tracking (-0.02em hero, -0.015em H1) keeps it from feeling airy.
- **UI body — Inter** at 400/500/600. Standard, neutral, clinical. Body face is shared with ScribeMD on purpose — the face is not the differentiator, the display + palette are.
- **Mono — JetBrains Mono** for record IDs (case IDs, license numbers, decision IDs).

All three are loaded via `next/font/google` in `app/layout.tsx` so they ship self-hosted with the app — no FOUT, no third-party network call at runtime.

## Component vocabulary

### Cards (workhorse surface)

`hairline border + soft shadow` over a near-white tile floating on ivory paper. `rounded-xl` (1rem) corners — tighter than ScribeMD's `rounded-2xl`. The pairing of border and shadow is deliberate: it reads as a structured worksheet, not a floaty marketing card.

When to add a `tone` ring: when the card surfaces a clinical state (`amber` for review needed, `crimson` for held / escalated, `moss` for committed, `teal` for active focus). Plain neutral cards everywhere else.

### Buttons

Pill `rounded-xl` (1rem) on default, `rounded-lg` on small. Teal focus ring with 22% alpha for the halo. `active:translate-y-px` on primary and escalate gives a subtle "press" without bouncing.

Variant logic:
- **primary** — the next thing the nurse should do ("Open case", "Confirm AI level")
- **secondary** — the alternate path ("Skip for now", "Hold for second opinion")
- **ghost** — non-committal, low-emphasis ("Cancel", "Skip")
- **destructive** — irreversible / hard rejection ("Reject decision")
- **escalate** — the signature CTA, filled crimson with extra weight ("Escalate to ER", "Escalate to virtual visit"). The single loudest event the product makes.

### Risk pills

The most clinically meaningful primitive. Always prefer a `RiskPill` over a generic `Badge` when the message is "this needs your judgment". The four-tier mapping (moss / taupe / amber / crimson-fill) is the contract — do not invent fifth or sixth tiers.

### Status dots

For *processes*, not records. `running` pulses (teal) — the heartbeat-tempo `triage-pulse` keyframe (1.6s, ease-in-out). `waiting` is amber. `committed` is moss. `error` is crimson.

### SessionStep

The Wave 2 view-layer agent will stack these into a vertical pipeline showing what the AI did and what the nurse needs to decide. States are in narrative order: idle → active → done, or active → blocked when the system flags something for human review (red-flag terms detected, AI level overridden, escalation pending).

## Microcopy

- Speak as if you're talking to a triage nurse working a queue: short, declarative, decision-oriented.
- Say "Open case", not "View case details". Say "Escalate to ER", not "Recommend emergency department referral".
- Lead with the verb. No marketing adjectives.
- Never use compliance / regulatory jargon. TriageGuard does not say "audit trail" or "EU AI Act" or "hash chain" — Vera does. TriageGuard says "Decision recorded · case closed".
- If you must reference an ID, render it in mono and prefix with the entity (`case_`, `pt_`, `dec_`).
- Avoid emoji.

### Reference microcopy bank (Wave 2 will use these)

1. Awaiting your triage decision
2. Confirm AI level
3. Escalate to ER
4. Escalate to virtual visit
5. No escalation — patient routed to self-care
6. Red-flag terms detected:
7. Approve and release to patient
8. Hold for nurse review
9. Triage queue · {n} cases waiting
10. AI recommendation overridden
11. Decision recorded · case closed
12. Patient symptoms · Last reported

## What you must NOT do

- Don't introduce emerald, teal-300, teal-400, or any radial gradient — those are Vera's vocabulary.
- Don't introduce cobalt, indigo, or `#2E5BD8` anywhere — that's ScribeMD.
- Don't use a pure-white page background — the page must read as cool ivory.
- Don't use Geist Sans or Source Serif 4. Inter for UI, DM Serif Display for display.
- Don't use `tracking-widest uppercase` pill chips — that's Vera's regulator look.
- Don't use shield, lock, key, gavel, scale-of-justice, or any compliance icon vocabulary.
- Don't reach for `rounded-2xl` everywhere — TriageGuard cards are tighter (`rounded-xl`).
- Don't reference Vera, hash chains, KMS, immutability, or compliance in any UI copy. The audit layer is invisible to the triage nurse.

## File map

| Path | Purpose |
|---|---|
| `app/globals.css` | CSS custom properties, Tailwind 4 `@theme inline` mapping, the pulse keyframe, the case-grid decoration |
| `app/layout.tsx` | next/font loading for Inter, DM Serif Display, JetBrains Mono |
| `app/page.tsx` | The look book — every primitive demonstrated |
| `lib/design/tokens.ts` | TS-side token export (mirrors the CSS custom properties) |
| `lib/design/README.md` | Practical "when do I use what" guide |
| `lib/utils.ts` | `cn()` for class merging |
| `components/brand/Glyph.tsx` | The stethoscope-pulse glyph |
| `components/brand/Wordmark.tsx` | Glyph + DM Serif lockup |
| `components/ui/*.tsx` | The nine primitives |
| `public/favicon.svg` | 32px brand icon |
| `public/logo.svg` | Full wordmark for external use (email signatures, splash) |

## Glyph rationale

The mark is a stylized **stethoscope-pulse hybrid** — two earpiece dots at the top connected by a thin curving tube (the stethoscope arc), resolving into a horizontal three-segment pulse line at the bottom (the ECG trace). Sat inside a soft squircle (`rx=8`, slightly tighter than ScribeMD's `rx=9`) so it tiles cleanly as an app icon and reads as a UI primitive rather than a logo.

Why a stethoscope-pulse hybrid? TriageGuard's value prop is *AI listens, nurse decides, patient routed*. The stethoscope is the universal "clinical listening" symbol; the pulse line is the universal "decision under time pressure" symbol. Together they read as "ambient listening that becomes a triage decision". Tested at 24/32/40/64px; all sizes hold up.

The wordmark renders "Triage" in `ink` and "Guard" in `teal` with tighter letter-spacing — the suffix reads as a clinical guardrail rather than a product suffix.

## Versioning

This is **v0.1**. The look book at `/` is the canonical reference. If you change a primitive, update the look book in the same commit so the documentation never drifts from the implementation.
