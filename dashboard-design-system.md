# Design System — Vera Dashboard

> **Scope:** This document is the visual design system and component
> library for Vera's **in-app dashboard** — the surface compliance
> officers and engineering leads at Vera's customers (Abridge, Suki,
> etc.) interact with daily.
>
> **Marketing design system:** see [landing-design.md](landing-design.md).
> The dashboard inherits its typography, color palette, and brand
> posture, but applies them at higher density with an operational
> component library.
>
> **Dashboard UX & wireframes:** see [dashboard-design.md](dashboard-design.md)
> for the four-page information architecture (Home, Customers,
> Compliance, Settings) and the screen wireframes. This document
> covers the visual tokens and components those wireframes are built
> from.

---

## The memorable thing

The dashboard is the boring, beautiful, calm work surface a compliance
officer opens for thirty seconds a day and closes. It should feel
the way **OpenAI's platform console** feels: warm, light, generous with
whitespace, confident enough to leave most of the screen empty. Not
the way **a typical SaaS dashboard** feels: dense, busy, gradient-laden,
notification-decorated, trying to justify the subscription on every
pixel.

Every visual decision below serves this posture. Charts, marketing
copy, gamified scores, gradient hero panels, and 3-column iconed-circle
feature grids are out. Tabular data, small-caps section headers,
single-color status dots, and lots of breathing room are in.

---

## Aesthetic direction

- **Direction:** Light, minimal, editorial-operational. The same
  warm-cream paper as the marketing surface, but applied to a dense
  work environment.
- **Reference shape:** OpenAI platform console (light theme), Linear's
  command palette aesthetic, Vercel's project dashboard, the
  contract-management product screenshots the user shared (Novera-class
  light theme). Not: Vercel's marketing dark mode, Datadog's
  high-density telemetry view, Salesforce Lightning, any product
  whose visual signature is "feature density."
- **Decoration level:** Restrained. The dashboard earns its weight
  through typography, whitespace, and tabular precision, not through
  illustration, decorative shape, or color. Allowed: subtle 1px
  borders, soft drop shadows on hover, status dots, severity badges,
  small filled icons in single colors. Disallowed: gradients,
  illustrations, glassmorphism, decorative blobs, animated loaders
  more elaborate than a spinner, coloured icon backgrounds (except
  product/integration logos in the integrations page, which are
  inherently colourful).
- **Mood:** Operational, calm, confident. The compliance officer feels
  competent using it, not entertained by it.

---

## Typography

Inherits from [landing-design.md](landing-design.md). Recap with
dashboard-specific scale:

- **Page titles:** Petrona 400 (regular weight, never bold). Use
  weight 400 even at the largest scale; the lightness is the point.
  Italic for emphasis fragments only.
- **Section headers (small caps):** Inter 12px, weight 600, tracking
  0.10em, uppercase, colour `--ink-2`. Used above every section block
  in the dashboard.
- **Body text:** Inter 400, line-height 1.5. Used for paragraphs,
  table cells, form inputs.
- **UI labels:** Inter 500 weight for navigation, button labels.
  Inter 600 for emphasis inside body.
- **Numeric data:** Inter with `font-feature-settings: "tnum"`
  (tabular-nums). Used in every numeric column, every count, every
  date. Without tnum, columns wobble.
- **Code (rare on dashboard):** JetBrains Mono 400, used only in
  technical-verification contexts (hashes, API keys, code samples).

### Dashboard type scale

| Token | Size / line-height | Family / weight | Where used |
|---|---|---|---|
| `--display` | 48-56px / 1.1 | Petrona 400 | Org name on Home, hero text in empty states |
| `--h1` | 28-32px / 1.2 | Petrona 400 | Page titles ("Customers", "Compliance", "Settings") |
| `--h2` | 20px / 1.3 | Petrona 400 | Section/subsection titles where a serif beat is wanted (rare) |
| `--label-lg` | 14px / 1.4 | Inter 600, tracking 0.08em, uppercase | Section headers above content blocks |
| `--label` | 12px / 1.4 | Inter 600, tracking 0.10em, uppercase | Smaller section headers, table column headers |
| `--body-lg` | 16px / 1.5 | Inter 400 | Card descriptions, modal body |
| `--body` | 14px / 1.5 | Inter 400 | Default body text, table cells |
| `--body-sm` | 13px / 1.5 | Inter 400 | Metadata, timestamps, secondary descriptions |
| `--micro` | 11px / 1.4 | Inter 500 | Pill labels, badge text, tooltip body |

Page titles use Petrona; everything else uses Inter. No mono on the
default dashboard surface (mono is reserved for the technical
verification appendix in audit PDFs and the in-app code editor).

---

## Color

Inherits the palette from [landing-design.md](landing-design.md), with
additional roles for dashboard-specific patterns (status indicators,
severity badges, code highlights, real-time collaboration cursors).

### Foundational tokens (shared with landing)

| Token | Hex / value | Use |
|---|---|---|
| `--paper` | `#FEFAF3` | Body background |
| `--paper-2` | `#F5EFE3` | Card surface, dropdown menu surface, hover background |
| `--paper-3` | `#EDE5D2` | Table header row, muted chip background, deep hover |
| `--ink` | `#1F1610` | Body text, page titles, primary button background |
| `--ink-2` | `#57514D` | Secondary text, captions, small-caps headers |
| `--ink-3` | `rgba(31,22,16,0.45)` | Tertiary text, metadata, placeholder |
| `--ink-4` | `rgba(31,22,16,0.14)` | Borders, dividers, table row separators |

### Status & severity (used sparingly)

| Token | Hex | Companion bg | Use |
|---|---|---|---|
| `--status-ok` | `#3E5C3B` (oxidised olive) | `#DDE5D5` | Green status dot, compliant indicator, success state |
| `--status-warn` | `#9C6A1D` (warm amber) | `#F4E3C9` | Yellow status dot, warning state, medium severity badge |
| `--status-error` | `#7A2E1F` (oxidised brick) | `#F2D5CC` | Red status dot, expired BAA, high severity badge, error state |
| `--status-neutral` | `--ink-3` | — | Inactive, neutral, "no data yet" |

These are the **only** non-neutral colours allowed on the dashboard.
No emerald, no royal blue, no purple, no teal. Status colours are
desaturated and oxidised — they raise their voice without shouting.

### Collaboration & user identity

Avatar backgrounds use a fixed palette of muted hues (one per user,
deterministically hashed from user ID):

| Token | Hex | Notes |
|---|---|---|
| `--avatar-blue` | `#4A7BB7` | Cool, slightly desaturated |
| `--avatar-orange` | `#C97C3A` | Warm |
| `--avatar-olive` | `#6B7A47` | Muted green |
| `--avatar-rust` | `#A85D3E` | Warmer red |
| `--avatar-slate` | `#5C6A75` | Cool neutral |
| `--avatar-ink` | `#1F1610` | Used for the user's own avatar (always ink) |

Real-time collaboration cursors use the user's assigned avatar colour
as the cursor stem and a small filled label tag bearing their first
name. See **Component Library → Collaboration cursor**.

### What's deliberately not in the palette

- No bright accent (no #007AFF blue, no #00D26A green, no purple)
- No gradient stops
- No tinted whites (background is always warm cream, never bluish white)
- No dark mode in v1 (the dashboard is always served on warm paper)

---

## Spacing

The base unit is 8px. The dashboard is **denser than the marketing
surface** — sections sit at 32-48px vertical gaps, not 96-160px.

### Spacing scale

| Token | Value | Common use |
|---|---|---|
| `--space-2xs` | 4px | Tight icon-to-label gap, small badge padding |
| `--space-xs` | 8px | Icon-to-label, chip internal padding |
| `--space-sm` | 12px | Compact form field internal padding, list item gap |
| `--space-md` | 16px | Default card internal padding, table cell vertical padding |
| `--space-lg` | 20px | Table cell horizontal padding, button vertical padding |
| `--space-xl` | 24px | Section block internal padding, modal content padding |
| `--space-2xl` | 32px | Gap between major sections within a page |
| `--space-3xl` | 48px | Gap between page header and first section |
| `--space-4xl` | 64px | Page outer margins on wide viewports |

### Layout containers

- **Sidebar width:** 240-260px (fixed). Single column. Always
  expanded on desktop (≥1024px). Collapsible to icon-only at 56px on
  narrower viewports (v2 — v1 is desktop-only).
- **Content max-width:** 1280px. Wider than the marketing 1200px
  because tables benefit from horizontal real estate.
- **Page outer padding:** 48px (top), 64px (sides on desktop),
  32px (bottom).
- **Section gap:** 32-48px between section blocks.

---

## Layout patterns

Three layout patterns the dashboard uses repeatedly. Every page
inherits one of them.

### Pattern A — Sidebar + content (default)

```
┌────────────┬──────────────────────────────────────────────────────┐
│            │                                                       │
│  sidebar   │     top bar (org, breadcrumb, right actions)         │
│  (240px)   │  ────────────────────────────────────────────────    │
│            │                                                       │
│  nav       │     page title                                       │
│  sections  │     ────                                              │
│            │     content sections                                  │
│            │                                                       │
│  user      │                                                       │
│  profile   │                                                       │
│            │                                                       │
└────────────┴──────────────────────────────────────────────────────┘
```

Used by: Home, Customers list, Compliance, Settings.

### Pattern B — Sidebar + content + right panel (split work surface)

```
┌────────────┬─────────────────────────────┬─────────────────────────┐
│            │                              │                         │
│  sidebar   │   content (document, chart)  │   right panel           │
│            │                              │   (AI chat / comments / │
│            │                              │   recommendations)       │
│            │                              │                         │
└────────────┴─────────────────────────────┴─────────────────────────┘
```

Used by: Customer detail with active review session, AI Insights
panel on Compliance, Decision detail (when expanded). Right panel
is 360-420px wide.

### Pattern C — Centered modal / dialog

```
┌────────────┬──────────────────────────────────────────────────────┐
│            │                                                       │
│  sidebar   │             ┌─────────────────────┐                  │
│  (dimmed)  │             │   modal content      │                  │
│            │             │   (max-width 560px)  │                  │
│            │             └─────────────────────┘                  │
│            │                                                       │
└────────────┴──────────────────────────────────────────────────────┘
```

Used for: Generate PDF, Renew BAA, Bulk import CSV, Match Review,
Decision detail (when small enough). Modal width 480-720px depending
on content density. Backdrop is `rgba(31,22,16,0.32)` over the rest
of the page.

---

## Component library

Every component used in the dashboard, with anatomy and tokens.

### Sidebar

The persistent left nav on every dashboard page. Three sections plus
two persistent chips (top and bottom).

**Anatomy:**

```
┌─────────────────────────────┐
│  ┌─────────────────────┐    │  ← Project switcher (top)
│  │ icon  Org name      │ ⇅ │     - Square icon with rounded corners
│  │       "Personal"    │    │     - Org name (Inter 500, 14px)
│  └─────────────────────┘    │     - Subtitle (Inter 400, 12px, ink-3)
│                              │     - Disclosure arrow (⇅)
│  Section label              │  ← Section header (small caps)
│  ▢ Item                     │     - 12px, weight 600, tracking 0.10em
│  ▢ Item                     │     - colour ink-3, padding 12px sides
│  ▢ Item (selected)          │
│                              │  ← Nav items
│  Section label              │     - 14px Inter 500
│  ▢ Item                     │     - 8px space between icon and label
│  ▢ Item                     │     - Selected: paper-2 background
│                              │     - Hover: paper-2/50 background
│                              │     - Icon: 16px filled, single colour
│  ───────                    │     - All-ink colour
│                              │
│  ┌─────────────────────┐    │  ← User profile chip (bottom)
│  │ 👤 Name             │ ⇅ │     - Avatar (32px circle)
│  │    email@x.com      │    │     - Name (Inter 500, 13px)
│  └─────────────────────┘    │     - Email (Inter 400, 11px, ink-3)
└─────────────────────────────┘
```

**Tokens:**
- Width: 240px desktop
- Background: `--paper`
- Right border: 1px `--ink-4`
- Top padding: 16px
- Bottom padding: 16px
- Section gap: 24px
- Item height: 36px
- Item padding (horizontal): 12px
- Item radius: 8px when selected/hovered
- Project switcher height: 64px (slightly taller — visual anchor)
- Project switcher bg: `--paper-2`, radius 12px, 1px `--ink-4` border
- User chip: same shape as project switcher

**States:**
- Default: ink-2 text, no background
- Hover: paper-2/50 background (subtle), ink text
- Selected: paper-2 background, ink text, no left-rail accent
  (the background change is the selection signal — no extra chrome)
- Disabled: ink-3 text, no hover state

### Top bar

Persistent across content pages. Holds breadcrumb on left and
contextual actions on right.

```
┌──────────────────────────────────────────────────────────────────┐
│  ✕   Contracts  ›  Master services            [actions →]        │
└──────────────────────────────────────────────────────────────────┘
```

**Anatomy:**
- Close icon (✕) on left edge — closes a deep view back to its
  parent list (e.g., Customer detail → Customers list)
- Breadcrumb: separator is `›` (single chevron, ink-3)
- Right side: contextual buttons (e.g., "Invite collaborator",
  "Start review session", "Generate audit PDF")
- Height: 56px
- Bottom border: 1px `--ink-4`
- Padding: 16px horizontal, 8px vertical
- Background: `--paper`

### Page header

The block immediately below the top bar that contains the page title
and primary actions.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│  Page Title                                  [primary action]    │
│                                                                   │
│  Optional subtitle / count line in ink-2                         │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

- Title: Petrona 400 at 28-32px (`--h1`)
- Subtitle: Inter 400 at 14px (`--body`), colour ink-2
- Primary action sits right-aligned, vertically centered with title
- Vertical padding: 24px top, 16px bottom
- No bottom border (the title is its own visual anchor; whitespace
  separates it from the content)

### Button

Three primary variants.

| Variant | Token role | Appearance |
|---|---|---|
| Primary | Critical action | Ink background, paper text, 10px radius, weight 500 |
| Secondary | Important but non-critical action | Paper-2 background, ink text, 1px ink-4 border, 10px radius |
| Ghost | Tertiary or in-line | No background, ink-2 text, hover: paper-2 background |

**Sizes:**
- Default: 36px height, 16px horizontal padding, 14px text
- Compact: 28px height, 12px horizontal padding, 13px text
- Large (CTAs in modals, hero): 44px height, 20px horizontal padding, 15px text

**States (all variants):**
- Default
- Hover: slight lift via `--shadow-1`; primary button background
  shifts to `#2A1D14` (one shade lighter); secondary darkens to
  `--paper-3`
- Active / pressed: shadow goes flat, transform translateY(1px)
- Focus: 2px outline at 2px offset in `--ink` (not the OS default
  blue ring)
- Disabled: ink-3 text, paper-3 background (primary) or
  paper-2 background (secondary); cursor not-allowed

**With icon:**
- Icon precedes label by 8px
- Icon size 16px, same colour as text
- Right-pointing arrow (→) used at the end of "Generate ↓" /
  "Continue →" CTAs

### Toggle (switch)

Used for enable/disable in Integrations, Settings, per-row toggles.

```
[ Settings ]     ●━━━○━━━●      ← on state (right)
[ Settings ]     ●━━━●━━━○      ← off state (left)
```

- Track: 36px wide, 20px tall, 10px radius
- Thumb: 16px circle, white, soft shadow
- Off: track = `--paper-3`, thumb = white
- On: track = `--ink`, thumb = white
- Disabled: track 50% opacity, no pointer events
- Transition: 120ms ease-out

### Card

The single most-used container in the dashboard. Standard card shape:

- Background: `--paper-2`
- Border: 1px `--ink-4`
- Radius: `--radius-md` (10px) for inline cards; `--radius-lg` (14px)
  for major cards
- Shadow: `--shadow-1` default; `--shadow-2` on hover (when card is
  interactive)
- Padding: 20px (default), 24px (major cards)

### Integration card (specific pattern)

Used on the Integrations page. Three-column grid on desktop.

```
┌─────────────────────────────────────────────┐
│  [coloured logo]                  domain ↗  │
│                                              │
│  Integration Name                            │
│  Short description of what this integration  │
│  does, two or three lines maximum.           │
│                                              │
│  [⚙ Settings]                  ●━━━○━━━●    │
└─────────────────────────────────────────────┘
```

- Logo: 40x40px, coloured rounded-rectangle (the integration's brand
  colour — this is the ONE place coloured icon backgrounds are
  allowed, because they're external product logos, not Vera's chrome)
- Domain link: top-right, 12px Inter 500, ink-3, with `↗` glyph
- Name: 16px Inter 600
- Description: 13px Inter 400, ink-2, 2-3 lines clamped
- Settings button: ghost variant, compact size, gear icon + label
- Toggle: standard toggle, right-aligned
- Padding: 24px
- Min-height: 220px (to make the grid even)
- Grid: 3 columns at ≥1280px, 2 at 1024-1280px, 1 at <1024px (v2)
- Gap: 24px

### Recommendation card (AI Insights)

Used on Compliance for AI-generated recommendations, and on the
Contract Review surface for AI-suggested fixes.

```
┌─────────────────────────────────────────────────────┐
│  Recommendation title              [SEVERITY pill]  ↑
│                                                      ↓ (expand toggle)
│  ┌─────────────────────────────────────────────┐   │
│  │ Quoted source text in muted background       │   │
│  └─────────────────────────────────────────────┘   │
│                                                      │
│  ⚠ One-line description of the issue                │
│                                                      │
│  [Apply recommendation]                              │
└─────────────────────────────────────────────────────┘
```

- Title: Inter 500, 15px
- Severity pill: see **Badge** below
- Quoted source: paper-3 background, 13px Inter 400, 8px radius,
  12px padding, italic optional
- Issue description: 13px Inter 400, ink-2, prefixed by amber
  warning triangle (⚠)
- Apply button: primary variant, full-width
- Expand/collapse caret on right
- Default: only title + severity visible; expands to show quote +
  description + action

### Severity badge

A small pill used to mark issue severity. Three variants:

| Severity | Bg / fg | Use |
|---|---|---|
| HIGH | `#F2D5CC` / `#7A2E1F` | Critical violation, expired BAA, prohibited use detected |
| MEDIUM | `#F4E3C9` / `#9C6A1D` | Stale artifact, missing recommended notice, reviewer time below threshold |
| LOW | `#DDE5D5` / `#3E5C3B` | Minor drift, optional improvement |

**Anatomy:**
- Height: 22px
- Padding: 0 10px
- Radius: 6px (rectangular pill — not full pill, not square)
- Font: Inter 500, 11px, tracking 0.04em, uppercase
- No icon — text label only

### Status indicator (dot + label)

A small colored circle paired with a text label. Used for showing
state next to entity names (customers, decisions, documents).

| State | Dot colour | Example label |
|---|---|---|
| OK | `--status-ok` | "Fully compliant", "Hash chain valid", "BAA active" |
| Warn | `--status-warn` | "BAA expires in 30 days", "Reviewer below threshold", "Stale" |
| Error | `--status-error` | "Expired BAA", "Chain integrity violation", "Outdated reference" |
| Neutral | `--ink-3` | "Inactive", "No data yet", "Not yet deployed" |

**Anatomy:**
- Dot: 8px circle, filled
- Gap to label: 8px
- Label: Inter 400, 13px, ink colour
- Never used without a label

Where the dot appears in a status icon column (e.g., compliance
insights table), it can be replaced with a larger filled icon:
- ✓ in olive circle (24px) — compliant
- ⚠ amber outlined triangle (24px) — warning
- ✕ in brick circle (24px) — error

### Table

The default tabular data presentation. Used in Customers list,
Compliance insights, Recent activity drill-down.

**Anatomy:**

```
COLUMN A         COLUMN B    COLUMN C          COLUMN D
────────────────────────────────────────────────────────────
●  Row label     Sub data    Status indicator  Action button
●  Row label     Sub data    Status indicator  Action button
●  Row label     Sub data    Status indicator  Action button
```

**Tokens:**
- Column header: small-caps Inter 12px / 600 / tracking 0.10em /
  ink-2 / paper-3 background
- Column header padding: 12px vertical, 20px horizontal
- Cell padding: 16px vertical, 20px horizontal
- Cell text: Inter 400, 14px
- Cell numeric text: same with tabular-nums
- Row separator: 1px `--ink-4` (between rows only, not outside edges)
- Row height: ~52px including padding
- Hover state: paper-2/50 background fill across whole row
- Click target: entire row, when row is navigable (e.g., Customers
  list); cursor changes to pointer
- Action button column: right-aligned, secondary variant, compact size

No striping. No outside borders. Headers separated from rows by 1px
ink-4 only.

### Modal / dialog

Overlaid centered work surface. See Pattern C above.

**Anatomy:**

```
┌─────────────────────────────────────────────  × ┐
│  Modal title                                     │
│                                                  │
│  ────────                                        │
│                                                  │
│  Content (form fields, radio options,            │
│  explanatory copy, nested cards)                 │
│                                                  │
│  ────────                                        │
│                                                  │
│  [secondary button]            [primary button]  │
└──────────────────────────────────────────────────┘
```

- Container: paper background, 14px radius, 1px ink-4 border,
  `--shadow-2`
- Title: Petrona 400, 24px, top of card
- Close (×): top-right, ghost button, 12px from edge
- Internal padding: 32px (content), 24px (header + footer rows)
- Footer separator: 1px `--ink-4` above button row
- Button row: right-aligned, primary button last (rightmost)
- Backdrop: `rgba(31,22,16,0.32)`, blur 4px optional
- Entrance: 200ms ease-out scale 0.96 → 1.0 + fade
- Width: 480px (default), 560px (form-heavy), 720px (Match Review,
  multi-column)

### Input field

```
┌──────────────────────────────────────────────────────┐
│ Field label                                          │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Input value or placeholder                       │ │
│ └──────────────────────────────────────────────────┘ │
│ Optional help text in ink-3                         │
└──────────────────────────────────────────────────────┘
```

- Label: 12px Inter 500, uppercase tracking, ink-2
- Input: 40px height, paper background, 1px ink-4 border, 8px radius
- Input padding: 0 12px
- Input text: 14px Inter 400
- Placeholder: ink-3
- Help text: 12px Inter 400, ink-3, below input with 6px gap
- Focus: 1px ink border (replaces ink-4) + subtle paper-2 inner fill
- Error: 1px brick border, 12px Inter 400 brick error message
- Disabled: paper-3 background, ink-3 text

Selects use the same shape with a small caret on the right edge.
Textareas are 100+ px tall, same border + padding treatment, with a
character counter at bottom-right if maxLength is set.

### Radio / Checkbox

- Radio: 16px circle, 1px ink-4 border, paper-2 inner; selected has
  a 6px ink dot center
- Checkbox: 16px square, 4px radius, 1px ink-4 border; selected fills
  with ink and shows a white check
- Hit target: 36px minimum (label + control area)
- Label: 14px Inter 400, ink

In option lists (e.g., the PDF modal's Branding choice, the wizard's
path choice), each option is a row with:
- Radio at left
- Bold label on first line (Inter 500, 14px)
- Description on second line (Inter 400, 13px, ink-2)
- Row padding: 12px vertical, 16px horizontal
- Selected row: subtle paper-2 background

### Avatar

Used for user identity in collaboration, comments, profile chip.

- Size: 24px (in lists), 32px (in chips), 40px (in profile menus)
- Shape: full circle
- Content: initials (1-2 letters, Inter 600, sized to fit)
- Background: deterministic from user_id, picked from the avatar
  palette (see Color section)
- Foreground (initials): white or paper, contrast-checked
- 1px ink-4 outer border (visible only on hover or focus, optional)

### Collaboration cursor

A small label-tagged cursor used in real-time editing surfaces
(Contract review, when multiple users are present).

```
       │
       ▼
  ┌────────────┐
  │ Arthur E.  │  ← name label
  └────────────┘
```

- Cursor stem: 2px wide vertical bar in user's avatar colour
- Label: 11px Inter 500, paper text, user avatar colour background,
  4px radius, 4px padding
- Position: anchored to cursor head, offset 4px below
- Selection range (when user has selected text): user colour at 30%
  opacity behind the selection

### Comment & comment thread

The right-rail comment system used on the Contract review surface.

```
┌──────────────────────────────────────┐
│ (A)  Arthur E.                       │
│      Jan 18, 2025 — 02:53 PM         │
│                                      │
│      Can we confirm whether this     │
│      agreement covers consulting      │
│      only, or also advisory          │
│      services?                       │
│                                      │
└──────────────────────────────────────┘
```

- Avatar at left (24px)
- Name: Inter 500, 13px, ink
- Timestamp: Inter 400, 11px, ink-3 (full date + time, not relative
  "2 hours ago" — auditable)
- Comment body: Inter 400, 14px, ink, line-height 1.5
- Vertical padding: 16px between comments
- Bottom 1px ink-4 separator
- Active comment (one selected in the document): paper-2 background
  on the comment block, 8px radius
- Reply: shown indented or in a thread expand pattern (v2 — v1 ships
  flat)

### Inline highlight (annotations on text)

Used to mark spans of text the AI flagged, or selected text in a
comment thread. Three colours map to severity / role:

| Highlight | Bg | Notes |
|---|---|---|
| AI-flagged severity HIGH | `#F2D5CC` | Critical issues |
| AI-flagged severity MEDIUM | `#F4E3C9` | Recommendations |
| Selection / comment anchor | `#D5DEE5` (cool desaturated blue) | Comment thread highlights — only place a cool hue appears on the dashboard |
| User-selected text (live) | `rgba(74,123,183,0.18)` | Live selection during a review session |

Highlights have no outline; only background fill. Underlying text
colour stays ink.

### AI chat interface

Used on AI Generator, AI Review insights, AI Contract Review surfaces.
The right-panel chat pattern.

```
                          ┌────────────────────────────┐
                          │ User message in paper-3    │
                          │ rounded bubble, right-      │
                          │ aligned.                    │
                          └────────────────────────────┘
                                            timestamp ↑

  (A) AI Agent    4:38 PM
       Plain-prose response, left-aligned. No bubble
       background — text sits on the paper. Uses bullet
       lists, bold labels, citations as needed.

       • Bold label: explanation
       • Bold label: explanation
```

**User messages:**
- Right-aligned, max-width 70% of panel
- Background: `--paper-3`, 12px radius
- Padding: 12px 16px
- Text: Inter 400, 14px, ink

**AI messages:**
- Left-aligned, no bubble background
- Avatar (24px) + name + timestamp on first line
- Body uses standard typography (paragraphs, bullets, bold labels)
- Bullets indent 16px; bold labels at start of bullet are Inter 600

**Input field:**
- Bottom of panel, sticky
- Text area: paper-2 background, 1px ink-4 border, 10px radius,
  min-height 48px
- Left-side icons: attach (paperclip), image (image), mic (microphone),
  4-dot menu (more) — 16px each, ink-3, 12px gap
- Right-side send button: 32px circle, ink background, paper arrow icon
- Send activated on Enter (Shift+Enter for newline)

### Document / file icon

Small red PDF or document icon used in lists (Compliance Insights
table, document attachments). Single colour: a muted red roughly
`#C44A3A`. Shape is the standard "page with folded corner"
silhouette, filled, 16-24px depending on context.

### Empty state

When a list or page has no content yet.

```
┌──────────────────────────────────────────┐
│                                           │
│                                           │
│         You haven't generated any         │
│         audit PDFs yet.                   │
│                                           │
│         [Generate your first PDF →]       │
│                                           │
│                                           │
└──────────────────────────────────────────┘
```

- Centered in the available space
- Title: 18px Inter 500, ink
- Optional one-line subtitle (14px Inter 400, ink-2)
- CTA: primary button, default size, with right-arrow
- No illustration. No icon. No "🎉" emoji.

### Loading state

Three patterns by duration:

- **<200ms (most actions):** no indicator. Just complete and reveal
  the new state.
- **200ms-2s (PDF generation, AI insight):** spinner inline next to
  the button label that triggered it; button is disabled. Spinner
  is a 12px circular indeterminate spinner in ink.
- **2s-30s (long jobs like CSV import, audit PDF rendering):**
  progress bar in the top of the affected modal or card. Bar is
  4px tall, paper-3 background, ink fill. Below the bar: text
  status "Generating PDF (3 of 7 sections)..." in 12px ink-2.

No skeleton screens (skeletons read as marketing slop). Use spinners
or progress bars.

### Tooltip

Used on hover over icons, badges, status dots, truncated text.

- Background: ink, paper text
- Padding: 6px 10px
- Radius: 6px
- Font: 12px Inter 500
- Arrow: 6px triangle in ink, pointing at the trigger
- Delay: 400ms hover before show, 100ms before hide
- Max-width: 280px

### Breadcrumb

Used in the top bar.

```
Contracts  ›  Master services  ›  Edit
```

- Each segment: 14px Inter 500, ink-2
- Separator: `›` (single right-pointing chevron), ink-3, 12px
- Last segment: ink (current page, not navigable)
- Earlier segments: navigable, hover transitions to ink colour
- Padding: 4px between segment and chevron

---

## Motion

Slightly more responsive than the marketing surface — the dashboard
is a tool, not a magazine.

| Duration | Use | Easing |
|---|---|---|
| 80-120ms | Hover, focus, button press | ease-out |
| 200-280ms | Modal entrance, panel reveal, accordion open | cubic-bezier(0.16, 1, 0.3, 1) (strong ease-out) |
| 320-480ms | Page transition, sidebar collapse (v2) | same strong ease-out |

**Reduced motion** (`prefers-reduced-motion: reduce`):
- All transitions become instant
- No scale or translate transforms
- No fade durations — opacity 0 or 1 directly

**No** parallax, scroll-jacking, spring physics, bounce, or stagger
animations.

---

## Voice & copy

Operational tone, more directive than the marketing surface.

- **Register:** Plain, brief, factual. The compliance officer wants
  to scan and act, not read.
- **Tense:** Imperative for actions ("Generate audit PDF", "Renew",
  "Apply recommendation"). Present-tense for state ("BAA expires
  Jun 23, 2027", "All chains valid").
- **Date format:** Full date with year ("Jun 23, 2027", "May 19, 2026")
  rather than relative ("13 months from now"). When both are useful,
  show both: "Jun 23, 2027 · 13 months away".
- **Number format:** Always tabular-nums, comma separators
  ("2,847 decisions"), no abbreviation under 10K. "12,500 decisions"
  not "12.5K decisions" — accuracy beats brevity.
- **Severity language:** Match the severity badge. HIGH = "Critical"
  or specific consequence ("BAA expired"). MEDIUM = "Recommended" or
  "Warning". LOW = "Optional" or "Consider".
- **Recommendation language (AI insights):** Always "Consider X" or
  "Recommended: X" — never "You should X" (too prescriptive) or
  "This will make you compliant" (Delve trap).
- **Empty states:** State the fact, offer the action. "You haven't
  generated any audit PDFs yet. [Generate your first PDF →]"
- **Error messages:** State what went wrong, what to do about it.
  Never "Something went wrong." Always "Webhook delivery to
  api.abridge.com failed — endpoint returned 503. Vera will retry in
  5 minutes. [View retry schedule]"

### Vocabulary that's in

- "Customer" (not Hospital, not Tenant — generic across verticals)
- "Audit-ready PDF"
- "Compliance posture" (not "compliance score")
- "Reviewer attestation"
- "Hash chain"
- "Tenant ID"
- "Standing notice"
- "Off-Vera checkpoint"

### Vocabulary that's out

- "Score" (use "posture")
- "Hospital" (use "customer" in UI; "hospital" only when describing the medtech vertical specifically)
- "Tenant" (engineering-internal; user-facing is "customer")
- "Dashboard" (don't refer to the product as a dashboard within the product itself)
- "Compliant" applied to the customer ("you are compliant" — that's a regulator's call, not Vera's)

---

## What this system deliberately doesn't do

- **No dark mode in v1.** The dashboard is always served on warm
  paper. v2 may revisit if customer demand is strong, but inverting
  an editorial cream palette to dark is its own design phase.
- **No charts or graphs.** Compliance officers want yes/no answers,
  not visualizations. v2 may add a posture-over-time line chart on
  the Compliance page if the data is genuinely useful, but it's
  not v1.
- **No marketing copy.** The dashboard is a work surface. No
  "Welcome back, John!" greetings, no product tips, no "what's new"
  feed.
- **No customizable layout.** Users can't hide sections or rearrange
  the nav. The default is the answer.
- **No mobile optimization in v1.** Mobile-responsive (doesn't break)
  but not mobile-first. Compliance officers don't generate audit PDFs
  from phones.
- **No 3-column iconed-circle feature grids.** The "canonical AI
  SaaS slop" pattern is banned. Cards and tables instead.
- **No coloured icon backgrounds in Vera chrome.** External
  integration logos (SignFlow, Slack, etc.) keep their brand colours
  — they're someone else's mark. Vera's own icons stay ink-coloured.
- **No notifications panel.** Email is the notification channel.
  In-dashboard banners on Home cover the "you need to know" cases.
- **No keyboard shortcut palette in v1.** Linear-style ⌘K is a v3
  feature once the surface is rich enough to justify it.
- **No animated loaders beyond a spinner.** No bouncing dots, no
  pulsing skeletons, no progress shimmer.

---

## Implementation notes (for engineering)

These guide the React component library you build in
`frontend/app/(dashboard)/` and shared in `frontend/components/`.

### Token implementation

Tokens live in CSS custom properties in `frontend/app/globals.css`
under a `.dashboard` selector (so the dashboard doesn't bleed into
the marketing surface, which uses the same tokens but at
landing-density).

```css
.dashboard {
  --paper: #FEFAF3;
  --paper-2: #F5EFE3;
  --paper-3: #EDE5D2;
  --ink: #1F1610;
  --ink-2: #57514D;
  --ink-3: rgba(31, 22, 16, 0.45);
  --ink-4: rgba(31, 22, 16, 0.14);

  --status-ok: #3E5C3B;
  --status-ok-bg: #DDE5D5;
  --status-warn: #9C6A1D;
  --status-warn-bg: #F4E3C9;
  --status-error: #7A2E1F;
  --status-error-bg: #F2D5CC;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;

  --shadow-1: 0 1px 2px rgba(31,22,16,0.06), 0 1px 1px rgba(31,22,16,0.04);
  --shadow-2: 0 12px 32px rgba(31,22,16,0.08), 0 2px 6px rgba(31,22,16,0.05);

  --space-2xs: 4px; --space-xs: 8px; --space-sm: 12px; --space-md: 16px;
  --space-lg: 20px; --space-xl: 24px; --space-2xl: 32px; --space-3xl: 48px;
}
```

### Component file structure

```
frontend/components/dashboard/
  Sidebar/
    Sidebar.tsx
    ProjectSwitcher.tsx
    NavSection.tsx
    NavItem.tsx
    UserChip.tsx
  TopBar/
    TopBar.tsx
    Breadcrumb.tsx
  PageHeader/
    PageHeader.tsx
  Button/
    Button.tsx               // primary | secondary | ghost
  Toggle/
    Toggle.tsx
  Card/
    Card.tsx                 // generic
    IntegrationCard.tsx
    RecommendationCard.tsx
  Badge/
    SeverityBadge.tsx        // HIGH | MEDIUM | LOW
    StatusBadge.tsx
  StatusIndicator/
    StatusDot.tsx            // dot + label
    StatusIcon.tsx           // larger circle with check/warn/x
  Table/
    Table.tsx
    TableRow.tsx
    TableHeader.tsx
  Modal/
    Modal.tsx
  Avatar/
    Avatar.tsx
    AvatarGroup.tsx
  Comments/
    Comment.tsx
    CommentThread.tsx
    InlineHighlight.tsx
  Cursor/
    CollaborationCursor.tsx
  Chat/
    ChatPanel.tsx
    UserMessage.tsx
    AgentMessage.tsx
    ChatInput.tsx
  Form/
    Input.tsx
    Select.tsx
    Textarea.tsx
    Radio.tsx
    Checkbox.tsx
    RadioOption.tsx          // the labeled-row variant
  EmptyState/
    EmptyState.tsx
  Loading/
    Spinner.tsx
    ProgressBar.tsx
  Tooltip/
    Tooltip.tsx
  Icon/
    Icon.tsx                 // wrapper around lucide-react filled variants
    DocumentIcon.tsx         // the red-PDF treatment
```

### Icon library

Use `lucide-react` filled variants where they exist; fallback to
`lucide-react` outline at stroke-width 1.5px. No custom icons in v1.
Icon colours come from text/foreground colour — never coloured.

Exception: the DocumentIcon (PDF) is filled muted red. Single
exception in the chrome.

### Type loading

Google Fonts via single `<link>` in `globals.css`, `display=swap`.
Subset: `Petrona:ital,wght@0,400;0,500;1,400;1,500` and
`Inter:wght@400;500;600`. JetBrains Mono is only loaded on the
technical verification page (lazy import).

### Accessibility minimums

- All interactive elements have keyboard focus state (2px ink outline
  at 2px offset)
- All status indicators include text labels (never colour alone)
- All buttons have aria-label when icon-only
- All form fields have associated `<label>` (not placeholder-as-label)
- All modals trap focus and restore focus on close
- Colour contrast: ink-on-paper is WCAG AA at all sizes; ink-2 is
  AA for body, may fall below for very small text — use ink-3 only
  for non-essential metadata
- Status colours never used standalone — always paired with text

---

## Cross-reference to dashboard-design.md

The four-page IA (Home, Customers, Compliance, Settings) lives in
[dashboard-design.md](dashboard-design.md). That document describes
**what is on each page** (the wireframes and information
architecture). This document describes **how each element looks and
behaves** (the visual tokens and components).

If you're implementing a screen, start with `dashboard-design.md` to
understand the layout, then come here for the component-level
specifications.

---

## TL;DR

Light theme, warm cream, Petrona display, Inter body — same tokens as
the marketing surface, applied at higher density with a dense
component library. Status colours are oxidised olive / amber / brick,
used sparingly. No dark mode, no charts, no marketing chrome, no
gradients, no slop. Sidebar + content + optional right panel covers
every layout. Cards, tables, modals, badges, status indicators, and
an AI chat panel cover every component. Everything is auditable
through tokens; everything inherits from a small palette of
foundational decisions; everything reads the way OpenAI's platform
console reads — confident, calm, and almost empty.
