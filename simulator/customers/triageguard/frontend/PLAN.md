# TriageGuard frontend — Wave 1 plan (4B)

Design system + brand + look-book brief. Bar: side-by-side with Vera and ScribeMD, a viewer reaches for **three different vocabularies**.

## 1. Three-way contrast

| Dimension | Vera | ScribeMD | **TriageGuard** |
|---|---|---|---|
| Mood | Regulatory | Calm-paper | **Decisive on-call** |
| Background | Dark slate | Cream `#FAF7F2` | **Cool ivory `#FBF8F1`** |
| Primary accent | Emerald | Cobalt | **Deep teal `#0F766E`** |
| Risk / warning | Amber on slate | Coral on cream | **Crimson `#B91C1C`** for escalation |
| Surface | Hairline cards | Soft-shadow `2xl` tiles | **Hairline + soft shadow `rounded-xl` "case file"** |
| Display type | Geist Sans bold | Source Serif 4 | **DM Serif Display** |
| UI type | Geist Sans | Inter | **Inter** (body shared, accents differ) |
| Iconography | Lucide | Phosphor + waveform | **Custom stethoscope-pulse glyph** |
| Wordmark | ShieldCheck + sans | Waveform + serif | **Stethoscope-pulse + DM Serif "TriageGuard"** (teal "Guard" suffix) |
| Pill style | uppercase tracked | Sentence-case soft chip | **Sentence-case + leading dot + thin rule** |
| Microcopy | Compliance | Doctor-shorthand | **Triage-nurse imperative** |
| Audience | DPOs | Clinicians | **On-call nurses, telehealth ops** |
| Decoration | Dot grid + emerald glow | Paper grain | **Hairline cross-rule grid** (case-file ruling) |

Teal reads clinical/surgical — not Vera's emerald glow. Crimson is louder than ScribeMD's coral because escalation *is* the product event. DM Serif Display is sharper than Source Serif 4.

## 2. Final palette (locks `tokens.ts`)

- Surfaces: `paper #FBF8F1`, `paper-2 #F4EFE4`, `paper-3 #E8E1D1`, `surface #FFFFFF`, `hairline #E2DCCD`.
- Ink: `ink #0E1A1A` (cool — distinct from ScribeMD's warm `#1B1A17`), `ink-2 #2E3A3A`, `ink-3 #5C6868`, `ink-4 #8E9897`.
- Teal (primary): `teal #0F766E`, `teal-deep #0B5650`, `teal-soft #CDE8E4`, `teal-ink #042F2E`.
- Crimson (urgent): `crimson #B91C1C`, `crimson-soft #FBE0E0`, `crimson-deep #7F1D1D`.
- Risk tiers: `low` moss `#2F6A3D`/`#DCEAD8`; `medium` taupe `#6E4E2E`/`#EFE3D2`; `high` amber `#92400E`/`#FCE7C5`; `critical` white-on-crimson (only filled tier — the alarm).

## 3. Accessibility (computed, WCAG 2.1 sRGB)

| FG | BG | Ratio | Std |
|---|---|---|---|
| ink | paper | 16.76 | AAA body |
| ink-2 | paper | 11.11 | AAA |
| ink-3 | paper | 5.45 | AA |
| teal | paper | 5.16 | AA |
| teal | surface | 5.47 | AA |
| white | teal | 5.47 | AA primary button |
| teal-ink | teal-soft | 11.20 | AAA |
| crimson | paper | 6.10 | AA |
| white | crimson | 6.47 | AA escalate button |
| crimson | crimson-soft | 5.19 | AA critical pill |
| amber | amber-soft | 5.87 | AA |
| moss | moss-soft | 5.17 | AA |
| taupe | taupe-soft | 5.07 | AA |

Body AAA (≥7); accents AA (≥4.5). Focus ring `outline 2px solid var(--teal)` + 18% halo.

## 4. Component primitives (9)

- **Button** — `primary` (teal) · `secondary` (paper outline) · `ghost` · `destructive` (crimson) · `escalate` (crimson, signature CTA). Sm/md/lg, `rounded-xl`.
- **Card** — elevations `flat|sm|md|lg` (hairline + soft shadow). Tones `neutral|teal|amber|crimson|moss`. `rounded-xl` (tighter than ScribeMD's `2xl`).
- **Badge** — `neutral|teal|amber|crimson|moss|outline`.
- **RiskPill** — `low|medium|high|critical`; `critical` filled crimson. Compact mode.
- **StatusDot** — `running|waiting|committed|error`; `running` pulses on `triage-pulse` keyframe (1.6s). Color + label communicate state independently of motion.
- **Input / Textarea** — hairline border + inset shadow + teal focus ring 18% halo.
- **Topbar** — sticky; `signedInAs={ name, role, license }`; center slot for queue counter.
- **SessionStep** — vertical pipeline step, states `idle|active|done|blocked`, label + sublabel + optional `payload`.

## 5. Look-book layout

Hero → 01 Brand (wordmark, glyph, palette swatches) → 02 Typography → 03 Buttons (variants × sizes incl. `escalate` + disabled) → 04 Badges → 05 RiskPill → 06 StatusDots → 07 Cards (elevations + tones + realistic triage-case) → 08 Inputs → 09 Session pipeline (full state matrix).

## 6. Glyph spec

Stethoscope arc resolved into a pulse line. SVG primitives in a 32-viewBox: 1 `rect` (squircle, rx=9), 1 `path` (stethoscope arc — left earpiece down, U-bend, up to right earpiece), 2 `circle`s (earpiece dots), 1 `path` (pulse line: flat-peak-flat). Stroke 1.6. Tones `primary|ink|white`. Tested at 24/32/40/64px.

## 7. Microcopy bank (Wave 2 consumes)

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

Rule: imperative verb leading; no marketing adjectives; no audit/hash/policy jargon; no emoji.
