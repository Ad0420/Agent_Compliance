# Landing Page Redesign Plan — Big Improvements

**Scope:** The seven big improvements (B1, B2, B3, B4, B6, B7, B8) from the
ICP critique, planned in detail against [DESIGN.md](../DESIGN.md) (Novera-
inspired warm cream / Petrona display / Inter body / espresso CTAs).

**Out of scope for this plan:** B5 (hero animation) needs a separate
treatment with photography sourcing and a still-vs-motion decision — it
moves on its own track.

**Already shipped:** PR #166 (15 small copy/colour edits S1–S15) and
PR #167 (em-dash removal) are merged. This plan picks up from that state.

---

## Phase 0 — Foundation work (must land first)

Three of the big improvements (B7 specifically, and B1/B2 partially)
depend on typography and colour tokens being wired up before component
work begins. Doing this in a single PR keeps the diff scannable and
prevents per-component palette drift.

### F1. Typography token migration

The current `globals.css` loads **Inter Tight + Newsreader + JetBrains
Mono**. DESIGN.md wants **Petrona + Inter + JetBrains Mono** (mono kept
only for the engineering sub-page and in-app code editor).

Change `frontend/app/globals.css`:

```css
/* Replace the existing @import url(...) at the top of globals.css */
@import url("https://fonts.googleapis.com/css2?family=Petrona:ital,wght@0,400;0,500;1,400;1,500&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap");

/* Replace the v4 font tokens */
--sans: "Inter", system-ui, -apple-system, sans-serif;
--serif: "Petrona", "Iowan Old Style", Georgia, serif;
--mono: "JetBrains Mono", "SF Mono", ui-monospace, monospace;
```

Petrona is loaded at weights 400 + 500 plus both italics. Inter at
400/500/600/700.

**Decision:** Inter remains on the gstack overused-fonts list, but it is
the exact body font that makes the Novera pairing work and the user has
explicitly approved the Novera direction. Documented in DESIGN.md
decisions log.

### F2. Colour token migration

Current emerald-as-brand stays available as a semantic token but is
demoted off the marketing surface. The espresso CTA already shipped via
S15 uses `var(--ink)` (#15140f), which is close enough to DESIGN.md's
#1F1610 that introducing a new variable is unnecessary noise.

Changes to `frontend/app/globals.css`:

```css
/* Add the oxidised red — the one semantic alarm colour */
--alarm: #7A2E1F;
--alarm-soft: #F2D5CC;

/* Add olive for verification UI (replaces emerald-as-success on marketing) */
--verified: #3E5C3B;
--verified-soft: #DDE5D5;

/* Keep --emerald available for the dashboard and existing dark-CTA links */
/* Do NOT delete --emerald — it's referenced in 30+ places */
```

The dark CTA currently uses `var(--emerald)` for its accent line and
kicker. **Decision:** keep that one usage. The dark CTA's emerald
accent against the espresso background reads as "trust signal," not
"developer tooling," because the surrounding context is no longer green.

### F3. Shadow + radius cleanup

DESIGN.md specifies two shadows max. The current `--shadow-glow-em`
(emerald glow on the hero CTA) was already removed via S15. Verify no
other components reference it:

```bash
grep -rn "shadow-glow-em" frontend/
```

If clean, delete the variable from globals.css.

---

## B1. Replace forensic-chain exhibit with regulator email scene

**Where:** Right column of the Problem section (currently
`<ForensicChainExhibit />` in `v4-problem.tsx`).

**Replace with:** A two-frame composition — a simulated regulator email
on top, a sealed-PDF reply on the bottom. Counsel sees the workflow
they actually live, not a Bloomberg-terminal hash table.

### The composition

```
+------------------------------------------------------+
|  [Email card]                                        |
|  From  dfpi@dfpi.ca.gov                              |
|  To    counsel@northstar-lending.com                 |
|  Subj  AI lending decision audit — Q1 2026           |
|                                                      |
|  Per California AB 316, demonstrate decision         |
|  integrity for the attached sample of 12 cases by    |
|  Friday, 5:47 PM PST.                                |
+------------------------------------------------------+
                          ↓
                  Friday, 5:47 PM
                          ↓
+------------------------------------------------------+
|  [Sealed PDF card — reuses <SignedPdfArtifact />]    |
|  northstar-q1-evidence.pdf                           |
|  ✓ Chain intact · 13 of 13 decisions verified        |
|  ✓ Sealed by AWS KMS (Virginia)                      |
+------------------------------------------------------+
```

### DESIGN.md alignment

- **Surface:** `var(--paper-2)` for both cards on `var(--paper)` background.
- **Email chrome:** ultra-restrained. Hairline `var(--ink-4)` border,
  radius `lg` (14px), `var(--shadow-1)`. Mock email client UI must be
  small caps Inter, never Gmail-iconography.
- **Headline serif emphasis:** the subject line in Petrona 400, body in
  Inter 400 at 15px line-height 1.55.
- **Connector:** vertical 24px ink-3 hairline + small Petrona italic
  timestamp "Friday, 5:47 PM" centred between cards.
- **PDF card:** reuse the existing `SignedPdfArtifact` component but
  pass a `compact` prop (new) to render at 70% scale with two summary
  lines instead of the full receipt.

### Information architecture

The four questions (`Q.01–Q.04`) on the left column stay. The email→PDF
scene replaces the forensic table on the right. The visual story now
matches the questions: "When this email arrives, can you answer? Yes,
with this PDF."

### States

Static composition — no loading, empty, error states needed. One motion:
on scroll-into-view, the email card fades in (300ms ease-out), then
after 400ms delay the PDF card fades in. Honour `prefers-reduced-motion`
(instant fade).

### Responsive

- **Desktop ≥1024px:** stacked vertical inside the right column (Problem
  section is already `v4-grid-2`).
- **Tablet 640–1023px:** stacked vertical, slightly smaller cards.
- **Mobile <640px:** cards span full width, vertical stack, timestamp
  connector becomes horizontal arrow "→".

### Accessibility

- Email card: `<article aria-label="Sample regulator email">` with a
  `<dl>` for From/To/Subject so screen readers get structured metadata.
- PDF card: `aria-label="Sealed evidence reply, 13 decisions verified"`.
- Decorative connector hidden with `aria-hidden`.
- Contrast: ink-on-paper-2 = ~15:1 (passes AAA).

### Component changes

- **New:** `frontend/components/landing/v4-regulator-scene.tsx`
- **Edit:** `frontend/components/landing/v4-problem.tsx` — replace
  `<ForensicChainExhibit />` import with `<RegulatorScene />`.
- **Keep:** `v4-forensic-chain-exhibit.tsx` lives on — it will be the
  centrepiece of the future engineering sub-page (B2 also references it).
- **Edit:** `v4-signed-pdf-artifact.tsx` — add an optional `compact`
  prop. Default behaviour unchanged.

### Open decisions (where you may want to redirect)

- **The regulator's name.** Using `dfpi@dfpi.ca.gov` (California
  Department of Financial Protection and Innovation) because AB 316 is
  already live and is the most concrete trigger. Could swap to a generic
  `regulator@example.gov` if you want to keep the page jurisdiction-neutral.
- **The applicant count.** "1,400 mortgage applications" pulls weight as
  a concrete number a CEO can imagine. Could go higher (10,000) or
  lower (47) depending on what's plausible for typical Vera customers.

---

## B2. Replace Python decorator code section with "How it works"

**Where:** The current V4Code section (Python `@audit` decorator + 5
tabs + dashboard preview side-by-side).

**Replace with:** Three numbered cards laid out horizontally, no code.

### The composition

```
SECTION KICKER:  HOW IT WORKS
SECTION TITLE:   Three steps. No engineering required.

+----------------+    +----------------+    +----------------+
|  01            |    |  02            |    |  03            |
|  Petrona       |    |  Petrona       |    |  Petrona       |
|  italic        |    |  italic        |    |  italic        |
|                |    |                |    |                |
|  Your AI runs  |    |  Vera silently |    |  You answer    |
|  as it always  |    |  seals every   |    |  regulators    |
|  has.          |    |  decision.     |    |  with one PDF. |
|                |    |                |    |                |
|  Vera sits     |    |  Each decision |    |  When a        |
|  alongside     |    |  is sealed by  |    |  question      |
|  your existing |    |  an independ-  |    |  comes, hand   |
|  system. No    |    |  ent third     |    |  over one      |
|  changes to    |    |  party at the  |    |  verified      |
|  decisioning   |    |  moment it     |    |  attachment.   |
|  logic.        |    |  happens.      |    |                |
+----------------+    +----------------+    +----------------+

                                For engineering teams →
```

### DESIGN.md alignment

- **Numerals:** Petrona italic 400 at clamp(64px, 8vw, 96px), colour
  `var(--ink-3)` (intentionally muted so they sit as marginalia).
- **Headlines:** Petrona 400 at clamp(24px, 3vw, 32px), line-height 1.15.
- **Body:** Inter 400 at 16px, line-height 1.55, colour `var(--ink-2)`.
- **Cards:** `var(--paper-2)` surface on `var(--paper)`, 1px `var(--ink-4)`
  border, radius `lg`, `var(--shadow-1)`. Hover lifts to `--shadow-2`
  (no other interactivity).
- **Connectors:** between cards on desktop, 24px ink-3 hairline arrows.
  Removed on mobile.
- **"For engineering teams →" link:** Inter 14px 500, ink-2, hover
  underline. Routes to `/engineering` (a new sub-page that hosts the
  current V4Code component + ForensicChainExhibit + integration matrix).

### Information architecture

- Section header: kicker + Petrona title (no italic emphasis fragment
  this time — the three cards are the emphasis).
- Three cards, 3-column grid desktop, 1-column mobile.
- The engineering link is small and quiet — it satisfies the engineer
  in the audience without distracting the CEO.

### States

Static. Cards fade-in on scroll, staggered 100ms each (300ms total).

### Responsive

- **Desktop ≥1024px:** 3 columns, gap clamp(32px, 4vw, 48px).
- **Tablet 768–1023px:** 3 columns, smaller cards, gap 24px.
- **Mobile <768px:** 1 column, full-width cards, connecting vertical
  hairline between them (replaces horizontal arrows).

### Accessibility

- `<ol>` semantics for the three steps.
- Decorative numerals (01/02/03) wrapped in `aria-hidden` spans since
  they're already conveyed by `<li>` order.
- "For engineering teams →" is a regular focusable `<Link>`.

### Component changes

- **New:** `frontend/components/landing/v4-how-it-works.tsx`
- **Edit:** `frontend/app/page.tsx` — replace `<V4Code />` import with
  `<V4HowItWorks />`.
- **Keep:** `v4-code.tsx` lives on — it moves to the future
  `/engineering` page.
- **Out of scope for this plan:** the `/engineering` sub-page itself.
  Track as a TODO; the link can route to a placeholder until then.

### Open decisions

- **Whether to keep a dashboard preview anywhere on the landing.** I
  recommend NO — the dashboard belongs on a `/product` page that
  prospects reach after they've decided to evaluate. Putting it on the
  landing reads as "look at our chrome" rather than "look at your
  problem solved." If you want it, I'd add it inside Step 03 ("you
  answer regulators…") as a small inset, not full-width.
- **Whether step 02 says "third party" or names a specific signer.**
  Naming AWS KMS specifically (as the verification receipt does) is more
  concrete but ties the message to a single vendor. Generic "third
  party" keeps it cleaner and matches the Compare section's existing
  language.

---

## B3. Reorder page for CEO scan pattern

**Current order:**
Hero → Customers (integrations) → Deadline → Problem → Compare → Code → Artifact → DarkCTA

**New order:**
Hero → **Deadline** → **Problem (with B1 scene)** → **Artifact** → Compare → **HowItWorks (B2)** → **Integrations (B6, renamed/demoted)** → **SocialProof (B4)** → DarkCTA

### Why this order

CEO/counsel scan pattern is **fear → validation → deliverable → trust →
implementation → proof → action.** The buyer's first decision is "is
this for me," which the hero+industry strip handles. The second is "do
I need to care now," which Deadline handles. From there the page should
descend into specifics about *what they'd hand a regulator*, then defend
that artifact against the obvious "we already log" objection, then show
implementation is easy, then prove with peers.

### Why integrations sits late

Integrations is a trust signal for engineering buyers and a distraction
for CEO buyers. Putting it near the bottom keeps it discoverable for the
former without slowing down the latter. SocialProof goes after
integrations because customer proof is the strongest argument to make
*last* before the closing CTA — recency bias is your friend.

### Component changes

- **Edit:** `frontend/app/page.tsx` — reorder imports and JSX. This is
  a pure file-shuffle edit, no component changes.

### Open decisions

- **Where Compare sits.** I've placed it between Artifact and HowItWorks.
  Alternative: put it directly after the Problem section (so questions →
  scene → "and logs don't suffice" → artifact). Both work. I chose the
  later position because the Artifact is more emotionally satisfying
  immediately after the Problem; Compare reads as the considered
  defence afterwards.
- **Whether to include integrations at all on the landing.** Defensible
  to cut entirely and put on `/product` or `/integrations` pages. I've
  kept it because removing it altogether feels evasive for the
  engineer-decision-maker who *does* visit the landing page.

---

## B4. Add social proof

**Where:** New section between Integrations and the dark CTA (per B3
ordering above).

### The composition

```
SECTION KICKER:  DESIGN PARTNERS
SECTION TITLE:   Trusted by teams that can't afford to be wrong.

+----------------------------------------+
|  "Petrona italic, large pull quote     |
|  set on cream paper, no card chrome.   |
|  The kind of quote that reads like     |
|  it could have been printed in The     |
|  Economist."                           |
|                                        |
|         Head of Compliance             |
|         Top-10 US digital lender       |
+----------------------------------------+

[Small-caps row of 5 placeholder logo silhouettes — "Design partners under NDA"]
```

### DESIGN.md alignment

- **Pull quote:** Petrona italic 500 at clamp(24px, 3vw, 36px), line-
  height 1.3, colour `var(--ink)`. No background card — just the quote
  sitting on cream with generous breathing room (top/bottom padding
  clamp(64px, 10vw, 128px)).
- **Attribution:** Inter 14px 500 small caps, ink-2, with the role on
  line 1 and the company descriptor on line 2.
- **Logo silhouettes:** 5 rounded rectangles at 32px height, ink-4 fill,
  72px width each, 24px gap. Subtitle below: "Design partners
  launching Q3 2026 — anonymised quotes available on request."

### Honesty constraint

Per the "no false claims" instruction in the design consultation:

- If real (even anonymised) partners exist, quote one of them with their
  approval and skip the placeholder logo row.
- If no real partners yet, ship the section but with the placeholder
  copy and a single quote that's clearly framed as a design-partner
  vision (e.g., a quote *to* prospective partners rather than *from* a
  current one). Or leave the quote slot empty and ship only the "design
  partners launching Q3 2026" framing.

**Recommended:** ship the section with whatever real proof you have. If
nothing is ready, acknowledge it explicitly — silence reads worse than
"we're under NDA."

### Information architecture

- Single-column composition. The visual weight is medium — large enough
  to register, quiet enough not to compete with the Artifact section's
  emphasis.
- Section uses the same `<V4SectionHeader />` component that the rest of
  the page uses, with `accent="amber"` for the kicker treatment (matches
  the gravitas of Deadline / Artifact).

### States

- **Has-quote state** (the intended ship state): renders the quote.
- **No-quote state**: renders only the logo-placeholder row + the
  "design partners launching Q3 2026" line. This is the design
  fallback if real proof isn't ready by ship date.

Both states are static; no loading/error.

### Responsive

- **Desktop ≥1024px:** quote 60% of grid width, attribution 40% right-
  aligned.
- **Tablet 768–1023px:** same 60/40 split.
- **Mobile <768px:** quote stacks above attribution, both full width.

### Accessibility

- `<blockquote>` for the quote with `<cite>` for attribution.
- Logo row uses `aria-label="Design partner logos, currently under NDA"`.
- Decorative quotation marks (if any are used in CSS pseudo-elements)
  hidden with `aria-hidden`.

### Component changes

- **New:** `frontend/components/landing/v4-social-proof.tsx`
- **Edit:** `frontend/app/page.tsx` — add to render list per B3 order.
- **Content TBD:** the actual quote text and attribution. Component
  takes them as props with sensible placeholder defaults that fail
  loudly in production (e.g., "QUOTE PENDING" if no real content).

### Open decisions

- **Whether to ship the section before real content is ready.** I
  strongly recommend yes — even an honest "design partners under NDA"
  acknowledgment is better than no section. CEOs will notice the
  absence and assume the worst.
- **Whether to include the placeholder logo row.** It's a hint of
  social proof without faking it. Could feel cheesy. Alternative: drop
  the logo row entirely and rely on the quote + attribution. I've kept
  it because it occupies space that would otherwise read as "nothing
  here yet."

---

## B6. Split misnamed Customers/Integrations section

**Where:** Current `v4-customers.tsx` component (which actually shows
integrations, not customers).

### Changes

1. **Rename component file:** `v4-customers.tsx` → `v4-integrations.tsx`.
2. **Rename exported component:** `V4Customers` → `V4Integrations`.
3. **Reduce integrations array:** OpenAI and Anthropic only. Drop
   LangChain and CrewAI from the marketing surface (they remain
   functional integrations, but engineers will find them on the
   `/engineering` page from B2's link).
4. **Move position** (handled by B3): from second-section-from-top to
   second-section-from-bottom.
5. **Simplify visual layout:** 4-column grid → 2-card row (centered),
   smaller per-card visual weight.

### DESIGN.md alignment

- **Kicker:** "WORKS WITH" (already shipped via S4, just smaller now)
  in Inter small caps 12px, ink-3, tracking 0.10em. Was mono in v4 — B7
  flips this.
- **Cards:** Inter 22px 600 for the provider name. Status dot becomes
  the new `var(--verified)` olive instead of emerald-soft.
- **Section padding:** matches DESIGN.md `clamp(96px, 12vw, 160px)`,
  same as other sections.

### Information architecture

- This is a quiet trust signal near the bottom. Reads as "we don't lock
  you into one model" rather than "look at our partner logos."
- Two cards, centred, with significant horizontal whitespace on either
  side (each card ~40% of content width).

### States

Static. No animation needed (the section is intentionally low-emphasis).

### Responsive

- **Desktop:** 2 cards side-by-side, centred.
- **Mobile:** 2 cards stacked, smaller.

### Accessibility

- Each card is a `<div>` with `aria-label="Compatible with OpenAI"` etc.
- The connection-status dot is decorative (`aria-hidden`).

### Component changes

- **Rename:** `v4-customers.tsx` → `v4-integrations.tsx`.
- **Edit:** `frontend/app/page.tsx` — update import name and position.
- **Update:** the INTEGRATIONS array to 2 entries.

### Open decisions

- **Whether to add Google Vertex AI / Azure OpenAI as future-state
  cards.** These are technically supported via Python SDK access but
  not first-class. I've left them out per the "no false claims"
  constraint. Adding them later (after first-class support ships) is
  trivial.
- **Whether to keep the connection-status dot animation.** It currently
  pulses (or appears static depending on CSS). For this audience, the
  status dot is a quiet trust signal — keep it static. The pulse is an
  engineering-tool vibe.

---

## B7. Drop engineering chrome throughout

**Surface area:** 38 instances of `var(--mono)` across the landing
components (verified by grep). Plus letter-spacing-heavy uppercase tags,
agent-name strings, and forensic timestamp formats.

### The migration

Across every landing component, replace:

```
fontFamily: "var(--mono)"  →  fontFamily: "var(--sans)"
```

…on the marketing surface only. Mono stays on:

- The engineering sub-page (`/engineering`, not yet built).
- The in-app code editor in the dashboard.
- The terminal-style code block inside `v4-code.tsx` (which moves to
  `/engineering` per B2).

### Per-component change list

| Component | Mono usages | What they're for | After |
|---|---|---|---|
| `v4-hero.tsx` | 2 | Microcopy ("Free to start · Thirty seconds…"), industry strip | Both → Inter small caps |
| `v4-customers.tsx` (→ `v4-integrations.tsx`) | 3 | Kicker, integration kind label, "connected" | All → Inter small caps |
| `v4-deadline.tsx` | 4 | "REGULATORY TIMELINE" tag, "LIVE NOW", milestone dates, "€15M / 3% turnover" | All → Inter (dates in Petrona 400, the fines callout in Petrona 500) |
| `v4-problem.tsx` | 2 | "Q.01" numbers, "✕ NO ANSWER" badge | Inter small caps |
| `v4-compare.tsx` | 2 | Kickers (EDITABLE / TAMPER-EVIDENT), row numbers | Inter small caps |
| `v4-code.tsx` | many | Code block contents | **No change** — V4Code moves to `/engineering` per B2 |
| `v4-artifact.tsx` | 4 | Kickers, verify-receipt label | Inter small caps |
| `v4-dark-cta.tsx` | 1 | Microcopy | Inter small caps |
| `v4-section-header.tsx` | 1 (kicker) | Kickers across all sections | Inter small caps |

### DESIGN.md alignment

- **All small-caps kickers:** Inter 12px, weight 600, letter-spacing
  0.10em, uppercase. Defined as a CSS class `.kicker-sm` in globals.css
  so it's reusable.
- **Status badges:** the "✕ NO ANSWER" / "LIVE NOW" / "EDITABLE" badges
  switch to Inter but keep their colour treatments (alarm-red for NO
  ANSWER / LIVE NOW, ink-4 border for EDITABLE).
- **Milestone dates** in Deadline switch to Petrona 400 (the dates are
  the gravitas — Petrona makes them feel like a publication).

### Risk and blast radius

This is the largest of the seven changes by line count. It touches
nearly every landing component but is a low-semantic-risk change
(typography only, no copy, no structural moves). It should ship as **a
single atomic PR** so the typography migration is visible as one diff
that reviewers can scan in two minutes.

### Component changes

- **Edit:** all 8 landing components listed above.
- **Edit:** `frontend/app/globals.css` — add `.kicker-sm` utility class.
- **Verify:** the dashboard pages (`/(dashboard)/*`) still use mono
  where appropriate — they're a separate surface and not in scope here.

### Open decisions

- **Whether to remove the `var(--mono)` token entirely from
  globals.css.** I'd keep it — the dashboard pages and the future
  `/engineering` page both legitimately need mono. The change here is
  *usage*, not the token itself.
- **Whether "Q.01" → "Q.01" stays formatted as it is, just in a sans
  font, or becomes "Question 01."** I'd keep "Q.01" — the abbreviation
  is fine in any typeface and the brevity helps the four-question
  rhythm on the left column.

---

## B8. Sharpen dark CTA framing

**Where:** `v4-dark-cta.tsx`. Builds on the S12+S13 changes from PR #166.

### The change

```
CURRENT (after PR #166):
KICKER:    START YOUR EVIDENCE TRAIL
HEADLINE:  Set up in thirty seconds.
SUBLINE:   Thirty seconds. Works alongside the AI you already run.

PROPOSED:
KICKER:    BEFORE THE FIRST EMAIL ARRIVES
HEADLINE:  Set up in thirty seconds.
SUBLINE:   California AB 316 is already live. The EU AI Act lands August 2, 2026.
           Thirty seconds. Works alongside the AI you already run.
```

The kicker changes from generic urgency ("start your evidence trail") to
*specific* urgency that connects narratively to the regulator email
scene from B1. The page now bookends with the same image: a regulator's
email arriving. The subline adds two regulatory dates — keeps the
deadline anchored in memory at the moment of CTA decision.

### DESIGN.md alignment

- **Kicker:** Inter 12px 700 small caps, letter-spacing 0.10em,
  emerald-on-espresso (the one place emerald stays on the marketing
  surface — see F2 above).
- **Headline:** Petrona 400, "thirty seconds." treatment becomes
  Petrona *italic* 500 (matching the Novera serif-italic emphasis
  pattern). Already partially shipped via the inline italic span — this
  just confirms the typeface migrates to Petrona.
- **Subline:** Inter 13px 500, night-text-3 colour. Two lines — first
  is the date callback, second is the existing "thirty seconds…" copy.

### Information architecture

- Single-column composition on dark espresso.
- The CTA stays right-aligned next to the headline (existing layout).
- The two-line subline lives below the CTA button, not above the
  headline — keeps the headline + CTA pairing tight.

### States

- Default: as above.
- Hover on the CTA button: cream surface lifts to bright white (already
  the case via existing styles).
- Reduced motion: no change needed; the section is static.

### Responsive

- **Desktop:** existing row-stack layout. Subline wraps onto 2 lines.
- **Mobile:** headline + CTA stack vertically (existing
  `.v4-row-stack` behaviour). Subline wraps to 3 lines.

### Accessibility

- Already accessible. Verify `<Link>` to `/register` has visible focus
  ring against the dark surface.
- The "California AB 316…" line is informational; no `aria-` additions
  needed.

### Component changes

- **Edit only:** `v4-dark-cta.tsx`. Text and one font swap.

### Open decisions

- **Which kicker.** I'm proposing "BEFORE THE FIRST EMAIL ARRIVES" because
  it pairs narratively with the B1 regulator email scene. The previous
  "START YOUR EVIDENCE TRAIL" (shipped via S13) is also defensible. If
  B1 doesn't ship, fall back to the existing kicker.
- **Whether to keep two regulatory dates in the subline.** "California
  AB 316 is already live. The EU AI Act lands August 2, 2026." doubles
  the subline length. Alternative: pick one date. I'd keep both — the
  combination of "already live" and "imminent" is what creates urgency.

---

## Page-level information architecture (after all changes)

The final structure of `frontend/app/page.tsx`:

```tsx
<div>
  <V4Nav />
  <V4Hero />              {/* with industry strip from S14 */}
  <V4Deadline />          {/* moved up */}
  <V4Problem />           {/* B1: regulator email scene replaces forensic chain */}
  <V4Artifact />          {/* moved up */}
  <V4Compare />
  <V4HowItWorks />        {/* B2: replaces V4Code */}
  <V4Integrations />      {/* B6: renamed, demoted */}
  <V4SocialProof />       {/* B4: new */}
  <V4DarkCTA />           {/* B8: sharpened framing */}
  <V4Footer />
</div>
```

The page goes from 10 sections (including Nav and Footer) to 11. The
reading time for the marketing surface stays roughly the same — the new
SocialProof section is quiet, the HowItWorks section is shorter than the
Code section it replaces, and the demoted Integrations section is
visually smaller.

---

## Implementation sequence (recommended PR ordering)

Each row is one PR. Rationale: each PR ships a complete user-visible
change, no PR depends on an unmerged PR, and each PR is reviewable in
under 15 minutes.

| # | PR | What ships | Risk | Depends on |
|---|---|---|---|---|
| 1 | `chore: typography + colour token migration` | Petrona + Inter loaded, `--alarm` and `--verified` added, F1+F2+F3 complete | Low — font tokens only | none |
| 2 | `landing: drop engineering chrome (B7)` | All 38 `var(--mono)` usages on landing flip to `var(--sans)`; new `.kicker-sm` class | Medium — high line count, zero semantic change | PR #1 |
| 3 | `landing: replace forensic chain with regulator email scene (B1)` | New `<V4RegulatorScene />`, ForensicChainExhibit moves out of the page | Medium — new component, content choice (regulator name, applicant count) | PR #1 |
| 4 | `landing: how-it-works replaces decorator code section (B2)` | New `<V4HowItWorks />`, V4Code removed from page (kept for future `/engineering`) | Low — pure replacement | PR #1 |
| 5 | `landing: rename customers→integrations and reduce list (B6)` | File rename, INTEGRATIONS array shrinks to 2, layout simplifies | Low — small surface | PR #2 |
| 6 | `landing: add social proof section (B4)` | New `<V4SocialProof />` with placeholder content + honest fallback state | Low — additive | PR #1 |
| 7 | `landing: reorder for CEO scan pattern (B3)` | Pure render-order edit in `page.tsx` | Low — one-file change | PRs #3, #4, #5, #6 |
| 8 | `landing: sharpen dark CTA framing (B8)` | Kicker + subline edits in `v4-dark-cta.tsx` | Low — text-only | PR #3 (for narrative coherence) |

**Critical path:** PR #1 → PR #3 → PR #7 (5 PRs total on the critical path).
Other PRs can land in parallel.

**Total estimated time** for the whole sequence: 8 PRs × ~30 minutes
each implementation + ~15 minutes review/QA = ~6 hours of focused work,
spread across however many sessions the team wants.

---

## What this plan deliberately doesn't change

- **The headline** "Trust Layer for AI Agents" — per your explicit
  instruction.
- **The "Set up in thirty seconds" CTA** — per your explicit instruction.
- **The hero animation (B5)** — separate track, needs photography
  sourcing and a still-vs-motion decision.
- **The regulations page** — out of scope. The ROI/risk-cost section
  per your earlier note already lives there.
- **The dashboard / app surface** — out of scope. Dashboard inherits
  the colour tokens from this plan but its layout, density, and
  component library are a separate design phase.
- **Dark mode** — per DESIGN.md, dark mode on the marketing surface
  isn't in scope. The page is always served on warm cream.

---

## Decisions still open for your input

These are calls I've made in the plan above but where reasonable people
could disagree. None block implementation — they're "redirect if you
want different" moments.

1. **B1 regulator details.** Using `dfpi@dfpi.ca.gov` and "1,400 mortgage
   applications" as concrete placeholders. Swap if you want different
   industry framing or different regulator (e.g., FCA for UK, OCC for
   federal banking).
2. **B2 dashboard preview.** I've removed it entirely. You may want a
   small inset inside Step 03.
3. **B3 Compare position.** Placed between Artifact and HowItWorks.
   Could also sit immediately after Problem.
4. **B4 social proof shipping state.** Recommend shipping with honest
   placeholder. You may have real partners ready.
5. **B6 integration set.** Recommend OpenAI + Anthropic only on
   marketing surface. You may want Google or Azure OpenAI.
6. **B7 scope.** I'm flipping every `var(--mono)` on marketing
   components in one PR. You may prefer to migrate per-component.
7. **B8 kicker.** "BEFORE THE FIRST EMAIL ARRIVES" vs. the already-
   shipped "START YOUR EVIDENCE TRAIL." Either works.

---

## Next steps

When you're ready to start implementing:

- Start with **PR #1** (typography + colour tokens). It unlocks every
  other PR and is the most reversible.
- Follow with **PR #3** (B1 regulator email scene) — it's the highest-
  leverage user-visible change and is the single PR most likely to need
  a design iteration based on how the email card actually looks at
  render time.
- The rest can sequence in any order that makes sense to your branch
  hygiene.

When you want mockups of any specific section before implementation,
ask and I'll generate variants via `/design-shotgun` against the
sections that benefit most (likely B1 and B2).
