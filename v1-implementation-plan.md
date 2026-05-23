<!-- /autoplan restore point: /Users/priyansh/.gstack/projects/Ad0420-Agent_Compliance/claude-kind-pike-2e1230-autoplan-restore-20260521-000159.md -->
# Vera v1 — Implementation Plan

**The 8-week build that ships the policy engine MVP and the dashboard together.**
**Last updated:** 2026-05-20
**Pairs with:** [policy-engine-mvp.md](policy-engine-mvp.md), [dashboard-design-system.md](dashboard-design-system.md), [dashboard-design.md](dashboard-design.md)

---

## TL;DR

Build engine and dashboard **intertwined, in vertical slices** — not engine-first-then-dashboard. Each phase ships one customer-visible capability end to end (backend + SDK + UI), is dogfoodable in under a day at the phase boundary, and inherits its visual surface from the design system established in Phase 0. Eight weeks, seven phases, seven test gates.

---

## Why intertwined, not sequential

A sequential plan (engine for 6 weeks, dashboard at the end) is the default reading of [policy-engine-mvp.md §8-week shipping plan](policy-engine-mvp.md). It is the wrong shape for v1. Three reasons:

1. **Testability after every phase requires a UI.** Engine-only phases test as cURL responses and JSON dumps. A compliance officer can't dogfood JSON; an engineering lead can't show JSON to their CEO. The user's explicit requirement is "test out the product after every phase" — that requires a clickable surface from Phase 1 onward.
2. **The MVP doc's own schedule squeezes the frontend.** [policy-engine-mvp.md:1424-1432](policy-engine-mvp.md) puts the entire dashboard build into Weeks 5-6 (two weeks). The dashboard spec ([dashboard-design-system.md](dashboard-design-system.md) + [dashboard-design.md](dashboard-design.md)) defines a four-page IA, a 25+ component library, three layout patterns, and a strict design system. Two weeks for that work is where MVPs go to die.
3. **Engine and dashboard share concepts.** Customer (first-class multi-tenant entity), Review (HITL lifecycle), Posture (six dimensions), BAA chain, Decision stream. Building each engine concept against its UI catches shape mismatches at the moment they appear; building engine first guarantees a UI rewrite when the data shape meets the wireframe.

The vertical-slice cadence also matches Vera's sales motion: every phase boundary produces something demonstrable to a prospective Abridge-tier customer.

---

## Phase 0 — Foundation: design system + IA shell (1 week)

**Goal:** the dashboard skeleton renders the four-page IA on warm-cream paper with the full component library available as primitives, before any real engine data exists.

### Backend / SDK

- None this phase. (Engine work resumes in Phase 1.)

### Dashboard

- Implement design tokens from [dashboard-design-system.md §Implementation notes](dashboard-design-system.md) in `frontend/app/globals.css` under a `.dashboard` selector — paper / ink / status / radius / shadow / spacing scales — so marketing and dashboard surfaces don't bleed into each other.
- Load Petrona + Inter via single Google Fonts `<link>` with `display=swap`; subset to `Petrona:ital,wght@0,400;0,500;1,400;1,500` and `Inter:wght@400;500;600`. JetBrains Mono lazy-loaded only on technical verification pages.
- Build the component shells under `frontend/components/dashboard/` matching the file structure spec exactly: Sidebar (+ ProjectSwitcher, NavSection, NavItem, UserChip), TopBar (+ Breadcrumb), PageHeader, Button (primary | secondary | ghost), Toggle, Card (+ IntegrationCard, RecommendationCard), Badge (SeverityBadge, StatusBadge), StatusIndicator (StatusDot, StatusIcon), Table, Modal, Avatar, Form primitives (Input, Select, Textarea, Radio, Checkbox, RadioOption), EmptyState, Loading (Spinner, ProgressBar), Tooltip, Icon, DocumentIcon.
- Stand up the four-page IA shell under `frontend/app/(dashboard)/`: Home, Customers, Compliance, Settings. Each page renders the Sidebar + TopBar + PageHeader + an EmptyState. No data wiring yet.
- Apply Layout Pattern A (sidebar + content) as the default; reserve Pattern B (sidebar + content + right panel) for Phase 2's review surfaces and Pattern C (modal) for Phase 4's PDF flow.

### Test gate

- Click through all four pages on warm-cream paper. Sidebar selection state, breadcrumb, hover/focus on every interactive element. Petrona renders on titles, Inter on body. No dark-mode bleed, no marketing chrome. Component library exports cleanly with type-safe variants. Lighthouse contrast passes WCAG AA on ink-on-paper.
- One screenshot per page, committed to the repo for later regression compare.

### Out of scope this phase

- Real data, real auth, animation polish beyond hover/focus, collaboration cursors, AI chat panel, mobile responsiveness (v1 is desktop-only per the design system).

---

## Phase 1 — Capture + Customers as first-class (1.5 weeks)

**Goal:** any SDK call from any customer codebase populates a Customer row on the dashboard within seconds, with auto-discover producing yellow "Setup required" rows that don't block engineering.

### Backend

- Extend `ActionRecord` with five fields via metadata blob (no schema churn): `subject_jurisdiction`, `domain`, `use_class`, `action_class`, `reason_codes`. Migrate existing rows with nulls.
- Tenant resolution: add `VeraMiddleware` mount point + `vera.tenant()` context manager + explicit `tenant=` kwarg on `@vera.gate`. Resolver picks the first non-null source in that order.
- Tenant validation: enforce `^[a-zA-Z0-9_-]{1,64}$` format; reject calls with non-conforming `tenant_id` and surface as a 4xx with a clear remediation. PHI-shape heuristic (high entropy, human-name-shaped strings) raises a warning and surfaces a dashboard banner — does not block.
- Auto-discover: first time a `tenant_id` is seen for an org, create a Customer with `status=pending_setup`, `baa_status=missing`. Decisions continue to be captured (encrypted, hash-chained, redacted). Audit PDF generation is blocked for the Customer until setup completes.
- Sandbox/production key split: `al_test_*` (synthetic data, hard redaction defaults, no BAA required, rate-limited) vs `al_live_*` (real PHI, BAA required).
- Customer CRUD endpoints: list, get, update (display name, BAA upload, jurisdictions, contact), bulk-import from CSV.

### SDK

- Ship `vera.middleware.VeraMiddleware` (FastAPI/Starlette/Django/Flask shims under `sdk/vera/integrations/`).
- Ship `vera.tenant()` context manager for background jobs.
- Extend `@vera.gate` to accept `tenant=` explicit override.
- CLI: `vera customers list`, `vera customers describe <tenant_id>` against the developer's sandbox.

### Dashboard

- **Customers page (list):** Table component, columns = name + status dot + decision count (last 30d) + BAA status + jurisdictions. Yellow row treatment for `pending_setup` ("Cleveland Clinic · Setup required · 47 decisions captured awaiting BAA"). Row click navigates to Customer detail.
- **Customer detail page:** Sidebar + content layout. Top section: name, status, BAA expiry, contact. Decisions stream below as a table (last 100 decisions, scoped to this Customer). Edit display name + complete-setup inline.
- **Add customer flow:** three paths from the [policy-engine-mvp.md](policy-engine-mvp.md) wizard — Auto-discover (info banner only, no form), Manual (form: display name, tenant_id, BAA upload, contact, jurisdictions), CSV bulk (download template, upload, preview, confirm).
- **Settings → API keys:** generate `al_test_*` and `al_live_*` keys; live key generation gated on signed BAA upload.

### Test gate

- Install the SDK in a sample agent codebase, point it at `al_test_*` sandbox, fire 50 actions across 3 distinct `tenant_id` values. Watch the Customers table populate live. Complete one customer's setup via the UI (display name + BAA upload). The pending-setup yellow turns ok-green. Try a `tenant_id` with PHI-shape characters — the warning surfaces. Try a malformed tenant_id — the call rejects with a clear error.
- CSV bulk import 25 hospitals from a sample file, confirm all appear with `pending_baa_upload`.

### Out of scope this phase

- Gate evaluation (Phase 2). Webhook delivery (Phase 2). PDF generation (Phase 4). Per-hospital posture (v2 — v1 is org-wide aggregate).

---

## Phase 2 — Gates v1 + HITL via in-app webhook (2 weeks)

**Goal:** the three medtech gates fire deterministically; HITL routing via in-app webhook works end to end including unhappy paths; reviewers see decisions in the dashboard queue and can approve/modify/reject from there as the alt channel.

### Backend

- `POST /v1/gates/evaluate` returning a `Ruling` with `effect ∈ {ALLOW, REQUIRE_HITL, BLOCK}`, `reason`, `citation`, `review_id?`, `fix_url?`, `required_role?`.
- `ClinicalScribePack` under `backend/app/packs/clinical/` implementing the three gates from [policy-engine-mvp.md §What v1 enforces](policy-engine-mvp.md):
  - **Gate 1 — new diagnosis:** if `new_diagnoses` non-empty → `REQUIRE_HITL` with `role=attending_physician`; citation HIPAA § 164.312(b) + Section 1557 § 92.210.
  - **Gate 2 — controlled substance:** RxNorm ID lookup against DEA Schedule I-V curated list (~3000 entries, vendored quarterly snapshot) → `REQUIRE_HITL` with `role=dea_licensed_physician`; citation 21 CFR 1306.04.
  - **Gate 3 — stale BAA:** if BAA expired or missing for the org → `BLOCK` with `fix_url` to BAA renewal; citation HIPAA § 164.504(e).
  - Strictest gate wins when multiple fire; precedence: BLOCK > REQUIRE_HITL > ALLOW.
- Webhook delivery service (extend `backend/app/services/webhooks.py`): exponential backoff 1m → 5m → 30m → 2h → 8h → 24h → abort, idempotency on `review_id`, configurable expiry (default 4h medtech, settable per agent action class), `review.expired` callback on expiry.
- Callback endpoint `POST /v1/reviews/{review_id}/complete`: validates `reviewer_role` matches the gate's `required_role`; rejects mismatches with 403 `reviewer_credentials_insufficient` (logged in audit trail, surfaces in PDF — "the customer attempted to attest an under-credentialed reviewer; Vera correctly rejected").
- `ApprovalRecord` persistence (extend existing): includes `client_review_started_at`, `client_review_decided_at`, `webhook_sent_at`, `callback_received_at`, `reviewed_below_threshold` flag.
- Attestation-conflict logging: second callback with the same `review_id` and a different decision is logged as `attestation_conflict` (canonical decision = first attestation).

### SDK

- `@vera.gate` synchronous Ruling handling: ALLOW → invoke + capture; REQUIRE_HITL → invoke for draft, queue Approval, raise `vera.PendingReview`; BLOCK → do not invoke, raise `vera.PolicyBlock`.
- Exception classes with structured fields: `PendingReview(review_id, expected_resolution, webhook_url)`, `PolicyBlock(reason, citation, fix_url, retryable, user_facing_reason, developer_reason)`.
- Real-time mode toggle `@vera.gate(action=..., realtime=True)` that returns `REQUIRE_DEFERRED_REVIEW` for HITL gates — action proceeds, review queued post-action, evidence flagged in PDF.
- CLI: `vera review-status <review_id>`.

### Dashboard

- **Customer detail → Decisions:** decision rows now show their gate Ruling (ALLOW / PENDING_REVIEW / BLOCKED) with the SeverityBadge component. Pending rows show webhook delivery status and time-to-expiry.
- **Review queue page** (under Compliance → Reviews): table of all decisions in `PENDING_REVIEW` state across the org. Filter by customer, by gate, by role. Click row → Pattern B layout (decision context on left, action panel on right). Approve / Modify / Reject buttons. Approval requires comment per the regulation requirements.
- **Webhook health on Settings → Integrations:** Integration card per registered webhook URL with last-delivery status, retry count, last 24h success rate. Toggle to enable/disable per endpoint.
- **Recommendation card** (AI Insights pattern) surfaces on the Review queue page when patterns appear ("3 decisions below review-time threshold from reviewer X in the last 7 days") — empty in this phase, wired up in Phase 4.

### Test gate

- Trigger each of the three gates from a sample agent against an ngrok-tunneled local webhook receiver. New diagnosis → webhook fires with the right `review_id` and role; reply with valid callback → chain extends, decision marked ALLOW with HITL evidence. Controlled substance → webhook fires with `dea_licensed_physician` requirement; reply with `MD` only → 403 rejection logged. Stale BAA → SDK raises `PolicyBlock` immediately, no webhook fired. Force the webhook receiver to 5xx → backoff schedule visible in the integration card; eventually surfaces on dashboard as `delivery_failed`.
- Use the Review queue UI as the alt channel: complete one pending review entirely through the dashboard without the customer's webhook — confirm the chain still extends correctly.
- Run real-time mode on a sample voice-agent gate; confirm latency <10ms for ALLOW, deferred-review queued for HITL.

### Out of scope this phase

- Slack channel (Phase 6 polish). Off-Vera checkpoint (Phase 3). Audit PDF (Phase 4). Posture math (Phase 4). Templates (Phase 5).

---

## Phase 3 — Evidence chain hardening: off-Vera checkpoint + offline verify (1 week)

**Goal:** kill the "what if Vera shuts down" procurement objection. The chain is verifiable without contacting Vera.

### Backend

- Daily KMS-signed checkpoint of the chain head; export to a customer-controlled S3 bucket (customer owns lifecycle; Vera cannot delete).
- OpenTimestamps anchor: every checkpoint is also anchored to the Bitcoin blockchain via OpenTimestamps' free public service. Store the proof alongside the checkpoint.
- Endpoint `GET /v1/checkpoints/{date}` returns the signed checkpoint + OpenTimestamps proof URL.
- IAM hardening: Vera staff cannot read customer PHI payloads; can read aggregate metrics, chain integrity, gate metadata. Enforced and audited.

### SDK / CLI

- `vera verify <hash>` checks against Vera's public key.
- `vera verify --offline` checks against the customer's S3 mirror + the OpenTimestamps anchor; no Vera contact required. Returns OK / FAIL with the verification trail printed.
- Document the offline-verify procedure in `sdk/docs/` so an OCR investigator could run it independently.

### Dashboard

- **Home page (early version):** chain integrity indicator — "Hash chain valid · Last checkpoint 04:00 UTC · Anchored at OpenTimestamps". StatusIndicator dot + small tabular metadata. Click expands to the last 7 checkpoints with verification URLs.
- **Customer detail → Verification panel:** verification URL + OpenTimestamps link + copy-paste-able `vera verify --offline --customer <id>` command for the customer's compliance officer.
- **Settings → Compliance → Off-Vera mirror:** S3 bucket configuration (customer provides bucket ARN + Vera IAM role to assume), test write, last successful sync timestamp.

### Test gate

- Block Vera's API at the laptop firewall. Run `vera verify --offline` against a customer S3 bucket + OpenTimestamps proof — it passes without ever contacting Vera. Tamper with one ActionRecord in a copy of the database → `--offline` verify fails with the broken link identified.
- Confirm a Bitcoin blockchain anchor lookup actually resolves for a checkpoint from yesterday.

### Out of scope this phase

- Customer S3 bucket creation tooling (customer provides their bucket — Vera writes to it).

---

## Phase 4 — Audit PDF + Compliance Posture + AI Insights (1.5 weeks)

**Goal:** the central product artifact — the HIPAA AI Audit Trail PDF — generates correctly for any Customer with captured data; the Compliance page surfaces honest posture across the six universal dimensions; AI Insights provides on-demand recommendations labeled as such (not regulatory advice).

### Backend

- ReportLab PDF generator under `backend/app/services/pdf/`. Sections in OCR's checklist order per [policy-engine-mvp.md §The PDF — design requirements](policy-engine-mvp.md):
  - Cover page (customer-white-labelable: customer logo + "Prepared for [Hospital Name]").
  - Scope of AI use (auto from agent manifest).
  - Audit controls in place (HIPAA § 164.312(b) mapping).
  - HITL evidence (counts, reviewer identities, attestation chain).
  - Demographic monitoring (Section 1557 § 92.210).
  - Workforce training (customer-attested).
  - BAA chain.
  - Technical verification appendix (hash chain head, OpenTimestamps anchor, `verify.vera.io/<hash>`).
- White-labeling: customer uploads a logo + accent color; PDF cover renders with customer chrome. Vera appears once in the technical appendix only.
- NIST AI RMF posture statement generator (separate PDF): Govern/Map/Measure/Manage mapping showing which functions Vera enforces.
- Compliance Posture math for the six universal dimensions ([policy-engine-mvp.md §Compliance Posture](policy-engine-mvp.md)): Artifact freshness (20%), HITL completion (25%), Reviewer integrity (15%), Notice delivery rate (10%), Chain integrity (20%), Workflow timeliness (10%). Each dimension has a low-volume guard — below the minimum, the dimension shows "insufficient data, see raw counts" instead of a number.
- AI Insights endpoint `POST /v1/compliance/insights`: on-demand Haiku-class call against the aggregated posture data + recent decision metadata. Returns 3-5 recommendation cards with `title`, `severity` (HIGH | MEDIUM | LOW), `quoted_source`, `description`, `suggested_action`. Labeled "recommendations not regulatory advice" in the response and on every render.

### Dashboard

- **Compliance page:** posture dimensions rendered as a 2x3 grid of cards. Each card shows the dimension name + score (or "insufficient data") + a one-line measured-fact ("947 HITL events · 947 reviewed before commit"). No bar charts, no gauges — single number with a status dot.
- **Compliance → AI Insights:** "Show insights" button → on-demand Haiku call → Recommendation cards (the [dashboard-design-system.md §Recommendation card](dashboard-design-system.md) pattern) with the severity pill, quoted source in `--paper-3` background, expand/collapse, and "Apply recommendation" CTA. "Apply" creates a task — does not auto-mutate anything.
- **Customer detail → Generate audit PDF:** Pattern C modal — choose section toggles (default: all), choose branding (Customer-white-label vs Vera-neutral), choose date range (default last 30 days), Generate → progress bar (PDF generation is ~5-15s) → download.
- **Compliance → Generated PDFs:** history table of every PDF generated, with regenerate/redownload actions.

### Test gate

- Generate a HIPAA AI Audit Trail PDF for a Customer with at least 100 captured decisions, 10+ HITL events, and a signed BAA. Open in Acrobat: cover page renders the Customer's brand, sections appear in OCR order, technical appendix's verify URL loads and validates. Generate the same PDF with Vera-neutral branding — Customer logo is replaced with a placeholder, but the Customer name remains in the body.
- Compliance page: dimensions show real scores for a Customer with enough data; show "insufficient data" honestly for a Customer with <10 HITL events.
- Click Show insights → Recommendation cards render, severity pills match the spec, "recommendations not regulatory advice" label is visible. Apply one → confirm no side-effect mutation.

### Out of scope this phase

- Per-hospital Posture (v2). Periodic obligation scheduler / reminder emails (v2). LLM polish on PDF narrative (optional flag, defer to Phase 6 if budget allows).

---

## Phase 5 — Templates + Onboarding wizard (1 week)

**Goal:** a new Vera customer can complete onboarding cold, generate their first set of organizational template skeletons, and complete one through the red-banner attestation gate.

### Backend

- Template generators (Markdown output, downloadable) per [policy-engine-mvp.md §Templates](policy-engine-mvp.md):
  - HIPAA Risk Analysis skeleton (§ 164.308(a)(1)(ii)(A)).
  - Section 1557 Nondiscrimination Policy.
  - AI Tool Inventory.
  - Workforce AI Training Module Outline.
  - AI-Assisted Care Disclosure (standing notice) — conditional sections for CA AB 489, TX TRAIGA, UT AIPA based on declared state footprint.
- Template completion guardrail: every template includes `<<REPLACE WITH YOUR ACTUAL PRACTICE>>` markers (rendered in red) and a checkbox banner: *"☐ Counsel has reviewed this document. I attest the statements reflect my organization's actual practices."* The attestation checkbox is required before sign-off; sign-off persists with timestamp + user identity.
- Wizard state persistence: 5-question answers stored on the org, used to drive template selection (e.g., declaring CA selects CA AB 489 clauses in the disclosure template).

### Dashboard

- **5-question onboarding wizard** ([policy-engine-mvp.md Appendix A](policy-engine-mvp.md)): agent type / jurisdictions / decision volume / channel / HIPAA Privacy Officer. Pattern C modal sequence with progress dots. Generates: HIPAA Risk Analysis skeleton, Section 1557 Nondiscrimination Policy skeleton, BAA draft. Persist + offer downloads.
- **Compliance → Templates section:** card grid of available templates with status (Not started / In progress / Counsel-attested). Click → Markdown editor with red `<<REPLACE...>>` markers highlighted, sticky red-banner attestation checkbox at the bottom, "Mark counsel-reviewed" button disabled until the checkbox is ticked.
- **Settings page (initial):** Integrations cards (Slack — disabled until Phase 6, generic webhook), BAA management (uploaded BAA viewer + expiry + renewal CTA), Team management (invite collaborators with role: admin / member / read-only).

### Test gate

- Run the wizard cold as a new org, answer the 5 questions, confirm the right templates generate. Try to mark a template counsel-reviewed without ticking the red banner — blocked. Tick it — sign-off persists with timestamp. Re-edit the template — sign-off resets and must be re-attested. Confirm CA jurisdiction selection produces the CA AB 489 clause in the disclosure template; UT selection produces the UT AIPA clause; deselecting both removes them.

### Out of scope this phase

- API connector for CRM → Vera sync (v2). Per-decision patient notice (v2 / EU pack).

---

## Phase 6 — Home page + polish + Slack channel (1 week)

**Goal:** the dashboard is dogfoodable end to end by a pilot Customer. The 30-second daily check has its own page. Slack ships as the alt HITL channel for solo-practitioner customers.

### Backend

- Slack channel routing for HITL (Bolt SDK): customer authorizes Vera's Slack app once per workspace; webhooks post to a designated channel with context + Approve / Modify / Reject buttons; Slack interactivity → callback equivalent to in-app webhook flow.
- Workspace-scoped install: tokens encrypted, scoped to chat:write + commands; never used for read access.

### Dashboard

- **Home page** (Vera's 30-sec check view) per [dashboard-design.md](dashboard-design.md):
  - Top: org name in `--display` size + subtitle (last activity timestamp).
  - "Things that need you" section: pending reviews (count + click → Review queue), expiring BAAs (≤30 days, click → Customer), webhook delivery failures (count + click → Settings → Integrations), templates awaiting counsel attestation. StatusIndicator dots throughout.
  - "Chain integrity" section: last checkpoint timestamp + StatusDot. Click → Phase 3's verification panel.
  - "Recent activity" section: last 20 decisions across all Customers, tabular, click row → Customer detail.
  - Empty when there's nothing to do (StatusDot ok-green only, no other chrome).
- **Loading states audit:** every action classified ≤200ms (no indicator), 200ms-2s (inline spinner, button disabled), 2-30s (progress bar with "Generating PDF (3 of 7 sections)..."). No skeleton screens.
- **Empty states audit:** every list/page with no content uses the EmptyState component — title + optional subtitle + primary CTA with right-arrow. No illustrations, no emoji.
- **Voice & copy pass** per the [dashboard-design-system.md §Voice & copy](dashboard-design-system.md) rules: full-date format with year, tabular-nums, comma separators, no abbreviation under 10K, "Customer" not "Hospital"/"Tenant", "posture" not "score", no "Welcome back", no "court-admissible"/"court-ready" (use "regulator-ready"/"evidence trail"), recommendation language is always "Consider X" / "Recommended: X".
- **Accessibility audit:** keyboard focus ring (2px ink outline at 2px offset) on every interactive element, modals trap focus + restore on close, all status indicators paired with text labels, all icon-only buttons have aria-label, color contrast verified at WCAG AA on ink-on-paper and ink-2-on-paper for body sizes.
- **Settings polish:** Integrations cards properly rendered with each integration's brand-colored logo (the one place colored icon backgrounds are allowed), domain link with `↗`, Settings + Toggle controls.

### Test gate

- Dogfood the full product end to end as a paid pilot would: install the SDK, fire 1000 decisions across 5 Customers with realistic HITL volume, route some via in-app webhook + some via Slack, generate audit PDFs for 2 Customers, complete 3 templates with red-banner attestation, run `vera verify --offline` from a different machine. The Home page reflects everything correctly with no broken states.
- Keyboard-only navigation through every page works (no mouse). Modal focus traps verified. Screen reader announces severity pills as text.
- Tab open at the Home page, simulate a 24h period with traffic — nothing crashes, the page reflects new decisions correctly.

### Out of scope this phase

- Mobile responsiveness, dark mode, customizable layout, keyboard shortcut palette (⌘K), notifications panel, charts/graphs, per-hospital posture, multi-pack composition, customer-authored policies. All deliberate per [dashboard-design-system.md §What this system deliberately doesn't do](dashboard-design-system.md) and [policy-engine-mvp.md §What v1 deliberately does not do](policy-engine-mvp.md).

---

## Parallel non-engineering tracks

These run alongside the phases, started Week 1, non-gating on v1 ship:

- **Big Law HIPAA opinion:** engagement letter signed Week 1; first counsel review of the PDF template after Phase 4 lands; opinion itself takes 3-6 months, lands ~Week 12-16. Budget $30-60K. Pull-quote becomes homepage hero.
- **NIST AI RMF mapping document:** published as a public 8-page PDF + website page by end of Phase 4.
- **BAA template + e-sign workflow:** finalized by Phase 5 so onboarding wizard can complete.
- **3 paid pilot conversations:** in progress from Phase 2 onward, target Abridge-tier Series A scribes.
- **YC application:** submitted before Phase 6.

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Webhook delivery edge cases blow up Phase 2 budget | Medium | Time-box backoff/idempotency/expiry to 3 days; defer real-time mode to later if needed |
| ReportLab PDF white-labeling doesn't render Customer logos crisply | Low | Test SVG + PNG inputs in Phase 4 dev; have a fallback monochrome rendering path |
| OpenTimestamps anchor latency (Bitcoin block confirmation ~10min-1h) trips up the verify command UX | Medium | `vera verify --offline` accepts an unconfirmed anchor with a warning ("anchor pending Bitcoin confirmation") |
| Posture dimension low-volume guard surfaces "insufficient data" for most pilot Customers | High (early) | Communicated as a feature, not a bug; the Compliance page's honesty is the point |
| Dashboard component library grows beyond the Phase 0 budget | Medium | Stub only what the next phase needs; defer Collaboration cursor, Comments, AI chat input to Phase 4-6 when actually used |
| Engine work in Phase 2 overruns the 2-week budget | High | Pre-commit to feature-flagging Slack channel to Phase 6 (already planned); cut real-time mode if needed |
| HIPAA Safe Harbor redaction defaults miss a PHI shape | Medium | Phase 1 PHI-shape heuristic catches some; Phase 2 reviewer-id validation catches others; explicit list of known shapes documented |

---

## Test gates summary (one row per phase)

| Phase | Test gate (must pass before next phase) |
|---|---|
| 0 | All four pages click through on warm-cream paper; design tokens match spec; WCAG AA contrast passes |
| 1 | 50 decisions across 3 tenants populate the Customers list live; one BAA upload completes setup |
| 2 | All three gates fire correctly; webhook unhappy paths handled; Review queue alt channel works end to end |
| 3 | `vera verify --offline` passes with Vera's API firewalled |
| 4 | HIPAA AI Audit Trail PDF generates for a real customer, opens in Acrobat, verify URL works; posture dimensions honest |
| 5 | Wizard completes cold; red-banner attestation gate blocks unattested sign-off; CA/TX/UT clauses conditional |
| 6 | Full end-to-end dogfood as a pilot Customer; keyboard-only nav; voice/copy audit clean |

---

## What this plan deliberately doesn't do

- **No "build the engine for 6 weeks then bolt on the dashboard."** Vertical slices instead — each phase ships engine + SDK + UI.
- **No design system rebuild later.** Phase 0 implements the dashboard design system in full; every subsequent phase consumes it.
- **No deferral of testability.** Every phase has a dogfoodable test gate, not just an engine spec.
- **No new pack work.** Medtech only. Lending / hiring / EU stay on the roadmap.
- **No customer-authored policies.** Vera ships the medtech pack as opinionated code.
- **No charts, gradients, marketing chrome, gamified scores, dark mode, mobile-first, ⌘K palette.** All deliberate.
- **No backwards-compatibility hacks for pre-v1 SDK shapes** — there are no v1 customers yet.

---

## Cross-reference

- [policy-engine-mvp.md](policy-engine-mvp.md) — what the engine is, what gates fire, what the PDF promises, the SDK contract, the cost model, the sales path.
- [dashboard-design-system.md](dashboard-design-system.md) — visual tokens, component library, layout patterns, voice & copy rules.
- [dashboard-design.md](dashboard-design.md) — four-page IA, screen wireframes, what's on each page.
- [policy-engine-north-star.md](policy-engine-north-star.md) — the 12-24-month destination. Every primitive in v1 is a strict subset.
- [landing-design.md](landing-design.md) — marketing surface (separate; not in v1 implementation scope).

---

# /autoplan review — Phase 1: CEO

**Mode:** SELECTIVE EXPANSION (per autoplan default).
**Status:** In progress — premise gate pending.
**Voices:** Claude subagent (independent) + Codex unavailable (degraded — `[codex-unavailable]`).

## Existing code leverage map (what already exists)

| Sub-problem | Existing code | Reuse posture |
|---|---|---|
| Hash chain + KMS signing | `backend/app/services/hashing.py`, `chain.py`, `kms.py`, `checkpoint.py`, `merkle.py` | Direct reuse; extend only for off-Vera mirror in Phase 3 |
| Policy engine + gate routing | `backend/app/services/policy_engine.py`, `routes/policies.py` | Extend with `ClinicalScribePack` in Phase 2 |
| Approvals + HITL lifecycle | `backend/app/services/approvals.py`, `routes/approvals.py` | Extend with role validation + webhook callback in Phase 2 |
| Webhook delivery | `backend/app/services/webhooks.py`, `routes/webhooks.py` | Reuse for HITL callbacks; add backoff/idempotency in Phase 2 |
| Action records | `backend/app/models/` + `routes/actions.py` | Extend with 5 new metadata fields in Phase 1 |
| Org / customer model | `routes/organizations.py`, `clerk_webhooks.py` | Extend with Customer-as-first-class entity in Phase 1 |
| SDK decorator + spool | `sdk/vera/decorator.py`, `client.py`, `spool.py`, `errors.py` | Extend `@vera.gate` with sync Ruling handling in Phase 2 |
| Redaction (PHI) | `sdk/vera/redaction.py` | Reuse; harden in production-key mode (CEO finding #7) |
| Dashboard chrome | `frontend/app/(dashboard)/`, `frontend/components/dashboard/` | Replace existing with design-system-compliant build in Phase 0 |
| Compliance reviewer dashboard | `frontend/app/compliance/`, `routes/dashboard_compliance.py` | Inform Phase 2 review queue; some screens may carry over |
| CLI | `sdk/vera/cli.py` | Extend with `verify` / `verify --offline` / `review-status` |

## Dream state delta

| Where the plan leaves us at Week 8 | 12-month north-star |
|---|---|
| Medtech pack only | Medtech + lending + hiring + EU packs; multi-pack composition |
| Org-wide Compliance Posture aggregate | Per-customer (per-hospital, per-bank) posture |
| In-app webhook + dashboard alt-channel HITL | Embedded Vera review widget; Microsoft Teams; SMS/mobile push; email magic-link |
| Customer-attested PHI tenant_id heuristic | Subject jurisdiction resolver + jurisdictional overlay engine |
| Auto-generated artifacts; templates manual | Policy authoring assistant; periodic obligation scheduler |
| Sync gate mode default, real-time mode opt-in | Drift detection + anomaly batch jobs; auditor Q&A bot |
| No charts, no per-customer trend | Posture-over-time chart on Compliance page if data is genuinely useful |
| Hardcoded review thresholds per agent class | Customer-tunable per-action + customer-tunable per-customer-of-customer |

## Implementation alternatives considered

| Approach | Time | Risk | Pros | Cons |
|---|---|---|---|---|
| **A) Intertwined vertical slices (this plan)** | 8 wk (likely 10) | Engine + UI build interlocked; risk of schedule miss | Testable after every phase; UI never crammed; matches sales cadence | Each phase requires both engineering and design context-switching |
| **B) Sequential — engine first, then dashboard** | 8 wk per MVP doc | Frontend squeezed to 2 wk at end → dies | Engine team can focus; clear handoff | No customer-visible progress for 6 weeks; UI risks; matches MVP doc but conflicts with "test after every phase" requirement |
| **C) Dashboard first (clickable prototype) then engine** | 10+ wk | Whole product is mockup for 4 wk | Visual progress; useful for sales decks | Engine work compressed; "the moat" delayed; misleading demos |
| **D) Cut to 1 capability end-to-end (e.g., new-diagnosis HITL only)** | 5 wk | Narrowest possible v1 | Fastest ship; clearest demo | Cuts the PDF (the actual sales artifact); cuts off-Vera checkpoint (the procurement objection); cuts posture; pilot won't buy |

**Chosen:** A (intertwined vertical slices). Principle P1 (completeness) + P2 (boil lakes — testability is in blast radius). Approach D is too narrow to close pilots; B and C have known failure modes.

## Premises this plan rests on (gate)

These are the foundational premises the plan inherits. The user must confirm or override at the premise gate below.

| # | Premise | Source | Confidence | Risk if wrong |
|---|---|---|---|---|
| P1 | **Medtech first** (over fintech first) | [policy-engine-mvp.md §Why medtech first](policy-engine-mvp.md) — but **conflicts with [strategy.md:200](strategy.md) "Fintech first, healthtech fast-second"** | Low — unresolved between two authoritative docs | Building the wrong vertical for the forced-buyer deadline stack (FINRA 2026, CA AB 316 are fintech-side; ship medtech and miss the buy-window) |
| P2 | **8-week MVP timeline** | MVP doc + this plan | Medium — risk register flags Phase 2 + 4 as likely overruns | Slip to 10-11 weeks; sales calls stall; YC application timing |
| P3 | **In-app webhook is the default HITL channel** | MVP doc | High | Solid premise — matches BAA-chain architecture |
| P4 | **6 universal Posture dimensions surfaced in v1 UI** | MVP doc | Medium — will read as "insufficient data" for pilots | Compliance page is mostly empty / "insufficient data" for first 5 customers; reads as Vera not working |
| P5 | **No charts in v1 (single number + status dot per dimension)** | dashboard-design-system.md §What this system deliberately doesn't do | Medium — sales pressure may collapse it | Customers ask for trends; engineering retrofits sparklines mid-Q3 |
| P6 | **OpenTimestamps Bitcoin anchor adds defensibility** | MVP doc | Low — solves a problem already 80% solved by S3 mirror | UX wart; "you anchored healthcare to Bitcoin?" objection in procurement |
| P7 | **Slack as alt HITL channel in v1** | MVP doc | Low — contradicts the Abridge-tier wedge customer | Engineering cycles spent on channel no v1 customer uses |
| P8 | **CSV bulk hospital import in Phase 1** | MVP doc onboarding paths | Low — Abridge-tier customers won't use it | ~2 days of dashboard + backend for a feature no v1 customer uses |
| P9 | **Big Law opinion is non-gating on v1 ship** | MVP doc §sales path | High but the moat artifact lands months after launch | 4-8 weeks of selling without the homepage hero quote |
| P10 | **Vertical-slice intertwined cadence > sequential** | This plan §Why intertwined | High — driven by "test after every phase" requirement | If wrong, sequential is the fallback (engine-only weeks 1-6, dashboard 7-8) |

## Phase 1 — Dual voices

### CLAUDE SUBAGENT (CEO — strategic independence)

Top 5 findings, ordered by severity:

1. **The fintech→medtech pivot is buried, not justified [CRITICAL].** Strategy.md commits to fintech first because FINRA 2026 + CA AB 316 are forced-buyer dates. The MVP doc flipped to medtech with soft reasons (network access, contacts, mapped use cases) — none of which name a Q3 2026 deadline forcing a check to clear. Two contradictory docs in the same repo. **Fix:** force a 1-pager — "If we ship medtech vs fintech in 8 weeks, which generates more revenue by Dec 2026?" Concrete logos + buyers + ACVs. If medtech still wins, update strategy.md.
2. **Intertwined vertical slices buys testability and the schedule is fiction [CRITICAL].** Phase 0 = 1 wk with zero engine work; Phase 2 = 2 wk for webhook delivery + role validation + Pattern B layout + review queue — really 3+ wk of work. Phase 4 = 1.5 wk for PDF + posture + insights + grid — really 2 wk. Risk register names the overrun but the "mitigation" is "cut real-time mode." Honest total is 9-10 wk. **Fix:** trim Phase 0 to 3 days (only the 6 components Phase 1 consumes), reallocate to Phase 2; re-plan Phase 4 as 2 weeks. Declare 9-10 weeks honestly OR cut scope.
3. **"No charts in v1" will look foolish to the first paid customer [HIGH].** Six posture dimensions as single number + status dot doesn't answer "is it improving" or "are we okay this week." Procurement-stage hospitals want a one-page printable trend. **Fix:** add a sparkline (single chart type, no axes, no labels) next to each posture number. ~8 hr of work. Keep the no-gauges, no-bar-charts rule.
4. **Big Law opinion lands Week 12-16, homepage hero depends on it [HIGH].** MVP ships Week 8. So for 4-8 weeks the homepage has no attorney pull-quote. **Fix:** (a) commission a preliminary memo or 2-page advisory letter from the same firm by Week 6 (~$8-15K); gives a "Reviewed by [Big Law] — full opinion pending Q3" quote that's honest and usable. (b) Plan two homepage states.
5. **6-dimension Posture is too clever and too generic at the same time [HIGH].** Four of six dimensions will read "insufficient data" for every pilot. A scribe vendor CEO doesn't want a 2x3 grid of universal dimensions; they want one number: "regulator-readiness 87%, here are the 3 blockers." **Fix:** v1 surfaces 1 composite + 3 named blockers. Keep 6-dim math internally. Saves ~3 days.

Additional findings:

6. Webhook unhappy path eats 24+ hours on flaky endpoints; clinical workflows can't tolerate that. Add `review.escalation` to a secondary endpoint at `expiry * 2` [HIGH].
7. PHI-shape heuristic only warns; in production it should reject the call. "Vera saw PHI and waved it through" is worse than a 4xx that breaks the customer's pipeline [HIGH].
8. No seeded sales demo tenant — every sales call needs realistic synthetic data [MEDIUM].
9. Slack channel contradicts the Abridge-tier wedge customer. Cut Slack, add email channel instead [MEDIUM].
10. OpenTimestamps Bitcoin anchor solves last-20% of "what if Vera shuts down" and adds a "you anchored healthcare to Bitcoin?" objection. Cut [MEDIUM].
11. CSV bulk import in Phase 1 — Abridge-tier customers won't use it. Cut from v1, keep in v2 [MEDIUM].

### CODEX SAYS (CEO — strategy challenge)

`[codex-unavailable]` — Codex CLI not callable in this shell. Auth probe returned AUTH_OK but binary not resolvable in subshells. Tagged single-model for this phase.

### CEO consensus table

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Premises valid? | DISAGREE — medtech-first conflicts with strategy.md; 4 other premises soft | — | N/A (single voice) — flagged for premise gate |
| 2. Right problem to solve? | CONFIRMED — wedge use case is right shape | — | N/A — single-voice CONFIRMED, low-confidence |
| 3. Scope calibration correct? | DISAGREE — 8 weeks is fiction; cut 3 features (Slack, OpenTimestamps, CSV) | — | N/A — flagged for taste decisions |
| 4. Alternatives sufficiently explored? | DISAGREE — fintech-first alternative not seriously costed | — | N/A — flagged for premise gate |
| 5. Competitive/market risks covered? | DISAGREE — 8-week defensibility not yet buyer-visible; needs preliminary attorney memo + customer logos to bridge | — | N/A — flagged for taste decisions |
| 6. 6-month trajectory sound? | DISAGREE — 5 specific regret scenarios identified | — | N/A — flagged for taste decisions |

Single critical finding from one voice = flagged regardless. With Codex unavailable, this is single-voice mode — concerns are surfaced but consensus strength is lower than dual-voice.

## Error & Rescue Registry (from CEO findings)

| Error condition | Detection | Rescue | Surface |
|---|---|---|---|
| Webhook endpoint silent >2x expiry | webhook delivery timer | POST `review.escalation` to secondary endpoint + dashboard red banner | New rule in Phase 2 — derived from CEO finding #6 |
| PHI shape detected in `tenant_id` (production key) | regex/entropy heuristic | reject call with 4xx `phi_shape_in_tenant_id` | Phase 1 — strengthen from warn-only (CEO finding #7) |
| Big Law opinion delays past Week 12 | calendar tracking | switch homepage to preliminary-memo quote | Sales/marketing track — CEO finding #4 |
| Compliance page reads "insufficient data" for >50% of dimensions on a Customer | dimension data-point check | switch UI to composite + blockers presentation | CEO finding #5 |

## Failure Modes Registry (from CEO findings)

| Failure mode | Likelihood | Blast radius | Mitigation |
|---|---|---|---|
| Phase 2 overruns to 3+ weeks | High | All downstream phases slip | Trim Phase 0 to 3 days; declare 10 weeks total honestly |
| First pilot's Compliance page is mostly "insufficient data" | High | Sales motion; customer perception of product value | Replace 2x3 grid with composite + 3 blockers (P4/P5) |
| Sales call requests trend chart; we don't have one | High | Lost deal momentum | Add posture-sparkline to Phase 4 (CEO finding #3) |
| Big Law full opinion misses Week 8 ship date | Near-certain (Big Law is slow) | Homepage has no expert quote | Preliminary memo by Week 6 (CEO finding #4) |
| Vendor's webhook endpoint flakes during a clinical pilot | Medium | Pending reviews queue for 24h; patient harm risk | Escalation rule + customer-side BLOCK guidance (CEO finding #6) |
| FINRA / CA AB 316 enforcement action drops in fintech in Q3 2026 | Medium | Wrong-vertical exposure; competitor swoops on fintech wedge | Premise gate resolves medtech-vs-fintech now, not in Q3 |

## NOT in scope (this plan, v1)

| Item | Why deferred | Phase to revisit |
|---|---|---|
| Multi-pack composition (lending, hiring, EU) | Wave 2 — Q3 2026 per MVP doc | v2 |
| Customer-authored policies / DSL | Vera authors packs as opinionated code | v3+ |
| Mobile / responsive frontend | v1 is desktop-only per design system | v2 |
| Dark mode | warm-paper-only in v1 | v2+ |
| Per-customer (per-hospital) Posture | aggregate org-wide for v1 | v2 |
| Periodic obligation scheduler (reminder emails) | none in v1 | v2 |
| ⌘K command palette | v3 once surface is rich enough | v3 |
| Notifications panel | email is the notification channel; Home banner covers urgent | v2+ |
| Auto-retry on denial | runaway-loop risk; customer's agent owns retry | not on roadmap |
| Per-decision patient notice (EU Art. 26(11)) | standing notice only in v1 (US Federal) | v2 / EU pack |
| Real-time mode HITL pre-action enforcement | post-action deferred-review only for realtime=True | v2 |
| Biometric ID two-person verification | EU Art. 14(5) — not shipped in v1 | v2+ |

## Phase 1 completion summary

- Premises identified: 10. **One critical conflict** (medtech vs fintech) blocks proceeding without user adjudication.
- Findings produced: 11 (5 critical/high, 6 medium) — all single-voice (Claude subagent only; Codex unavailable).
- Auto-decisions deferred to Final Approval Gate: 7 user-challenges and taste decisions, listed in the audit trail below.
- Mandatory outputs written: existing-code leverage map ✓, dream state delta ✓, alternatives table ✓, premises list ✓, dual-voice section ✓ (degraded), consensus table ✓ (degraded), error/rescue registry ✓, failure modes registry ✓, NOT-in-scope ✓, completion summary ✓.

**Phase 1 complete. Codex: [unavailable]. Claude subagent: 11 findings. Consensus: single-voice degraded mode — all findings flagged at premise gate or final gate. Passing to Phase 2 once premises confirmed.**

### Premise gate result

User confirmed: **Medtech first (keep plan as-is)**. Strategy.md should be updated post-ship to reflect the pivot. Logged 2026-05-21.

---

# /autoplan review — Phase 2: Design

**Voices:** Claude subagent (independent senior product designer) + Codex unavailable (degraded).

## Phase 2 — Dual voices

### CLAUDE SUBAGENT (design — independent review)

Top 4 findings (all critical/high):

1. **[CRITICAL] Onboarding wizard ships in Phase 5 — six weeks after the first user sees the product.** A new Abridge PM signs up in Week 1 and gets an empty 4-page IA shell. The 5-question wizard that drives template selection + jurisdictional clauses doesn't exist until Phase 5. First-60-seconds emotional arc: confusion → "is this it?" → tab close. **Fix:** Move the 5-question wizard *flow* into Phase 1 alongside Customers. The wizard captures jurisdictions and decision volume — which Phase 1 already needs for Customer setup. Template *generation* can stay in Phase 5. ~2-3 days reallocation.
2. **[CRITICAL] Home page ships in Phase 6 — the daily workspace is the last thing built.** Until Phase 6, the landing page is "an EmptyState on Home." Five phases (~6.5 weeks) where every test gate validates pieces but the actual product-shape is missing. Phase 3 sneaks in a chain-integrity indicator without scaffolding. **Fix:** Ship a skeletal Home in Phase 1 with three sections (Needs your attention / Chain integrity / Recent activity) wired to whatever data exists. Each subsequent phase fills its section. By Phase 6 it's polish, not assembly.
3. **[HIGH] PDF modal error/partial states are entirely unspecified.** Phase 4 describes the happy path only. Nothing on: timeout, ReportLab crash mid-render, partial-data warnings, BAA-expired block, regenerate idempotency. Generated PDFs history table mentioned with no IA placement. **Fix:** Phase 4 must spec four PDF modal states explicitly: in-flight (progress + cancel), error (timeout/crash with retry), blocked (BAA expired with deep-link fix), partial (generated with "insufficient data for section X" inline warnings). Generated PDFs history lives on Customer detail AND a roll-up on Compliance — both, because discovery paths differ.
4. **[HIGH] 2x3 Compliance Posture grid is the wrong pattern for v1 reality.** Four cells reading "insufficient data" reads as broken product, not honest product. The grid pattern assumes parity across cells; reality has two cells with signal and four without. **Fix:** v1 surfaces a composite headline ("Runtime posture: 2 dimensions measured, 4 awaiting data") + the two live dimensions as prominent cards + the four pending dimensions in a single collapsed "Dimensions awaiting data" row with raw counts. When pilots cross a dimension's minimum, it promotes to a card. The 2x3 grid becomes correct at v1.5.

Additional findings (medium):

5. Home Page is missing the Generate-PDF shortcut and the posture chip from `dashboard-design.md` spec. Add to Phase 6.
6. Review queue states (empty / 200+ / filtered-empty / claim-collision) are unspecified.
7. Wizard abandonment + SDK-traffic-already-flowing conflict is unspecified. Add resume-setup banner on Home.
8. First-PDF-generated celebration moment is silent; the *only* moment of magic deserves an in-modal confirmation, not a silent download.
9. AI Insights component appears in two different surfaces with no canonical entry-point per phase.
10. Pending-setup Customer detail layout (0 decisions) is undefined; only the populated layout is implied.
11. Cross-page nav for "compare to last month's PDF" is unspecified.
12. WizardProgress primitive is referenced but not in the Phase 0 component library.

### CODEX SAYS (design — UX challenge)

`[codex-unavailable]` — single-voice mode for this phase.

## Design litmus scorecard

| Dimension | Subagent score | Codex | Consensus | Action |
|---|---|---|---|---|
| 1. Information hierarchy | 6/10 | — | N/A | Add Generate-PDF shortcut + posture chip to Home (Phase 6) |
| 2. Missing states | 4/10 | — | N/A | Spec review queue states (Phase 2) + PDF modal states (Phase 4) |
| 3. User journey | 3/10 | — | N/A | **Move wizard flow to Phase 1; ship skeletal Home in Phase 1** |
| 4. Specificity | 5/10 | — | N/A | Spec pending-setup Customer detail; canonical AI Insights entry-point |
| 5. Design system fidelity | 8/10 | — | N/A | Hold the no-charts rule (rejects CEO finding #3 sparkline) |
| 6. Cross-page navigation | 5/10 | — | N/A | Generated PDFs in both Customer detail + Compliance |
| 7. Posture with empty dimensions | 3/10 | — | N/A | **Replace 2x3 grid with asymmetric (composite + 2 measured + 4 collapsed)** |
| **Composite** | **4.9/10** | — | — | — |

CONFIRMED = both agree. DISAGREE = models differ (→ taste decision). Missing voice = N/A. Single critical finding from one voice = flagged regardless.

## Cross-phase resonance (design ↔ CEO)

Design finding #4 (2x3 grid wrong) **confirms** CEO finding #5 (6-dimension Posture too generic). Two independent voices agree → high-confidence signal. Surfaced as theme at final gate.

Design finding #5 (hold no-charts) **disagrees with** CEO finding #3 (add sparkline). Both have valid reasons:
- CEO: customers will ask for trends; sales pressure will collapse it
- Design: charts violate the editorial-operational system; aesthetic discipline is the product

This is a real taste decision for the final gate. Note: if user picks "add sparkline," need to update dashboard-design-system.md to permit a single sparkline primitive (not a general chart license).

## Phase 2 completion summary

- 7 design dimensions evaluated, composite 4.9/10.
- 4 critical/high findings, 8 medium findings — total 12.
- Required outputs: dual voices section ✓ (degraded), design litmus scorecard ✓, cross-phase resonance ✓.
- Auto-decisions deferred to final gate: 5 (Phase 1 wizard move, Phase 1 Home skeleton, PDF modal states spec, posture asymmetric layout, sparkline-or-no-sparkline taste).

**Phase 2 complete. Codex: [unavailable]. Claude subagent: 12 findings. Consensus: single-voice degraded mode. Passing to Phase 3.**

---

# /autoplan review — Phase 3: Eng

**Voices:** Claude subagent (read actual code) + Codex unavailable (degraded).
**Test plan artifact:** [/Users/priyansh/.gstack/projects/Ad0420-Agent_Compliance/priyansh-claude-kind-pike-2e1230-test-plan-20260521-001503.md](file:///Users/priyansh/.gstack/projects/Ad0420-Agent_Compliance/priyansh-claude-kind-pike-2e1230-test-plan-20260521-001503.md)

## Scope challenge — what the eng subagent found by reading actual code

The eng subagent didn't take the plan at its word — it loaded `backend/app/services/webhooks.py`, `approvals.py`, `chain.py`, `hashing.py`, and the SDK. Three critical mismatches with the plan:

1. **Webhook delivery has no retries today.** Existing impl is fire-and-forget via `asyncio.create_task`, 5-second timeout, auto-disable after 20 consecutive failures, no persistent queue, no per-`review_id` dedupe. Phase 2 says "exponential backoff 1m→5m→30m→2h→8h→24h" — this is a rewrite + new durable queue, not an extension.
2. **Approval model is poll-based.** `approvals.py` uses `wait_for_approval` polling against `GET /v1/approvals/{id}`. No callback endpoint, no reviewer role enforcement, no timing columns. Phase 2 implies a parallel webhook-callback approval pipeline.
3. **ActionRecord has no `tenant_id` column.** Has `org_id` and `data_subject_id`. Plan's "5 new fields via metadata blob" decision poisons downstream queries: Customer detail page (filter by tenant), review queue (filter by customer), posture aggregation across domain/action_class — all become JSON containment queries at 1M actions/month.

## Phase 3 — Dual voices

### CLAUDE SUBAGENT (eng — independent review)

#### Critical
- **F1. Webhook delivery is a rewrite, not an extension.** Phase 2's 2-week budget assumes 3-4 days of webhook work; real cost is 1.5-2 weeks alone. **Fix:** pull webhook hardening into a sub-phase with a durable store (`webhook_delivery_attempts` table with `(review_id, attempt_n, next_retry_at, status)`), worker process, idempotency anchor. Re-budget Phase 2 to 3 weeks.
- **F2. Approval pipeline is poll-based; plan assumes callback-based.** Existing `Approval` model has no `client_review_started_at`, no role enforcement, no `attestation_conflict` mechanism. Plan implies a parallel pipeline without saying so. **Fix:** Pick one — (a) deprecate polling, build webhook-callback `Review` service; or (b) extend `Approval` with `kind` column and gate new behavior. Add `reviewer_credentials` table or role assertion model.
- **F3. ActionRecord metadata-blob trap.** 5 new fields in `metadata_` means JSON containment queries on every dashboard load. Plan doesn't say whether new fields hash as top-level or under `metadata_`. **Fix:** Promote `tenant_id`, `domain`, `action_class` to proper indexed columns. Keep `subject_jurisdiction` + `reason_codes` in metadata. Document hash contract explicitly.

#### High
- **F4. Tenant resolver precedence is backwards.** Plan: middleware → context → kwarg, first non-null wins. Should be: kwarg > context > middleware default. Also: contextvars don't propagate into thread-pool workers (FastAPI `BackgroundTasks`), so async middleware + decorator on worker = `tenant_id=None`.
- **F5. OpenTimestamps Bitcoin anchor has no SLA.** Free donation-supported service. 10-60min Bitcoin confirmation. Calendar servers go down. Plan's test gate ("confirm an OTS lookup resolves") works on day 1, fails the day a calendar is unreachable. **Fix:** Default off; opt-in only. Customer-S3 mirror + KMS signature already solves "what if Vera shuts down."
- **F6. PDF generation sync vs async unspecified.** ReportLab is CPU-bound, pins event-loop worker for 15s. At 30+ concurrent renders/peak hour, sync HTTP times out behind any reverse proxy gateway. **Fix:** `POST /v1/audits` returns job_id; worker process executes ReportLab; client polls.
- **F7. Posture math at scale.** Naive query at 1M actions/month is 2-5s/page-load. **Fix:** `posture_snapshots` table updated by 5-min cron; Home reads snapshot, not raw actions.
- **F8. SSRF on customer-provided webhook URLs.** Existing impl POSTs to any URL. Customer registers `http://169.254.169.254/...` → reads Vera's AWS IAM role. **Fix:** allowlist (https only, non-RFC1918, validate post-DNS). 1-day fix; Phase 2.
- **F9. Cross-org tenant_id collision.** `tenant_id="abridge"` in two orgs is fine (scoped by org_id), but misconfigured agent with wrong API key fires actions onto wrong chain. **Fix:** warn when a tenant_id value exists in another org and the action is fired with a similar-shaped name.
- **F10. KMS rotation mid-chain.** Plan adds key_id to Approval votes; checkpoints don't track key history. **Fix:** Phase 3 adds `key_id` per checkpoint; `kms_keys` history table; `vera verify --offline` consults history.

#### Medium
- **F11. Concurrent webhook callbacks race.** No row-level lock on Approval. Two reviewers approving simultaneously both pass the `status=='pending'` check. **Fix:** `SELECT ... FOR UPDATE`, unique constraint on (approval_id, approver).
- **F12. No migration plan, no rollback story.** Plan says "no backwards-compat hacks — there are no v1 customers" — fine, but mid-phase rollback within v1 is still real. **Fix:** Alembic migration per phase + feature flags (`VERA_GATES_ENABLED`, etc.) + rollback runbook.
- **F13. SDK call against org with no pack installed.** Silently evaluates ALLOW; customer thinks Vera is enforcing; PDF generates zero HITL events. **Fix:** Surface warning header on every call + dashboard banner; don't fail call, fail loud in UI.
- **F14. Future/past timestamp on callback.** Clock skew unhandled. **Fix:** reject decided_at outside `[requested_at, now()+60s]`.
- **F15. Customer S3 bucket setup is a 1-2 week customer process, not a 1-week Phase 3.** Customer's security team writes the trust policy. **Fix:** S3 push is opt-in; default is customer-downloads-checkpoints from Vera on their schedule.
- **F16. Postgres unavailable during write.** Acceptable for v1 if SDK spool is reliable, but document the failure mode. Don't promise "always available."

### CODEX SAYS (eng — architecture challenge)

`[codex-unavailable]` — single-voice mode.

## Eng dual voices — consensus table

| Dimension | Subagent | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | DISAGREE — 3 critical mismatches with existing code | — | N/A — flagged for taste decisions / scope expansion |
| 2. Test coverage sufficient? | DISAGREE — plan's gates cover ~40% of new codepaths; 25+ gaps identified | — | N/A — test plan artifact written to cover gaps |
| 3. Performance risks addressed? | DISAGREE — PDF concurrency, posture math at scale, webhook queue depth all unspecified | — | N/A |
| 4. Security threats covered? | DISAGREE — SSRF, cross-org collision, KMS rotation, concurrent races all gaps | — | N/A — flagged for taste decisions |
| 5. Error paths handled? | DISAGREE — 8+ specific error paths unspecified | — | N/A |
| 6. Deployment risk manageable? | DISAGREE — no migration plan, no feature flags, no rollback | — | N/A |

Single-voice mode (Codex unavailable). Critical findings flagged regardless.

## Architecture dependency graph

```
                    Customer codebase
                          │
                          ▼
              ┌───────────────────────────┐
              │  @vera.gate decorator     │   sdk/vera/decorator.py
              │  + tenant resolver        │   (NEW: tenant precedence — fix F4)
              └────────────┬──────────────┘
                           │ enqueue + sync gate-eval call
                           ▼
              ┌───────────────────────────┐
              │   VeraClient (sync/async) │   sdk/vera/client.py
              │   spool + background flush│
              └────────────┬──────────────┘
                           │ POST /v1/gates/evaluate (NEW)
                           │ POST /v1/actions/batch  (existing)
                           ▼
       ┌──────────────────────────────────────────┐
       │  FastAPI routes                           │
       │   /v1/gates/evaluate          (NEW)       │
       │   /v1/reviews/{id}/complete   (NEW)       │
       │   /v1/checkpoints/{date}      (NEW)       │
       │   /v1/audits                  (NEW async) │
       │   /v1/actions                 (existing)  │
       └────────────┬─────────────────────────────┘
                    │
   ┌────────────────┼────────────────────────────────────┐
   ▼                ▼                                    ▼
 ┌───────┐    ┌────────────┐                      ┌──────────────┐
 │Policy │    │ChainSvc    │ chain.py             │ Audit PDF    │
 │Engine │◄───┤build_record│ hash contract        │ worker (NEW) │
 │(EXIST)│    │+ promoted  │ (fix F3: explicit    │ ReportLab    │
 └───┬───┘    │ columns    │  top-level fields)   │ (fix F6)     │
     │        └─────┬──────┘                      └──────┬───────┘
     ▼              ▼                                    │
 ┌────────────────┐ ┌────────────┐                       │
 │ClinicalScribe  │ │ReviewSvc   │ (NEW — fix F2:        │
 │Pack (NEW)      │ │ +role check│  webhook-callback     │
 │ Gate1 newDx    │ │ +callback  │  pipeline parallel    │
 │ Gate2 ctlSub   │ │ +timing    │  to existing Approval)│
 │ Gate3 staleBAA │ └─────┬──────┘                       │
 └────────────────┘       │                              │
                          ▼                              │
                ┌────────────────────┐                   │
                │ WebhookDeliverySvc │ (REWRITE — fix F1)│
                │  durable queue     │                   │
                │  webhook_delivery_ │                   │
                │  attempts table    │                   │
                │  exp backoff       │                   │
                │  idempotency key   │                   │
                │  SSRF guard (F8)   │                   │
                └─────────┬──────────┘                   │
                          │                              │
                          ▼                              ▼
                Customer webhook URL          Customer S3 (Phase 3)
                (in-app / Slack Phase 6)      OpenTimestamps anchor (opt-in F5)

                Existing services (load-bearing, mostly untouched):
                  hashing.py, kms.py, checkpoint.py, merkle.py,
                  verification.py, spool.py, redaction.py

                NEW supporting tables:
                  webhook_delivery_attempts (review_id, attempt_n, next_retry_at)
                  posture_snapshots (org_id, computed_at, dimension_scores) — fix F7
                  kms_keys (key_id, valid_from, public_key) — fix F10
                  reviewer_credentials (review_id, role, credentials[]) — fix F2
```

## NOT in scope (eng layer)

| Item | Why | Phase to revisit |
|---|---|---|
| Multi-region failover | v1 is us-east-1 + us-west-2 multi-AZ; no active-active across regions | v2 |
| Action-record sharding | Per cost model: 100M actions/mo aggregate before sharding needed | v2/v3 |
| Audit chain re-anchoring (rebuilding from S3 mirror) | Customer-facing operation, defer to v2 | v2 |
| Native Postgres replica reads | Single primary OK at v1 scale | v2 |
| LLM extraction fallback hardening | Opt-in, off by default | v1.1 |

## Phase 3 completion summary

- 6 eng dimensions evaluated — all flagged DISAGREE with single-voice mode.
- 16 findings total (3 critical, 7 high, 6 medium).
- Required outputs: scope challenge (read actual code) ✓, dual voices ✓ (degraded), consensus table ✓, architecture ASCII diagram ✓, test diagram → test plan artifact written ✓, NOT-in-scope ✓.
- Auto-decisions deferred to final gate: 9 (webhook rewrite as own phase, approval-pipeline strategy, ActionRecord column promotion, OTS default-off, PDF async job model, posture snapshot table, SSRF guard, migration plan, KMS rotation tracking).

**Phase 3 complete. Codex: [unavailable]. Claude subagent: 16 findings + test plan artifact. Consensus: single-voice degraded mode. Passing to Phase 3.5 (DX).**

---

# /autoplan review — Phase 3.5: DX

**Voices:** Claude subagent (independent DX engineer, read SDK code) + Codex unavailable (degraded).
**Product type:** Python SDK + dashboard. Primary user: scribe-vendor engineer at Abridge-class company. Headline DX claim: "5-minute live install on every sales call."

## Phase 3.5 — Dual voices

### CLAUDE SUBAGENT (DX — independent review)

#### Critical
- **F1. `@vera.audit` vs `@vera.gate` collision with no migration story.** Shipped SDK README sells `@vera.audit` as the headline primitive (5-min quickstart). Plan only ever says `@vera.gate`. New dev pip-installs today, gets a README about `@audit`; dashboard expects `@gate` data. **Fix:** Pick one in Phase 1. Recommend `@vera.gate` is v1 primitive; `@vera.audit` becomes a thin alias for ALLOW-only pure logging with DeprecationWarning. Rewrite the SDK README before any prospect installs.
- **F2. Three init flavors with no decision tree.** `__init__.py` exports `init`, `init_async`, `init_async_awaitable`. Sales-call engineer in FastAPI uvicorn worker has to read three docstrings. **Fix:** Collapse to `vera.init(...)` that auto-detects sync vs async via `asyncio.get_running_loop()`; keep `init_async_awaitable` as explicit-await override.

#### High
- **F3. Tenant resolver fallback order is plan-side, not SDK-side, with no `doctor` to tell you which one fired.** When a record posts with the wrong tenant_id, dev has no command to ask "which resolver attributed this call?" **Fix:** Stamp `tenant_source ∈ {middleware, context_manager, explicit_kwarg}` on every ActionRecord; expose via `vera tail --json`; add `vera doctor` that lists resolvers + dumps order.
- **F4. `PolicyBlock` discipline only enforced for BAA stale.** Malformed tenant_id, no pack installed, KMS unavailable, webhook URL SSRF-blocked, callback role mismatch — all need the same `(user_facing_reason, developer_reason, fix_url, docs_url)` shape. **Fix:** Add error-discipline checklist as Phase 0 deliverable; gate every PR.
- **F5. Plan contradicts SDK's published versioning policy.** Plan says "no backwards-compat hacks — no v1 customers yet." SDK README:907 says "Breaking changes ship behind DeprecationWarning for at least one minor release." `vera-sdk` is on PyPI. **Fix:** Pick one before Phase 1 — either yank from PyPI until v1 (cleanest, recommended), or commit to deprecation shims.
- **F6. No `vera init` scaffold.** No starter `vera.config.toml`, no `.env.example`, no `vera doctor`. The 5-min demo loses 2 min to "okay let me copy-paste env vars." **Fix:** Add `vera init` (Phase 1) + `vera doctor` (Phase 2).
- **F7. Sales-call recovery paths undefined.** Headline claim "pip install → decorator → record visible in dashboard on Zoom call" breaks at: corp proxy blocks PyPI, sandbox key signup gated on email verification, middleware not wired (tenant_id null), auto-discover yellow rows must land in <3s. **Fix:** Ship `vera quickstart` in Phase 1 — single command that does pip sanity + OAuth device-code sandbox key + temp `vera.tenant("demo")` context + posts one record + opens dashboard URL.

#### Medium
- **F8. `VERA_DEV=1` is a third mode the plan ignores.** Dev (stderr sink, no key) + Sandbox (`al_test_*`) + Production (`al_live_*`) — three modes, no docs. **Fix:** Phase 1 docs: "Modes" table; `vera config show` prints active mode.
- **F9. `vera verify --offline` UX with unconfirmed Bitcoin anchor.** OCR investigator verifying a same-day checkpoint sees "anchor pending" warning, may stop. **Fix:** explicit message: "OK — chain integrity verified against S3 mirror. Bitcoin anchor pending (confirms within 1h, retry then). Does not affect chain validity."
- **F10. No documented skip-gate-for-tests escape hatch.** Scribe vendor's unit test for `commit_chart_note` hits `REQUIRE_HITL`, raises `PendingReview`, test fails. **Fix:** `vera.testing.bypass_gates()` context manager + `@vera.gate(..., test_mode_bypass=True)` kwarg.

### CODEX SAYS (DX — developer experience challenge)

`[codex-unavailable]` — single-voice mode for this phase.

## Developer journey map

| Stage | Friction | Score |
|---|---|---|
| 1. Discover | PyPI page, GitHub README. Title "vera-sdk" is unambiguous. | 8/10 |
| 2. Evaluate | README strong on `@vera.audit`, silent on `@vera.gate` and tenant resolution. Engineer sees "audit" → thinks logging, not enforcement. | 5/10 |
| 3. Install | `pip install vera-sdk` clean, extras documented. | 9/10 |
| 4. First call | Quickstart works *if* you accept defaults. No `vera init` scaffold; no `.env.example`; dev edits source. | 6/10 |
| 5. Debug first error | `vera ping` + `vera config show` exist. No `vera doctor` bundling env + network + auth + tenant introspection. | 5/10 |
| 6. Integrate in prod | Three init variants with no decision tree. Tenant resolver picks first non-null of three sources — no way to see which won. | 4/10 |
| 7. Upgrade | `@vera.audit` → `@vera.gate` is a real rename with semantic change. README + plan contradict on versioning policy. | 3/10 |
| 8. Debug in prod | `vera tail` solid. `vera review-status` covers HITL. No `vera trace <tenant_id>` for chain integrity drift. | 6/10 |
| 9. Escape hatch | Custom redactor: excellent. Custom pack: unclear. Skip-gate-for-tests: not documented. | 5/10 |

## Developer empathy narrative

> *Tuesday 9am. Zoom call with Abridge's VP of Eng. I share my terminal. He says "show me." I run `pip install vera-sdk` — that works. I run `vera init` — command not found. I run `vera config show` — okay so I need to write a `.env`. I open my editor; he watches me copy env vars from your docs site. He notices the docs say `@vera.audit` but in the call you mentioned `@vera.gate`. He asks "which one is current?" I don't know. I add `@vera.audit` because that's what the README shows. I run my script. Nothing appears in the dashboard. I open `vera ping` — that works. I open `vera tail` — empty. He says "I think we'll need more time." Call ends. I lose the deal.*

The headline DX claim ("5-min live install") cannot survive contact with a single contradiction in the docs. F1 + F2 + F6 are not three findings; they are one critical failure mode of the v1 sales motion.

## DX scorecard

| Dimension | Subagent score | Codex | Consensus |
|---|---|---|---|
| 1. TTHW | 5/10 | — | N/A — fix F1/F2/F6 to reach 8 |
| 2. API/CLI ergonomics | 6/10 | — | N/A |
| 3. Error messages | 5/10 | — | N/A — gate on F4 |
| 4. Documentation | 6/10 | — | N/A — write rewrite required after F1 |
| 5. Upgrade path | 2/10 | — | N/A — F5 unresolved |
| 6. Dev environment | 5/10 | — | N/A — F8 unresolved |
| 7. Sales-call demo | 4/10 | — | N/A — F7 unresolved |
| 8. Escape hatches | 6/10 | — | N/A — F10 unresolved |
| **Composite** | **4.9/10** | — | — |

CONFIRMED = both agree. DISAGREE = models differ. Missing voice = N/A. Single critical finding from one voice = flagged regardless.

## TTHW assessment

| Target | Reality | Gap |
|---|---|---|
| 5 min (sales-call claim) | ~20 min (full integration: middleware + sandbox key + Customer setup + tenant resolver wiring) | -15 min |
| 5 min (with `vera quickstart` per F7) | ~5 min | on target |

## DX implementation checklist

To reach TTHW ≤5 min and DX composite ≥7.5/10, the plan must add:

| Phase | Add | Source |
|---|---|---|
| Phase 0 | Error-discipline checklist (gate every PR) | F4 |
| Phase 0 | Decision: yank `vera-sdk` from PyPI until v1, OR add deprecation shims | F5 |
| Phase 1 | `vera init` scaffold (writes `.env.example`, prints next-step decorator) | F6 |
| Phase 1 | `vera quickstart` command (OAuth device-code + temp tenant + first record + opens dashboard) | F7 |
| Phase 1 | Consolidate `init` variants to one auto-detect entry point | F2 |
| Phase 1 | Rename `@vera.audit` → `@vera.gate` (alias kept with DeprecationWarning) | F1 |
| Phase 1 | Stamp `tenant_source` on every ActionRecord; expose via `vera tail` | F3 |
| Phase 1 | "Modes" table in docs (Dev / Sandbox / Prod) | F8 |
| Phase 1 | `vera.testing.bypass_gates()` context manager + `test_mode_bypass=True` kwarg | F10 |
| Phase 2 | `vera doctor` command (config + ping + middleware + resolver order + webhook URL test) | F6 |
| Phase 3 | Update `vera verify --offline` output for pending Bitcoin anchor | F9 |
| Phase 5 | Migration guide page (`@audit` → `@gate`) + SDK README rewrite | F1, F5 |

## Phase 3.5 completion summary

- 8 DX dimensions evaluated, composite 4.9/10.
- 10 findings (2 critical, 5 high, 3 medium).
- Required outputs: dual voices ✓ (degraded), DX scorecard ✓, developer journey map ✓, developer empathy narrative ✓, TTHW assessment ✓, DX implementation checklist ✓.
- Auto-decisions deferred to final gate: 4 (yank SDK or deprecation shim, rename `@audit`→`@gate`, ship `vera quickstart` + `vera init` + `vera doctor`).

**Phase 3.5 complete. Codex: [unavailable]. Claude subagent: 10 findings. DX composite 4.9/10; TTHW 20min → 5min after fixes. Single-voice degraded mode. Passing to Phase 4 (Final Gate).**

---

# /autoplan — Cross-phase themes (high-confidence signals)

A concern flagged in 2+ phases independently is a high-confidence signal. Surfacing here:

1. **"8 weeks is fiction"** — CEO finding #2 (Phase 0 too long, Phase 2 + 4 mis-scoped) + Eng finding F1 (webhook delivery is a rewrite not extension) + Eng finding F2 (approval pipeline is a parallel build). All three independently concluded the schedule is closer to 9-10 weeks. Recommendation: declare 10 weeks honestly OR cut scope (next theme).
2. **Scope can be cut without product harm** — CEO findings #9 (Slack), #10 (OpenTimestamps), #11 (CSV bulk) + Eng finding F5 (OTS no SLA) + Eng finding F15 (S3 bucket setup is a 2-week customer process) all suggest cuts. Cutting Slack, OpenTimestamps as default, CSV bulk, and customer-S3-push as default saves ~5-7 engineering days and removes 3 procurement risks.
3. **Sequencing of wizard + Home is wrong** — Design finding #1 (wizard ships Phase 5 but needed Phase 1) + Design finding #2 (Home ships Phase 6 but is the daily workspace) + DX finding F7 (sales-call quickstart). All three say: the user-visible product shape needs to be assembled earlier, not at the end.
4. **6-dimension Posture is too generic** — CEO finding #5 (4 of 6 dimensions "insufficient data") + Design finding #4 (2x3 grid wrong pattern) independently conclude the same thing. Highest-confidence finding in the review.
5. **No backwards-compat policy is contradictory** — DX finding F5 (SDK README promises deprecation shims; plan says no backwards-compat) + DX finding F1 (`@audit` → `@gate` is a real rename that needs a path). One must yield.

## Phase 3.5 → Phase 4 transition

**All four phases complete.** 11 + 12 + 16 + 10 = 49 findings across CEO, Design, Eng, DX. Single-voice degraded mode throughout (Codex unavailable). Composite scores: Design 4.9/10, DX 4.9/10. Premise gate cleared. Test plan artifact written. 5 cross-phase themes identified. Passing to Phase 4 (Final Approval Gate).

---

# Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected alternative |
|---|---|---|---|---|---|---|
| 1 | Phase 1 (premise) | Confirm medtech-first | User-gated | n/a — premise gate | User confirmed via AskUserQuestion 2026-05-21 | Fintech first / Both in parallel |
| 2 | Phase 0 | Tighten Phase 0 to design-system tokens + 6 components (Button, Card, Table, Modal, Badge, StatusIndicator) | Auto (Mechanical) | P3 pragmatic | CEO finding #2 — recovered 4 days for Phase 2 | Ship all 25 components in Phase 0 |
| 3 | Phase 0 | Add error-discipline checklist (every error has user_facing + dev + fix_url + docs_url) | Auto (Mechanical) | P1 completeness | DX F4 — gates every PR going forward | Defer to Phase 6 polish |
| 4 | Phase 0 | Add WizardProgress + sparkline-stub primitives even if unused (footprint) | Auto (Mechanical) | P5 explicit | Design F12 + future-proofing for cross-phase theme #4 | Inline-only when needed |
| 5 | Phase 1 | Promote `tenant_id`, `domain`, `action_class` to indexed columns (not metadata blob) | Auto (Mechanical) | P5 explicit | Eng F3 — JSON containment queries at 1M actions/mo would be 2-5s/page | Keep in metadata blob |
| 6 | Phase 1 | Invert tenant resolver precedence to explicit > context > middleware-default + propagate via contextvars at decorator-call time | Auto (Mechanical) | P5 explicit | Eng F4 — current order has silent-mismatch bug | Keep middleware-first |
| 7 | Phase 1 | PHI-shape heuristic rejects in production keys, warns in sandbox | Auto (Mechanical) | P5 explicit | CEO finding #7 + Eng concern — "Vera saw PHI and waved it through" is worse than 4xx | Warn-only across both |
| 8 | Phase 1 | Add `vera init` + `vera quickstart` + consolidate init flavors + rename `@audit`→`@gate` (alias kept w/ DeprecationWarning) + stamp `tenant_source` | Auto (Mechanical) | P1 completeness, P5 explicit | DX F1, F2, F3, F6, F7 — required to hit 5-min TTHW | Keep `@audit`/`@gate` split + 3 init flavors |
| 9 | Phase 1 | Move 5-question wizard *flow* into Phase 1 (template *generation* stays Phase 5) | User Challenge | n/a — escalated | Design #1 — first-60-sec experience is broken without wizard | Keep wizard in Phase 5 |
| 10 | Phase 1 | Ship skeletal Home page in Phase 1 with 3 sections; subsequent phases fill in | User Challenge | n/a — escalated | Design #2 — the daily workspace can't be the last thing built | Keep Home in Phase 6 |
| 11 | Phase 1 | Drop CSV bulk hospital import from v1 | Taste | P3 pragmatic | CEO #11 — Abridge-tier won't use it; saves ~2 days | Keep CSV; defer to v2 |
| 12 | Phase 2 | Promote webhook-delivery rewrite to dedicated sub-phase; Phase 2 budget grows to 3 weeks | User Challenge | n/a — escalated | Eng F1 — existing impl is fire-and-forget, the plan implies a rewrite + durable queue | Keep 2-wk budget; cut scope mid-flight |
| 13 | Phase 2 | Decision on approval pipeline: webhook-callback Review service parallel to existing Approval polling, gated by `kind` column | User Challenge | n/a — escalated | Eng F2 — existing model is poll-based; both options have tradeoffs | Deprecate polling entirely (riskier) |
| 14 | Phase 2 | Add SSRF guard on customer-provided webhook URLs (https + non-RFC1918 + DNS rebinding) | Auto (Mechanical) | P1 completeness | Eng F8 — security gap | Defer to v2 |
| 15 | Phase 2 | Add cross-org tenant_id collision warning | Auto (Mechanical) | P1 completeness | Eng F9 | None — no v2 reason to defer |
| 16 | Phase 2 | Add row-level lock on Review row in callback handler; unique constraint on (review_id, attestation) | Auto (Mechanical) | P5 explicit | Eng F11 — concurrent callback race | None |
| 17 | Phase 2 | Add no-pack-installed warning (don't fail call; fail loud in UI) | Auto (Mechanical) | P5 explicit | Eng F13 — silent ALLOW is worst-case false confidence | None |
| 18 | Phase 2 | Add callback timestamp validation `[requested_at, now()+60s]`; reject skew | Auto (Mechanical) | P1 completeness | Eng F14 | None |
| 19 | Phase 2 | Add `review.expired` callback + `review.escalation` to secondary endpoint at expiry × 2 | Taste | P1 completeness | CEO #6 + Eng — clinical workflows can't sit 24h | Plan-as-written 24h backoff |
| 20 | Phase 2 | Add review-queue states (empty / 200+ / filtered-empty / claim-collision) to spec | Auto (Mechanical) | P5 explicit | Design #2 sub-find | None |
| 21 | Phase 2 | Add `vera doctor` command | Auto (Mechanical) | P1 completeness | DX F6 | None |
| 22 | Phase 3 | Cut OpenTimestamps Bitcoin anchor from default; opt-in only | Taste | P3 pragmatic | CEO #10 + Eng F5 — no SLA, procurement objection, last-20% benefit | Keep as default per MVP doc |
| 23 | Phase 3 | Customer-S3-push is opt-in; default is customer-downloads-checkpoints | Auto (Mechanical) | P3 pragmatic | Eng F15 — bucket setup is a 2-wk customer process not 1-wk phase | Keep S3 push as default |
| 24 | Phase 3 | Add `key_id` per checkpoint + `kms_keys` history table | Auto (Mechanical) | P1 completeness | Eng F10 | None |
| 25 | Phase 3 | Update `vera verify --offline` output for pending-anchor case | Auto (Mechanical) | P5 explicit | DX F9 | None |
| 26 | Phase 4 | PDF generation via async job model (`POST /v1/audits` → job_id; worker pool) | Auto (Mechanical) | P5 explicit | Eng F6 — ReportLab is CPU-bound, sync HTTP times out | Sync HTTP |
| 27 | Phase 4 | Add `posture_snapshots` table refreshed every 5 min by cron | Auto (Mechanical) | P5 explicit | Eng F7 — naive query is 2-5s at 1M actions | Compute on every request |
| 28 | Phase 4 | Replace 2x3 Posture grid with asymmetric layout (composite + measured cards + collapsed pending row) | User Challenge | n/a — escalated | CEO #5 + Design #4 — high-confidence cross-phase theme | Keep 2x3 grid per design system |
| 29 | Phase 4 | Add PDF modal states explicitly: in-flight, error (timeout/crash + retry), blocked (BAA-expired + deep-link), partial (insufficient-data inline warnings) | Auto (Mechanical) | P1 completeness | Design #3 | None |
| 30 | Phase 4 | Generated PDFs history surfaces on BOTH Customer detail and Compliance | Auto (Mechanical) | P1 completeness | Design #6 | One surface only |
| 31 | Phase 4 | Sparkline chart added per posture dimension? | Taste — DISAGREE | P5 explicit (design) vs P1 completeness (CEO) | CEO wants charts; Design wants no charts. Single-voice mode, recommendation unclear. | Either default holds; surfaced at gate |
| 32 | Phase 5 | Wizard abandonment + resume banner on Home | Auto (Mechanical) | P1 completeness | Design #7 | None |
| 33 | Phase 5 | Migration guide page (`@audit` → `@gate`) + SDK README rewrite | Auto (Mechanical) | P1 completeness | DX F1, F5 | None |
| 34 | Phase 6 | Cut Slack channel from v1; add email digest channel instead | Taste | P3 pragmatic | CEO #9 — Slack contradicts Abridge-tier wedge; email has higher demand signal from compliance officer | Keep Slack per MVP doc |
| 35 | Phase 6 | Add Generate-PDF shortcut + Posture chip to Home | Auto (Mechanical) | P1 completeness | Design #5 — was in `dashboard-design.md` spec, omitted in plan | Defer |
| 36 | Phase 6 | First-PDF-generated celebration (in-modal confirmation, not silent download) | Auto (Mechanical) | P5 explicit | Design #8 — only magic moment in product | Silent download |
| 37 | Cross-phase | Add Alembic migration plan + feature flags per phase + rollback runbook | Auto (Mechanical) | P5 explicit | Eng F12 | None |
| 38 | Cross-phase | Decision: yank `vera-sdk` from PyPI until v1 OR commit to deprecation shims | User Challenge | n/a — escalated | DX F5 — plan says no backwards-compat; SDK README promises deprecation shims; contradicts | Either resolution OK |
| 39 | Marketing | Commission Big Law preliminary memo by Week 6 ($8-15K) | Taste | P1 completeness | CEO #4 — homepage hero quote can't wait 3-6 months for full opinion | Wait for full opinion |
| 40 | Marketing | Seed sales demo tenant with realistic synthetic data | Auto (Mechanical) | P1 completeness | CEO #8 | Defer |
| 41 | Schedule | Declare honest 9-10 week timeline OR cut additional scope to fit 8 | User Challenge | n/a — escalated | CEO #2 + Eng F1/F2 — high-confidence cross-phase theme | Promise 8, slip publicly |
| 42 | Strategy | Update strategy.md post-ship to reflect medtech-first pivot | Auto (Mechanical) | P5 explicit | Resolves the contradiction surfaced at premise gate | Leave the contradiction |

Total auto-decided: 32. User challenges: 7. Taste decisions: 6. (One taste decision has model DISAGREE — sparkline chart.)

---

# /autoplan — Codex second pass (Codex re-enabled)

After the user re-enabled Codex (CLI version 0.133.0, auth OK), all four phases were re-run with the Codex voice in addition to the Claude subagent. **22 new findings surfaced that the first pass missed.** Most are second-order — extensions of the user's "multi-agent reality" observation, the SDK rename's actual semantic implications, and infra cost realism.

## Codex CEO — additional findings

| # | Finding | Severity | Source |
|---|---|---|---|
| C1 | **AI scribe wedge doesn't match vendor reality.** Abridge-tier vendors sell scribe + receptionist + prior-auth + inbox + coding + triage + care navigation. v1 covers one. PDF must explicitly say "Covered workflows: chart-entry scribe only" or it creates a false-comfort artifact. | Critical | Codex CEO |
| C2 | **BAA gate is too coarse.** Treats stale BAA as org-level boolean. Real risk is service-scope drift — vendor signs BAA for scribe, later routes prior-auth PHI through Vera. Need BAA scope metadata: covered services, PHI categories, agent types, effective/amendment dates. | Critical | Codex CEO |
| C3 | **99% gross margin is fantasy at v1 scale.** Infra margin is 99%; business margin is 60-85% with founder support time, BAA redlines, regulatory escalation. Loaded $180K support hire / 10 customers = $1,500/customer/month before legal. | High | Codex CEO |
| C4 | **The moat is mostly not present at launch.** Big Law lands months later. BAA trust has no switching cost until live logs accumulate. The dangerous competitor doesn't need to be correct — just needs to announce "AI audit logs for healthcare" and pattern-match Vera as a feature. Launch moat must be narrower and concrete: signed design partners, live PHI-volume logs, hospital procurement acceptance, exact RFP language. | High | Codex CEO |

## Codex Design — additional findings

| # | Finding | Severity | Source |
|---|---|---|---|
| D1 | **Multi-agent reality surfaces in 4 dashboard places, not a new page.** Customers list adds `AI coverage` column ("1 of 3 agents covered · Scribe only"); Customer detail puts full matrix above Status (rows = agents, columns = Detected, Vera coverage, Capture, HITL gates, PDF included, Posture included); Compliance adds org-level Coverage section before Posture; Audit PDF Scope page includes matrix + blunt "This evidence covers Scribe only" line. | Critical | Codex Design |
| D2 | **Asymmetric Posture creates a new risk.** Prominent "measured" cards feel harshly graded; pending dimensions get a free pass. Separate **eligibility** from **performance**: show denominators ("Needs 10 HITL events · has 2"); don't show "9.2/10" without "2 of 6 dimensions eligible" alongside. | High | Codex Design |
| D3 | **Copy violations beyond CLAUDE.md's banned terms.** "Fully compliant", "compliant indicator", "✓ compliant" are direct violations of the Delve guardrail. Replace with "All checks passing", "OK indicator", "No current blockers". Also overreaching: "cryptographic proof", "proof-of-existence", "Trust through transparency" — use "verification evidence" / "hash-chain verification". `audit-ready PDF` borderline; safer in-app copy is "Audit PDF" or "audit evidence packet". | High | Codex Design |
| D4 | **Wizard empty state must show what's already captured.** When SDK is installed but wizard incomplete: Home banner says "SDK connected · 47 decisions captured · setup incomplete" (not "you have no data yet"). Decisions are hash-chained but excluded from posture/PDF scope until wizard completes. | Medium | Codex Design |
| D5 | **Dark mode is a false v1 concern but a real QA item.** Don't build dark mode. Do force `color-scheme: light`. Verify OS dark mode doesn't invert or degrade contrast. | Medium | Codex Design |

## Codex Eng — additional findings

| # | Finding | Severity | Source |
|---|---|---|---|
| E1 | **AI Coverage Matrix has no durable model.** Current `Agent` is `(org_id, name)` only. Add `customer_agents` table: `(customer_id, agent_id, agent_type, first_seen_at, last_seen_at, source, confidence, status)`. `agent_type` must be stamped historically on records — changing metadata later must not rewrite past compliance coverage. | Critical | Codex Eng |
| E2 | **Scoped BAA needs new tables, not a boolean.** `Organization` has no BAA model. Add `baa_agreements` + `baa_scopes` with `covered_services`, `covered_agent_types`, `effective_at`, `expires_at`, `document_uri`. Migration: backfill existing as `legacy_all_services` scope; dual-read during rollout; then scope-aware gate checks for live keys. | Critical | Codex Eng |
| E3 | **No-alias `@audit → @gate` is a real breaking release.** Existing SDK exports `audit` on PyPI (`vera-sdk` 0.3.0). README promises DeprecationWarning before breaking. With no alias: ship as **1.0.0** (semver-breaking), publish final 0.3.x with DeprecationWarning, tell existing users to pin `vera-sdk<1`, provide `vera codemod audit-to-gate` (LibCST, not regex). | Critical | Codex Eng + DX |
| E4 | **Email digest approval is an auth system, not a notification.** Existing `email.py` sends static alerts via Resend. An "Approve" link cannot be trusted by token alone (forwarded email, mailbox compromise, security scanners). Digest links open an authenticated Clerk session; approval is POST-only, CSRF-protected, role-checked, single-use/idempotent, requires comment. Token bound to (reviewer email, org, review, decision, expiry); store only hashes. | High | Codex Eng |
| E5 | **3-day Phase 0 is unrealistic.** Existing repo is shadcn-dark, not warm-paper. In 3 days: tokens + Button/Card/Badge/StatusIndicator + thin Sidebar/TopBar reskin. **Falls out:** Table real states, Modal polish + focus QA, PageHeader variants, ProjectSwitcher/UserChip/Breadcrumb quality, screenshot regression, full a11y pass. **Re-budget Phase 0 back to 5 days; Phase 2 stays 3 wk total.** | High | Codex Eng |
| E6 | **5-min posture snapshots create false eligibility windows.** Cron snapshot OK for dashboards, not gates. If BAA scope flips eligible → ineligible at 10:01, enforcement must read authoritative state immediately, not 10:00 snapshot. Dashboard shows `computed_at`; event-driven recompute on BAA/scope/review changes; cron is reconciliation only. Record eligibility epochs so reports don't retroactively reinterpret decisions. | High | Codex Eng |
| E7 | **99% margin omits fixed v1 costs.** At 5-10 customers, fixed costs dominate: multi-AZ Postgres + PITR, worker queues (PDFs/webhooks/posture), observability + log retention, KMS for PHI + envelope encryption + approvals, S3 Object Lock + 6yr retention, Resend, Clerk, Vercel/Railway, HIPAA-eligible paid tiers. Gross margin can be good at $50K+ ACV; "99%+" not credible for v1. | Medium | Codex Eng |

## Codex DX — additional findings

| # | Finding | Severity | Source |
|---|---|---|---|
| X1 | **`@audit → @gate` is NOT a rename — it's a blocking semantics change.** Current README promises background delivery, no added latency. New `@gate` is sync-blocking and raises `PendingReview`/`PolicyBlock`. Required regression test: fake `/v1/gates/evaluate` sleeps 2s; old `@audit` function returns immediately, textually migrated `@gate` must either fail latency assertion or require explicit `mode="enforce"`. Codemod cannot silently change that contract. | Critical | Codex DX |
| X2 | **Codemod must use LibCST, not regex.** Must handle `@vera.audit`, `from vera import audit`, aliases, `@async_audit(blocking=False)`, async vs sync wrapping, `action_name` → canonical `action`/`action_class`, surrounding `try/except` (code that didn't catch Vera exceptions now needs `PendingReview`/`PolicyBlock` handling), `vera.init()` mode changes (existing init registers default for audit; gate needs tenant + policy metadata). | High | Codex DX |
| X3 | **Wizard ownership split.** SDK CLI owns bootstrap only (`vera init` creates local config + sandbox key flow + prints/opens resumable dashboard URL). Dashboard owns the wizard. If developer never opens dashboard: sandbox capture works; live keys, BAA, coverage confirmation, templates remain blocked as "org setup incomplete." | Medium | Codex DX |
| X4 | **AI Coverage Matrix needs `agent_type` registration, not just `action_class`.** Action classes are a taxonomy. SDK should send `agent_type` + manifest/capabilities at `vera.init(...)` or first `@gate`. Backend emits "new agent type detected" on first `(org_id, agent_name, agent_type)`. Unknown action classes land as `unclassified`, not silently create new coverage categories. | High | Codex DX |
| X5 | **Error catalog needs 12+ classes, not the ~5 the plan implied.** Top v1 errors needing `user_facing` + `developer` + `fix_url` + `docs_url`: `missing_api_key`, `invalid_api_key`, `wrong_key_tier`, `dev_mode_active`, `init_missing`, `tenant_missing`, `tenant_invalid_or_phi`, `gate_timeout_or_network`, `policy_block`, `pending_review`, `reviewer_credentials_insufficient`, `redaction_or_spool_failure`, `unknown_agent_type_or_action_class`. | High | Codex DX |
| X6 | **Sandbox key (`al_test_*`) and `VERA_DEV=1` are separate concepts.** Don't subsume. `al_test_*` hits Vera, creates dashboard rows, supports Coverage Matrix; `VERA_DEV=1` is local stderr only, no backend, no compliance trail. Make mode precedence explicit; error if `VERA_DEV=1 + al_test_*` are both active unless intentionally forced. | Medium | Codex DX |

## Codex pass — consensus tables (now full dual-voice)

### CEO consensus

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Premises valid? | DISAGREE | DISAGREE | **CONFIRMED DISAGREE** — medtech-first + 8wk + 6-dim posture all flagged by both |
| 2. Right problem to solve? | CONFIRMED | DISAGREE — wedge mismatched to vendor reality | **DISAGREE** → user challenge: scribe wedge is too narrow; need coverage matrix to be honest |
| 3. Scope calibration correct? | DISAGREE | DISAGREE | **CONFIRMED DISAGREE** — both say cut scope (Slack, OTS, CSV) |
| 4. Alternatives sufficiently explored? | DISAGREE | DISAGREE | **CONFIRMED DISAGREE** — fintech alt not costed; coverage matrix not considered |
| 5. Competitive/market risks covered? | DISAGREE | DISAGREE | **CONFIRMED DISAGREE** — moat not present at launch; pattern-matching threat real |
| 6. 6-month trajectory sound? | DISAGREE | DISAGREE | **CONFIRMED DISAGREE** — multiple regret scenarios |

### Design consensus

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Info hierarchy | 6/10 | adds: 4-place Coverage Matrix surface | **CONFIRMED** — add Coverage Matrix to 4 places |
| 2. Missing states | 4/10 | adds: eligibility vs performance separation; wizard empty state copy | **CONFIRMED** — multiple states still unspec |
| 3. User journey | 3/10 | adds: SDK-installed-but-wizard-incomplete state | **CONFIRMED** — wizard journey needs explicit signposting |
| 4. Specificity | 5/10 | adds: copy violations beyond banned terms | **CONFIRMED** — voice/copy pass must include "Fully compliant", "cryptographic proof", etc. |
| 5. Design system fidelity | 8/10 | confirms; adds `color-scheme: light` QA | **CONFIRMED** |
| 6. Cross-page nav | 5/10 | Coverage Matrix on Audit PDF Scope page too | **CONFIRMED** |
| 7. Posture w/ empty dims | 3/10 | eligibility vs performance separation | **CONFIRMED** — asymmetric AND eligibility-first |

### Eng consensus

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | DISAGREE — 3 mismatches | DISAGREE — adds: no agent_type model, no BAA scope model | **CONFIRMED DISAGREE** — 5 architectural gaps |
| 2. Test coverage | DISAGREE — 25+ gaps | adds: @audit→@gate latency regression test | **CONFIRMED DISAGREE** |
| 3. Performance risks | DISAGREE | adds: snapshot-staleness eligibility races | **CONFIRMED DISAGREE** |
| 4. Security threats | DISAGREE | adds: email-as-auth is its own security system | **CONFIRMED DISAGREE** |
| 5. Error paths | DISAGREE | adds: 12-class error catalog | **CONFIRMED DISAGREE** |
| 6. Deployment risk | DISAGREE | adds: 1.0.0 release strategy (no alias) | **CONFIRMED DISAGREE** — needs explicit release plan |

### DX consensus

| Dimension | Claude subagent score | Codex addition | Consensus |
|---|---|---|---|
| 1. TTHW | 5/10 | wizard ownership split clarified | **CONFIRMED** — 5min after fixes |
| 2. API/CLI ergonomics | 6/10 | agent_type registration needed at init | **CONFIRMED** — adds new requirement |
| 3. Error messages | 5/10 | 12-class catalog enumerated | **CONFIRMED** — discipline + catalog |
| 4. Documentation | 6/10 | adds: 1.0.0 release notes + codemod docs | **CONFIRMED** |
| 5. Upgrade path | 2/10 | adds: LibCST codemod, semver-major release, final 0.3.x deprecation | **CONFIRMED** — concrete plan replaces "no backwards compat" |
| 6. Dev environment | 5/10 | sandbox vs VERA_DEV explicit separation | **CONFIRMED** |
| 7. Sales-call demo | 4/10 | confirms `vera init` + sandbox key OAuth flow | **CONFIRMED** |
| 8. Escape hatches | 6/10 | adds: explicit mode precedence + error on conflict | **CONFIRMED** |

## Codex pass summary

**71 total findings across both passes** (49 first pass + 22 Codex second pass).
**Full dual-voice consensus achieved.** Every concern flagged by Codex was either: (a) confirmed by Claude subagent (CONFIRMED CONSENSUS), (b) extended an earlier Claude finding with concrete schema/auth/release-strategy detail, or (c) brought a net-new dimension (multi-agent coverage, BAA scope, 1.0.0 release, email-as-auth, eligibility-vs-performance).

**Net effect on the plan:** scope expands meaningfully. The user's multi-agent observation was right and it cascades through Customer model (E1), BAA model (E2), Coverage Matrix UI in 4 places (D1), PDF Scope page (D1), agent_type SDK registration (X4), and posture eligibility computation (E6).

---

# FINAL APPROVED v1 IMPLEMENTATION PLAN

This section is the implementation-ready plan after both review passes, user adjudication, and the Merkle-exposure addition. All decisions resolved. Schedule: **11 weeks** (declared honestly; 8-week target abandoned per user override stand; +1 week for Merkle exposure surfaced from existing `backend/app/services/merkle.py` infrastructure). Replaces the "Phase 0 — Foundation" through "Phase 6 — Polish" sections at the top of this document for purposes of execution; the original is preserved above as the pre-review baseline.

## Resolved decisions summary

| # | Decision | Resolution |
|---|---|---|
| Vertical | medtech (ClinicalScribePack) | confirmed at premise gate |
| Schedule | declare 10 weeks publicly | autoplan default stood (user did not reverse) |
| Wizard placement | Phase 1 (flow) + dashboard-owned; SDK CLI does bootstrap only | autoplan default stood |
| Home page | skeletal in Phase 1, filled progressively, polished in Phase 7 | autoplan default stood |
| Posture page | asymmetric + eligibility-first (denominators visible alongside scores) | autoplan + Codex D2 |
| SDK rename | `@vera.audit` → `@vera.gate` canonically as **1.0.0** breaking release; final 0.3.x with DeprecationWarning; pin `vera-sdk<1` for laggards; `vera codemod audit-to-gate` ships in Phase 1 (LibCST) | user override + Codex E3/X1/X2 |
| SDK PyPI status | stays on PyPI; release 0.3.x deprecation patch + 1.0.0 cut | user override |
| Sparkline charts | NO (autoplan default stood) | design system holds |
| OpenTimestamps | opt-in, not default; customer-S3 + KMS is default | autoplan default stood |
| Slack channel | cut from v1; ship email digest instead with full auth (Clerk session, CSRF, single-use tokens, role check) | autoplan + Codex E4 |
| CSV bulk import | cut from Phase 1 | autoplan default stood |
| Webhook escalation | add at expiry × 2 to secondary endpoint + dashboard banner | autoplan default stood |
| Big Law preliminary memo | deferred (no budget); commission later | user override |
| AI Coverage Matrix | new — surfaces in 4 places, no 5th nav page; new `customer_agents` + `baa_scopes` tables | Codex CEO C1 + Design D1 + Eng E1/E2 |
| BAA scope tracking | new — `baa_agreements` + `baa_scopes` schema; backfill legacy as broad scope | Codex CEO C2 + Eng E2 |
| Agent type registration | new — SDK sends `agent_type` at `vera.init(...)` + first `@gate`; backend detects new types | Codex DX X4 |
| Error catalog | new — 12-class catalog with user_facing + developer + fix_url + docs_url for each | Codex DX X5 |
| Eligibility vs performance | new — posture math separates eligible-but-failing from not-yet-eligible; show denominators | Codex Design D2 + Eng E6 |
| Phase 0 budget | revert to 5 days (not 3); 3 days is unrealistic against shadcn-dark baseline | Codex Eng E5 |
| Strategy.md update | post-ship, reflect medtech-first pivot officially | autoplan default stood |
| **Merkle inclusion proofs (NEW)** | Expose existing [merkle.py](backend/app/services/merkle.py) via a route + CLI flag + per-decision evidence package attachment. Default checkpoint cadence becomes hourly for production keys (configurable). Phase 3 grows 1 → 2 weeks; total schedule 10 → 11 weeks. | User addition + grounded review of existing infra |

## Approved phase breakdown (10 weeks)

### Phase 0 — Foundation: design system + IA shell (5 days)
- Replace existing shadcn-dark frontend baseline with warm-paper design tokens in `frontend/app/globals.css` under `.dashboard` scope. Force `color-scheme: light`; verify OS dark mode doesn't invert.
- Build component shells per [dashboard-design-system.md §Implementation notes](dashboard-design-system.md).
- Wire Petrona + Inter; subset per spec.
- Stand up 4-page IA shell (Home, Customers, Compliance, Settings); apply Layout Pattern A.
- **Cross-phase deliverables (added):** Error-discipline checklist (12-class catalog mandates user_facing+developer+fix_url+docs_url on every new error path). WizardProgress primitive.
- **Test gate:** all 4 pages click through; WCAG AA contrast; screenshot baseline committed.

### Phase 1 — Capture + Customers + AI Coverage Matrix + Wizard (2 weeks)
- **Schema:** promote `tenant_id`, `domain`, `action_class` to indexed ActionRecord columns (not metadata blob). Keep `subject_jurisdiction` + `reason_codes` in metadata. Document hash contract.
- **New tables (Codex E1, E2):** `customer_agents (customer_id, agent_id, agent_type, first_seen_at, last_seen_at, source, confidence, status)` + `baa_agreements` + `baa_scopes (covered_services, covered_agent_types, effective_at, expires_at, document_uri)`.
- Tenant resolver: explicit kwarg > context manager > middleware default (inverted from MVP doc); propagate via contextvars at decorator-call time, not at flush.
- Tenant validation: format regex; PHI-shape heuristic **rejects in `al_live_*`, warns in `al_test_*`**.
- Sandbox key vs `VERA_DEV=1` are explicitly separate; error if both active unless `VERA_FORCE_OVERLAY=1`.
- API key split (`al_test_*`/`al_live_*`); live keys gated on signed BAA upload (which now stores scope metadata).
- **SDK 1.0.0 release (Codex E3, X1, X2):**
  - Ship final `vera-sdk 0.3.x` with `DeprecationWarning("@vera.audit will be removed in 1.0.0; use @vera.gate")`.
  - Ship `vera-sdk 1.0.0` with `@vera.gate` only; `@vera.audit` removed.
  - `@vera.gate` is sync-blocking with `PendingReview`/`PolicyBlock` raises — *semantic change from @audit's non-blocking best-effort*. Document explicitly.
  - Ship `vera codemod audit-to-gate` (LibCST-based; handles imports, aliases, async/sync, `action_name`→`action_class`, surrounding try/except, `vera.init()` mode updates).
  - `MIGRATION.md` documents the latency regression test pattern.
- **SDK at-init agent registration (Codex X4):** `vera.init(agent_type=...)` required; backend emits `new_agent_type_detected` event on first `(org_id, agent_name, agent_type)`.
- **CLI:** `vera init` (writes `.env.example`, prints decorator example, OAuth device-code sandbox key, opens dashboard URL); `vera quickstart` (the sales-call command); `vera doctor` (config + ping + middleware + resolver order + webhook URL test); existing `vera ping`/`tail`/`config show`.
- **Dashboard:**
  - **Skeletal Home** (3 sections, wired to whatever data exists, populated by subsequent phases).
  - Customers list with **AI Coverage** column ("1 of 3 agents covered · Scribe only").
  - Customer detail with **AI Coverage Matrix** above Status (rows = agents, columns = Detected / Vera coverage / Capture / HITL gates / PDF included / Posture included).
  - Pending-setup Customer detail layout (0 decisions) explicitly specified.
  - 5-question wizard *flow* (dashboard-owned). Wizard empty state: "SDK connected · 47 decisions captured · setup incomplete."
- **Voice & copy pass start:** add D3 violations to the banned-vocabulary list. Replace "Fully compliant", "✓ compliant" → "All checks passing", "OK indicator", "No current blockers".
- **Test gate:** 50 decisions across 3 tenants populate live; one BAA upload completes setup; AI Coverage Matrix shows on Customer detail; wizard completable; `vera quickstart` works in <5 min on a fresh machine.

### Phase 2 — Gates + HITL via webhook + email digest channel (3 weeks)
**Budget grew from 2 → 3 wk per Codex E3/F1 — webhook delivery is a rewrite, not extension.**
- **Webhook delivery rewrite:** new `webhook_delivery_attempts (review_id, attempt_n, next_retry_at, status)` table; worker process (APScheduler or Celery); exponential backoff 1m→5m→30m→2h→8h→24h→abort + escalation at expiry × 2 to secondary endpoint + dashboard banner; idempotency anchor on `review_id`.
- **SSRF guard** on customer-provided webhook URLs (https only, non-RFC1918, validate post-DNS).
- **Approval pipeline:** new `Review` service parallel to existing `Approval` polling (gated by `kind` column); both pipelines coexist for v1.
- `POST /v1/gates/evaluate` returning Ruling shape; `ClinicalScribePack` with 3 gates (new diagnosis, controlled substance via RxNorm/DEA, stale BAA — now scope-aware per `baa_scopes`).
- Callback endpoint `POST /v1/reviews/{review_id}/complete` with role validation, role-mismatch 403, timestamp validation (`[requested_at, now()+60s]`), row-level lock on Review row, unique-constraint dedupe, `attestation_conflict` logging, `review.expired` callback firing at expiry.
- **No-pack-installed warning:** call returns ALLOW with warning header + dashboard banner; PDF generation blocked until pack installed.
- **Cross-org tenant_id collision warning.**
- **Email digest channel (replacing Slack):** Resend-delivered digest; "Approve" link **opens authenticated Clerk session** (not token-only); approval is POST + CSRF-protected + role-checked + single-use + requires comment; token hashes bound to (reviewer email, org, review_id, decision, expiry).
- SDK: `@vera.gate` sync ruling handling, `vera.PendingReview` + `vera.PolicyBlock` with full 12-class error catalog (`user_facing_reason`, `developer_reason`, `fix_url`, `docs_url`).
- **Dashboard:** Review queue UI with explicit states (empty, single, many (50+ paginated), filtered-empty, claim-collision). Webhook health on Settings → Integrations.
- **Test gate:** all 3 gates fire correctly; webhook unhappy paths covered including escalation at expiry × 2; email digest approve flow works end-to-end with auth; race conditions covered.

### Phase 3 — Evidence chain hardening + BAA scope enforcement + Merkle proof exposure (2 weeks)
**Budget grew from 1 → 2 wk per user-approved Merkle exposure addition.**
- **Checkpoint cadence becomes configurable.** Default for `al_test_*`: daily. Default for `al_live_*`: hourly (so per-decision Merkle proofs are available within ≤1h of a decision). KMS-signed at every cadence.
- Checkpoints exported to customer-controlled S3 (default is **customer downloads** from Vera; S3 push is opt-in per Eng F15).
- OpenTimestamps Bitcoin anchor on the Merkle root: **opt-in only, not default**. Async write; "anchor pending" surface.
- KMS rotation tracking: `key_id` per checkpoint, `kms_keys` history table, offline verify consults history.
- **BAA scope enforcement at gate time:** gate reads `baa_scopes` authoritative state immediately, not posture snapshot. Eligibility epochs recorded so reports don't retroactively reinterpret decisions.
- **Merkle inclusion proofs surfaced (NEW — uses existing [merkle.py](backend/app/services/merkle.py)):**
  - **New route:** `GET /v1/records/{record_id}/merkle-proof` — locates the checkpoint window the record falls into, reconstructs the tree via `build_tree_from_records()`, generates the proof via `MerkleTree.get_proof()`, returns `{proof: MerkleProof.to_dict(), checkpoint: {root, kms_signature, key_id, signed_at, opentimestamps_proof?}}`. Returns 409 `checkpoint_pending` if the record's window hasn't been checkpointed yet (with retry-after header).
  - **CLI:** `vera verify --merkle-proof <file.json>` runs the existing `verify_proof()` against the file's leaf + siblings + root, then verifies the KMS signature over the root using the customer S3 mirror's public key history. Works offline like `vera verify --offline`.
  - **Per-decision evidence package:** each on-demand per-decision evidence PDF embeds the corresponding `proof.json` as a PDF file attachment. The PDF text includes a one-line verification command: `vera verify --merkle-proof proof.json`.
  - **Audit PDF Scope page:** adds a sentence — "Each decision in this evidence packet has an attached Merkle inclusion proof verifiable against checkpoint root `<short hash>` (anchored at `<timestamp>`)." No change to the per-decision PDF format beyond the attachment.
  - **Selective disclosure capability:** an Abridge-to-Cleveland-Clinic export route can produce a slice — the 200 Cleveland Clinic records + their Merkle proofs against the relevant checkpoints — without exposing other customers' records. v1 ships this as a CLI command (`vera evidence-export --customer <id> --since <date>`); UI surface is v1.1.
  - **Big Law opinion brief gets one sentence:** "Vera produces Certificate Transparency-style Merkle inclusion proofs for individual records, in addition to the linear hash chain."
- **Test gate:** offline verify passes with Vera firewalled; KMS rotation mid-chain verifies; OTS calendar-unreachable graceful failure; BAA scope flip at 10:01 enforces at 10:01 (not at next snapshot). Merkle proof generated for an arbitrary record verifies via `vera verify --merkle-proof` offline; tampered proof rejects; tampered leaf rejects; mismatched root rejects. Selective-disclosure CLI produces a Cleveland-Clinic-only export that verifies without any other customer's records.

### Phase 4 — Audit PDF + Compliance Posture (asymmetric + eligibility-first) + AI Insights (2 weeks)
**Budget grew from 1.5 → 2 wk per Codex E5/F6.**
- **PDF async job model:** `POST /v1/audits` → job_id; worker pool (max-concurrent cap); ReportLab renders off the request thread.
- **PDF Scope page now mandatorily includes AI Coverage Matrix + blunt scope line** ("This evidence covers Abridge Scribe only. Receptionist and prior authorization workflows are excluded").
- White-label PDF cover with customer logo (SVG/PNG); Vera-neutral fallback.
- **PDF modal states:** in-flight (progress + cancel), error (timeout/crash + retry + support copy), blocked (BAA scope-expired with deep-link fix), partial (insufficient-data inline warnings).
- NIST AI RMF posture statement generator (separate PDF).
- **Posture math (Codex E6 + D2):** 6 universal dimensions with low-volume guards. Asymmetric UI: composite headline + 2-3 measured-and-eligible dimensions as prominent cards (with raw denominators) + remaining as collapsed "Not yet eligible" row with thresholds ("Needs 10 HITL events · has 2"). Score never shown without eligibility denominator. `posture_snapshots` table refreshed every 5 min (dashboard only); **gates always read live state**.
- AI Insights endpoint `POST /v1/compliance/insights` (Haiku-class, on-demand, labeled "recommendations not regulatory advice").
- **Dashboard:** Compliance page now shows org-level Coverage section before Posture ("Runtime posture covers 1 of 3 active agents"). Generate PDF modal (Pattern C). Generated PDFs history surfaces in **both** Customer detail and Compliance roll-up.
- **First-PDF celebration moment:** in-modal confirmation, not silent download.
- **Test gate:** PDF generates for a real customer; verify URL works; asymmetric Posture renders honestly; eligibility denominators visible; AI Insights respect no-side-effect Apply.

### Phase 5 — Templates + Wizard generation (1 week)
- Template generators (HIPAA RA skeleton, Section 1557 NDP, AI Tool Inventory, Workforce Training Outline, AI-Assisted Care Disclosure with CA/TX/UT conditionals).
- Red-banner attestation gate; re-edit resets attestation.
- Wizard *generation* (flow already in Phase 1) — completes templates from wizard answers.
- Wizard abandonment + SDK-traffic conflict: resume banner on Home until complete.
- **Settings polish:** BAA management surfaces scope metadata; team management.
- **Test gate:** wizard completable cold + resumable; templates generate; red-banner blocks unattested sign-off; CA/TX/UT clauses conditional.

### Phase 6 — Home polish + remaining polish (1 week)
- Fill the skeletal Home page from Phase 1 with all sections + interactions.
- Generate-PDF shortcut + Posture chip on Home (per dashboard-design.md spec).
- Loading states + empty states audit.
- **Voice & copy pass:** purge banned + Codex D3 violations ("Fully compliant" → "All checks passing", "cryptographic proof" → "verification evidence", `audit-ready PDF` → "Audit PDF" or "audit evidence packet").
- Accessibility audit (keyboard focus, modal focus trap, WCAG AA).
- `color-scheme: light` enforcement + OS-dark-mode QA verification.
- **Test gate:** full end-to-end dogfood; keyboard-only nav; voice/copy audit clean.

### Cross-phase parallel tracks (start Week 1)
- **Big Law engagement letter signed** (preliminary memo deferred per user override; full opinion targets 3-6mo later). Brief now includes the Merkle-proof + Certificate-Transparency sentence so the opinion covers both structures from the start.
- **NIST AI RMF mapping document** published by Phase 4.
- **BAA template + e-sign workflow** finalized by Phase 5; now supports scope metadata.
- **Strategy.md update** post-ship to reflect medtech-first pivot.
- **3 paid pilot conversations** from Phase 2.
- **`vera-sdk 0.3.x` deprecation patch on PyPI** during Phase 1.
- **`vera-sdk 1.0.0` cut + PyPI release** at end of Phase 2.

## Honest cost / margin restatement

Per Codex E7: replace "99% gross margin" with **"99% infra margin; service-adjusted v1 gross margin 60-85% during pilot phase."** Don't tell investors 99% — the next question exposes the model. Price with paid implementation, strict support boundaries, templated "not legal advice" responses.

## Final Phase 4 — Gate cleared

**All 71 findings adjudicated.** All taste decisions resolved per user overrides + autoplan defaults where unchallenged. All Codex consensus items incorporated (4 critical from Codex × 4 phases). User-approved Merkle exposure added in Phase 3 (uses existing `backend/app/services/merkle.py`; adds 1 route + 1 CLI flag + 1 PDF attachment + 1 selective-disclosure CLI). Schedule honest: **11 weeks**. SDK release strategy concrete: 1.0.0 breaking + codemod. Multi-agent reality addressed via AI Coverage Matrix + scoped BAA. The plan is implementation-ready.

Suggested next step: open a PR for this plan + the paired test plan, then begin Phase 0.

---

# Decision Audit Trail — addendum

| # | Phase | Decision | Classification | Principle | Rationale | Rejected alternative |
|---|---|---|---|---|---|---|
| 43 | Phase 3 | Surface Merkle inclusion proofs (route + CLI + PDF attachment + selective-disclosure CLI). Checkpoint cadence becomes configurable; default hourly for `al_live_*`. Phase 3 grows 1→2 wk; total 10→11 wk. | User addition + grounded review | P1 completeness + P3 pragmatic | merkle.py already exists; cost is exposure only (~1 wk). Procurement-objection-killer for "prove decision X without contacting Vera"; selective disclosure enables BAA-chain trust (Cleveland Clinic verifies its 200 records without seeing other hospitals'); Big Law opinion gets stronger via CT precedent. | Build Merkle from scratch (2-3 wk); defer to v1.5 (loses procurement upgrade + selective disclosure capability) |






