# Design System — Vera

## Product Context

- **What this is:** Vera is the trust layer for AI agents. It seals every AI decision the moment it's made, into a verifiable record that holds up in front of a regulator, an auditor, or a customer dispute.
- **Who it's for:** CEOs of companies operating in regulated spaces, and the in-house counsel / general counsel who advise them. Secondary audience: heads of risk, compliance, and audit. Engineering decision-makers are tier-three on the marketing surface.
- **Space/industry:** Regulated AI deployment — lending, underwriting, clinical decision support, and hiring. AI governance / AI evidence / RegTech-adjacent.
- **Project type:** Marketing site (landing page + regulations page + product pages) with a connected web application (dashboard, account, evidence viewer).

## The Memorable Thing

Vera is the product that makes a regulator's email feel routine.

When a buyer leaves the landing page, the one thing they should remember is the **posture** — a calm, considered, trusted-advisor brand that treats AI compliance the way a top law firm treats an opinion letter. Not a developer tool. Not a security product. A piece of professional infrastructure that a General Counsel would be comfortable forwarding to their CEO.

Every design decision below serves this posture.

## Aesthetic Direction

- **Direction:** Editorial / refined. Warm-neutral, serif-led, generously spaced. Influence: Novera (the user's reference), with cues from long-form legal publications, *The Economist*, and considered B2B brands like Vanta and Patterson Belknap.
- **Decoration level:** Intentional. The page carries its weight through typography, photography, and pacing — not through illustration or ornament. Allowed decorative elements: a single warm-sepia oil-paint background texture in one or two product mockup sections (per Novera), subtle drop shadows on cards, quiet fade-ins on scroll. Disallowed: gradient backgrounds, illustrated icons, decorative shapes, code-rain backdrops, terminal aesthetics, hex-string callouts.
- **Mood:** Calm. Considered. Authoritative without being austere. The reader should feel like they're being briefed by a senior partner at a firm, not pitched by a vendor.
- **Reference sites:** [novera.framer.ai](https://novera.framer.ai/) (primary visual reference), and the warm-cream + serif-italic register common across editorial product brands.

## Typography

- **Display / Hero / Section titles:** **Petrona**, weight 400 (regular). Petrona is a transitional serif with a warm, literary feel — it's what makes Novera's hero feel like a magazine spread rather than a SaaS pitch. Use weight 400 even at 56–72px; the lightness is the point. Italic variant for emphasis fragments inside headlines (the "AI Agents", "can't", "thirty seconds" treatment in the current page should map to italic Petrona, not italic Newsreader). Loaded from Google Fonts: `Petrona:ital,wght@0,400;0,500;1,400;1,500`.
- **Body / Paragraphs / UI:** **Inter**, weight 400 for body, weight 500 for nav and buttons, weight 600 for emphasis. Note: Inter is on the gstack overused-fonts list, but it is **the exact font Novera uses for body**, and the user has explicitly asked for a Novera-inspired system. The combination of Petrona display + Inter body is the visual signature being borrowed. Loaded from Google Fonts: `Inter:wght@400;500;600`.
- **UI labels / Small caps / Kickers:** **Inter** at 11–13px, weight 600, letter-spacing 0.08–0.14em, uppercase. This replaces the current `--mono` JetBrains Mono kickers across the page. The mono kickers are an engineering tell; small-caps Inter reads as editorial.
- **Data / Tables / Dashboard:** **Inter** with tabular-nums enabled (`font-feature-settings: "tnum"`). No monospace anywhere on the marketing surface. Monospace is reserved for the engineering sub-page and the in-app code editor only.
- **Code (engineering sub-page only):** **JetBrains Mono**, weight 400. Stays out of the marketing surface entirely.
- **Loading:** Google Fonts via a single `<link>` tag in `globals.css` — minimal subset, `display=swap`.
- **Scale:**
  - `--h1`: clamp(56px, 7vw, 92px) — Petrona 400
  - `--h2`: clamp(40px, 5vw, 64px) — Petrona 400
  - `--h2-cta`: clamp(48px, 6vw, 80px) — Petrona 400
  - `--h3`: 28px — Petrona 400 (italic for in-headline emphasis)
  - `--body-lg`: 20px — Inter 400, line-height 1.5
  - `--body`: 17px — Inter 400, line-height 1.55
  - `--body-sm`: 14px — Inter 400
  - `--label`: 12px — Inter 600, tracking 0.10em, uppercase

## Color

- **Approach:** Restrained. The entire palette stays within a warm-neutral range, with a single semantic red reserved for regulatory urgency callouts only. No emerald primary. No amber primary. No blue. The deliberate departure from the current Vera palette is removing emerald-as-brand-colour — emerald reads "developer tooling" (Vercel, Linear, GitHub) and pulls the brand away from where this ICP wants it to sit.
- **Primary surface (paper):** `#FEFAF3` — warm cream. This is the body background. Borrowed directly from Novera.
- **Secondary surface (paper-2):** `#F5EFE3` — slightly deeper cream, for cards and elevated surfaces.
- **Tertiary surface (paper-3):** `#EDE5D2` — used for muted chips, table headers, hover states.
- **Primary ink:** `#1F1610` — warm near-black with brown undertones. This is the body text, the headline colour, and the dark-CTA background.
- **Ink-2 (secondary text):** `#57514D` — warm muted gray-brown. Used for subheads, captions, kickers.
- **Ink-3 (tertiary text):** rgba(31,22,16,0.45) — used for metadata, hints.
- **Ink-4 (borders, dividers):** rgba(31,22,16,0.14).
- **Dark surface (the espresso card / dark CTA section):** `#1F1610` background, `#FEFAF3` foreground. Single dark element per page maximum (the bottom CTA).
- **Semantic red — regulatory urgency only:** `#7A2E1F` (oxidised brick), with a soft companion `#F2D5CC` for backgrounds. Reserved for: deadline section ("LIVE NOW" markers, "€15M / 3% turnover"), Problem section badges ("NO ANSWER"), and nowhere else. This is the one place on the page that's allowed to raise its voice.
- **Semantic success — only inside product/verification UI:** `#3E5C3B` (oxidised olive), companion `#DDE5D5`. Used sparingly — *not* a brand colour. The CLI-style "✓ chain intact" block should switch to this olive (or to ink-on-paper-2) instead of the current bright emerald.
- **Dark mode:** Not in scope for the marketing surface. The page is always served on warm cream; dark mode applies only to the dashboard/app once shipped. (Inverting an editorial cream brand to dark mode is the kind of thing that breaks the posture — it can be revisited as a separate design phase if/when the app needs it.)

## Spacing

- **Base unit:** 8px.
- **Density:** Spacious. The page should breathe. Novera's signature is that *most of the viewport is empty most of the time*, which is what makes the moments of content feel considered. Section vertical padding should be clamp(96px, 12vw, 160px) — significantly more generous than the current `--section-pad`.
- **Scale:** 2xs(4) xs(8) sm(12) md(20) lg(32) xl(48) 2xl(80) 3xl(128) 4xl(192).
- **Gutter:** clamp(24px, 4vw, 64px) on the page edges. Inside sections, max-content-width 1200px (current page goes wider — narrow it).

## Layout

- **Approach:** Hybrid — grid-disciplined for the dashboard/app, creative-editorial for the marketing surface. The landing page is allowed to break the grid with photographic insets, asymmetric two-column rows, and floating product mockup cards (Novera does this with overlapping cards on the warm-sepia oil-paint backdrop).
- **Grid:** 12-column with 24px gutters at desktop. Hero is allowed to span full-bleed; product sections use 8 of 12.
- **Max content width:** 1200px.
- **Border radius:** Hierarchical:
  - `sm`: 6px (chips, small buttons, badges)
  - `md`: 10px (buttons, inline cards, inputs)
  - `lg`: 14px (major cards, screenshots, the artifact preview)
  - `xl`: 20px (the dark CTA card, hero photo container)
  - `full`: 9999px (avatars, status dots)
- **Shadows:** Two shadows max across the site, both very soft:
  - `--shadow-1`: 0 1px 2px rgba(31,22,16,0.06), 0 1px 1px rgba(31,22,16,0.04)
  - `--shadow-2`: 0 12px 32px rgba(31,22,16,0.08), 0 2px 6px rgba(31,22,16,0.05)
  No shadow glow effects (the current `--shadow-glow-em` emerald glow goes away with the emerald).

## Motion

- **Approach:** Intentional, restrained, scroll-driven. The page should reveal itself the way Novera does — sections fade in as they enter the viewport, with a 200–400ms duration and an ease-out curve. No mid-scroll parallax. No scroll-jacking. No bounce. No spring. The mood is "considered," not "playful."
- **Easing:** enter `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out, strong). exit `cubic-bezier(0.4, 0, 1, 1)`. move `cubic-bezier(0.4, 0, 0.2, 1)`.
- **Duration:** micro 80–120ms (hover, focus), short 200–280ms (state transitions, fade-ins), medium 320–480ms (section reveals, modal entrance). No animation longer than 500ms on the marketing surface.
- **Reduced motion:** Honour `prefers-reduced-motion: reduce` — fade-ins become instant; the hero animation becomes a still image.

## Photography & Imagery

- **Hero:** A still photograph of a real human in a moment of focused work — counsel reading a document, an executive at a desk, hands resting on a printed contract. Lit warmly (golden hour / interior tungsten). Shot with shallow depth of field. Photo lives inside a rounded container (radius `lg` or `xl`) with `--shadow-2`. This is the single biggest mood signal on the page and the most direct borrow from Novera. *Avoid:* stock photos of suited people pointing at screens, abstract gradient renders, 3D illustrations of locks/shields/keys, AI-generated humans.
- **Section backdrops (optional, used sparingly):** A warm sepia / oil-paint texture (Novera uses this behind product cards in one or two sections). Source: a single hand-painted texture file, kept consistent across the site. Never used full-bleed — always cropped, always behind a card or screenshot.
- **Product mockups:** Real screenshots of the actual product UI (the evidence PDF, the dashboard, the verification view). Always presented inside a soft drop-shadowed card. Never with code visible on the marketing surface (except on the engineering sub-page).
- **Iconography:** Used minimally. Where icons appear (tick marks, status dots, list markers), they are 1.25px stroke line icons or filled circles in `--ink` or `--ink-2`. No coloured icons. No icon backgrounds.

## Voice & Copy

- **Register:** Plain English in an editorial register. Counsel and CEOs read *The Economist* and *Lawfare*, not Hacker News.
- **Avoid:** "court-admissible", "court-ready" (per user instruction), "trust me bro," over-the-top fear FUD, terminal command examples in marketing surfaces, hex strings, agent names like `data-agent`, latency claims in milliseconds.
- **Allowed (and encouraged):** "the seal", "the record", "the chain", "tamper-evident", "regulator-ready", "evidence trail", "independently verifiable", named regulations and dollar figures.
- **Numerals:** Spell out small numerals in headlines ("thirty seconds", "four questions, four answers"); use figures in body and tables ("€15M", "3% turnover", "1,400 applications").

## Component Library Direction

- **Buttons:** Two variants. **Primary** = espresso (`#1F1610` bg, `#FEFAF3` text, radius `md`, weight 500). **Secondary** = paper (cream bg, ink text, 1px ink-4 border, radius `md`). No emerald button. No green glow. The arrow glyph (→) stays — it's compatible with the editorial register.
- **Cards:** Cream-on-cream — paper-2 surface on paper background, 1px ink-4 border, `--shadow-1`. Hover lifts to `--shadow-2`.
- **Chips / Kickers:** Inter 12px, weight 600, tracking 0.10em, uppercase, `--ink-2` colour. No background, no border — just the small-caps text and an optional 24px horizontal rule before it (Novera pattern).
- **Tables:** Inter tabular-nums. Header row in `--paper-3`. Cell padding 16px vertical, 20px horizontal. Borders only between rows, never on outside edges.
- **Status indicators:** 8px filled circle in semantic colour (oxidised red for urgent, olive for verified, ink-3 for neutral). Always paired with a text label — never used standalone.

## Pages That Inherit This System

- **Landing page** (`/`): Editorial register, hero photograph, generous pacing.
- **Regulations page** (`/regulations`): Same system, slightly denser — closer to a long-form explainer. ROI/risk-cost section (per user, already present here) stays.
- **Product / dashboard** (`/(dashboard)/*`): Same colour and type tokens, denser spacing (8px base unit applies, sections at 32–48px instead of 80–160px). Component library inherits the cream surface but the dashboard is allowed slightly more chrome (status dots, small-caps headers, tabular data) — it's a work surface, not a brochure.
- **Login / Register**: Single centred card on the cream surface. Petrona for the page title, Inter for the form. Hero photo as a quiet half-pane on desktop.

## What This System Deliberately Doesn't Do

- **No emerald.** Emerald is the previous Vera brand colour and the colour every developer-tooling company uses. Removing it is the single biggest move in this redesign.
- **No mono font on marketing surfaces.** Mono fonts on a marketing page signal "engineering audience." The current page uses mono for kickers, microcopy, badges, dashboard previews, hashes — all of that switches to Inter small-caps. Mono is allowed on the engineering sub-page and in the in-app code editor.
- **No hex strings, no agent names, no latency callouts** on the marketing surface. The technical proof lives on a sub-page or in the white paper.
- **No bright accent colour.** The page draws attention through typography, photography, and pacing — not through hue.
- **No 3-column feature grid with iconed circles.** This is the canonical "AI SaaS slop" pattern. Vera uses two-column editorial rows with photographic or screenshot insets instead.
- **No purple gradients, no decorative blobs, no glassmorphism.** Standard slop exclusions per gstack defaults.

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-11 | Initial design system created | User invoked `/design-consultation`, referenced [novera.framer.ai](https://novera.framer.ai/) as primary visual inspiration. ICP is CEOs and in-house counsel of companies deploying AI in critical spaces. Current landing page positions toward engineers; this system repositions toward the actual buyer. |
| 2026-05-11 | Removed emerald as brand colour | Emerald reads "developer tooling" (Vercel, Linear) and pulls the brand toward the wrong audience. Replaced with espresso `#1F1610` as the high-contrast accent, in line with Novera. |
| 2026-05-11 | Petrona serif (weight 400) for display, Inter for body | Direct borrow from Novera. Inter is on the gstack overused-fonts list but is the exact body font that makes Novera's pairing work; user explicitly asked for a Novera-inspired system. |
| 2026-05-11 | No "court-ready" or "court-admissible" language anywhere | Per explicit user instruction. "Regulator-ready" and "evidence trail" are the approved alternatives. |
| 2026-05-11 | Kept "Trust Layer for AI Agents" headline and "Set up in thirty seconds" CTA | Per explicit user instruction. Both are positioning calls the user has already made. |
| 2026-05-11 | Industry strip excludes Algorithmic Trading | Per explicit user instruction. Lending, underwriting, clinical decision support, and hiring only. |
| 2026-05-11 | ROI/risk-cost section not added to landing | Per user note, already present on the regulations page. Don't duplicate. |
