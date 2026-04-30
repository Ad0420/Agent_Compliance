# Design System — practical guide

Quick reference for "what do I reach for when". For the *why*, see `LOOK.md` at the package root.

## Colors

Tokens live in two places that must stay in sync:

- `lib/design/tokens.ts` — TS export, used inside JS/TS code (charts, dynamic styles).
- `app/globals.css` — CSS custom properties, used by Tailwind utilities and inline `style` props.

In components, prefer the CSS custom property: `style={{ color: "var(--teal)" }}` or use the Tailwind arbitrary value `text-[var(--teal)]`. A single token change in `globals.css` then ripples everywhere.

When you genuinely need the hex (SVG inline fills, chart-library config), import from `tokens.ts`:

```tsx
import { colors } from "@/lib/design/tokens";
<svg fill={colors.teal} />
```

## Surfaces

| Need a... | Use |
|---|---|
| Page background | `bg-[var(--paper)]` (default on `<body>`) |
| Hero band / muted section | `bg-[var(--paper-2)]` |
| Standard card | `<Card>` (default `elevation="md"`) |
| Card flagged for risk | `<Card tone="amber">` or `tone="crimson"` |
| Modal / dropdown / floating thing | `<Card elevation="lg">` |
| Inline tile inside a card | `<Card elevation="flat">` |

## Type

| Need... | Class |
|---|---|
| Hero (one per page max) | `font-serif text-5xl font-semibold`, letter-spacing -0.02em |
| Page H1 | `font-serif text-3xl font-semibold`, -0.015em |
| Section H2 | `font-serif text-xl font-semibold` |
| Card title | `<CardTitle>` (handles this) |
| Body | default Inter via `<body>` |
| Captions / labels | `font-sans text-xs text-[var(--ink-3)]` |
| Small caps caption | `font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]` |
| ID / license / case-id | `font-mono text-xs text-[var(--ink-2)]` |

## State indicators

| Communicate... | Use |
|---|---|
| Risk tier on a case (clinical judgment) | `<RiskPill tier="..." />` |
| Status of a long-running process | `<StatusDot status="..." />` |
| Generic chip / count / label | `<Badge variant="..." />` |
| Step in a multi-step pipeline | `<SessionStep state="..." />` |

Don't mix these. A `Badge` for risk loses the clinical color contract. A `RiskPill` for status conflates a static rating with a live state.

## Buttons

Default to `<Button variant="primary">`. Reach for `secondary` when there are two equally weighted paths. `ghost` for cancellations and skips. `destructive` for irreversible actions. `escalate` is the signature CTA — use it when the action sends a patient up the urgency ladder (ER, virtual visit, nurse review).

Sizes:
- `sm` — inline within tables / queue rows
- `md` (default) — almost everywhere else
- `lg` — hero CTAs, primary action in a modal

## Forms

`Input` and `Textarea` share the inset-shadow / teal-focus-ring treatment. Always pair with a `<label>` (the look book uses a `Field` helper that wraps the label + input vertically — copy that pattern).

For form errors, use a crimson-tinted helper text below the field:

```tsx
<span className="font-sans text-xs text-[var(--crimson)]">
  License number must be 10 characters.
</span>
```

## Icons

There is one custom brand glyph in `components/brand/Glyph.tsx` (the stethoscope-pulse mark). For everyday UI icons, draw small custom SVGs (the look book includes inline check / exclamation icons inside `SessionStep`). Do **not** import lucide (that's Vera's vocabulary) and avoid leaning on Phosphor stethoscope icons — the brand mark is the system's stethoscope.

## Writing copy

See the "Microcopy" section of `LOOK.md`. Short rule: every line should sound like a triage nurse wrote it for another triage nurse. If a sentence could appear unchanged on a regulator's slide deck, rewrite it.

## Adding a new primitive

1. Add the file under `components/ui/` (or `components/brand/` if it's identity-related).
2. Comment the file with a paragraph describing its role and contract.
3. Add a section to `app/page.tsx` (the look book) demonstrating every variant and state.
4. If the primitive introduces a new design token, add it to `lib/design/tokens.ts` AND `app/globals.css` in the same commit.
5. Update `LOOK.md`'s component vocabulary section if the new primitive is significant.

## Don't

- Don't use `bg-white` literally — use `bg-[var(--surface)]`.
- Don't hard-code shadow values. The `<Card elevation="...">` API exists for a reason.
- Don't create new risk-tier colors. Four tiers is the contract.
- Don't reach for `dark:` Tailwind variants. TriageGuard is light-only by design.
- Don't reach for emerald (Vera) or cobalt (ScribeMD). Teal-and-crimson is the contract.
