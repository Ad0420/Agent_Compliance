# Design System — practical guide

Quick reference for "what do I reach for when". For the *why* behind these choices, see `LOOK.md` at the package root.

## Colors

Tokens live in two places that must stay in sync:

- `lib/design/tokens.ts` — TypeScript export, used inside JS/TS code (charts, dynamic styles).
- `app/globals.css` — CSS custom properties, used by Tailwind utilities and inline `style` props.

In components, prefer the CSS custom property: `style={{ color: "var(--cobalt)" }}` or use the Tailwind arbitrary value `text-[var(--cobalt)]`. This keeps the component declarative and means a single token change in `globals.css` ripples everywhere.

When you genuinely need the hex (e.g. SVG inline fills, a chart library config), import from `tokens.ts`:

```tsx
import { colors } from "@/lib/design/tokens";
<svg fill={colors.cobalt} />
```

## Surfaces

| Need a... | Use |
|---|---|
| Page background | `bg-[var(--paper)]` (it's the default on `<body>`) |
| Hero band / muted section | `bg-[var(--paper-2)]` |
| Standard card | `<Card>` (default `elevation="md"`) |
| Card flagged for risk | `<Card tone="amber">` or `tone="coral"` |
| Modal / dropdown / hover-floating thing | `<Card elevation="lg">` |
| Inline tile inside a card | `<Card elevation="flat">` |

## Type

| Need... | Class |
|---|---|
| Hero (one per page max) | `font-serif text-5xl font-semibold`, letter-spacing -0.025em |
| Page H1 | `font-serif text-3xl font-semibold`, -0.015em |
| Section H2 | `font-serif text-xl font-semibold` |
| Card title | `<CardTitle>` (handles this) |
| Body | default Inter via `<body>` |
| Captions / labels | `font-sans text-xs text-[var(--ink-3)]` |
| Small caps caption | `font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]` |
| ID / hash / NPI | `font-mono text-xs text-[var(--ink-2)]` |

## State indicators

| Communicate... | Use |
|---|---|
| Risk tier on a record (clinical judgment needed) | `<RiskPill tier="..." />` |
| Status of a long-running process | `<StatusDot status="..." />` |
| Generic chip / count / label | `<Badge variant="..." />` |
| Step in a multi-step pipeline | `<EncounterStep state="..." />` |

Don't mix these. A `Badge` for risk loses the clinical color contract. A `RiskPill` for status conflates a static rating with a live state. They're separate primitives on purpose.

## Buttons

Default to `<Button variant="primary">`. Reach for `secondary` only when there are two equally weighted paths (which is rare in clinical UI — there's almost always one "next thing" the doctor should do). `ghost` for cancellations and skips. `destructive` for irreversible actions only.

Sizes:
- `sm` — inline within tables / list rows
- `md` (default) — almost everywhere else
- `lg` — hero CTAs, primary action in a modal

## Forms

`Input` and `Textarea` share the inset-shadow / cobalt-focus-ring treatment. Always pair with a `<label>` (the look book uses a `Field` helper that wraps the label + input vertically — copy that pattern).

For form errors, use a coral-tinted helper text below the field:

```tsx
<span className="font-sans text-xs text-[var(--coral)]">
  Provider NPI must be 10 digits.
</span>
```

There's no separate `<ErrorText>` primitive yet — add one in `components/ui/` if you find yourself writing this in three places.

## Icons

Phosphor (`@phosphor-icons/react`) is the chosen library — different vocabulary from Vera's lucide. Prefer the `regular` weight at 16–20px inside buttons, `bold` weight when standalone.

If you need an icon that doesn't exist in Phosphor, write a small custom SVG in `components/brand/` (like `Glyph.tsx`). Don't reach for lucide — that's Vera's library.

## Writing copy

See the "Microcopy" section of `LOOK.md`. Short rule: every line should sound like it was written by a clinician for a clinician. If a sentence could appear unchanged on a regulator's slide deck, rewrite it.

## Adding a new primitive

1. Add the file under `components/ui/` (or `components/brand/` if it's identity-related).
2. Comment the file with a paragraph describing its role and contract.
3. Add a section to `app/page.tsx` (the look book) demonstrating every variant and state.
4. If the primitive introduces a new design token (color, radius, shadow), add it to `lib/design/tokens.ts` AND `app/globals.css` in the same commit.
5. Update `LOOK.md`'s component vocabulary section if the new primitive is significant enough to warrant guidance.

## Don't

- Don't use `bg-white` literally — use `bg-[var(--surface)]`. If we ever decide raised cards should have a faint warm tint, one token change updates the whole app.
- Don't hard-code shadow values. The `<Card elevation="...">` API exists for a reason.
- Don't create new risk-tier colors. Four tiers is the contract.
- Don't reach for `dark:` Tailwind variants. ScribeMD is light-only by design — there is no dark mode in v0.1 and we won't be adding one without a brand discussion.
