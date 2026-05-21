# Vera Dashboard — Design

**The UI for Vera's customer-facing dashboard.**
**Last updated:** 2026-05-19 (with AI-assisted Match Review + Customer terminology)
**Pairs with:** [policy-engine-mvp.md](policy-engine-mvp.md), [DESIGN.md](DESIGN.md)
**Inherits visual system from:** [DESIGN.md](DESIGN.md) (Petrona display, Inter
body, warm-cream `#FEFAF3`, no emerald, editorial register)

---

## Premise — who opens this dashboard

The dashboard is a **Tier-3 conduit-tier** artifact (per
[policy-engine-mvp.md](policy-engine-mvp.md) and
[policy-engine-north-star.md](policy-engine-north-star.md) chain analysis).
Its user is the compliance officer or engineering lead at Vera's direct
customer — Abridge, Suki, Ambience, DAX, etc.

**Not the dashboard's user:** the customer (the audit target — hospital,
bank, employer), the reviewer (practitioner, loan officer, recruiter),
the affected person (patient, applicant, candidate), or the regulator.
They each consume different artifacts (PDF, in-app review prompt,
standing notice, audit submission) through the chain.

Six jobs the dashboard supports, ranked by frequency:

| Frequency | Job | Trigger |
|---|---|---|
| Daily (30-sec check) | Verify nothing's broken | Habit |
| Weekly | Investigate stuck reviews / expiring BAAs | Email alert |
| ~2-5x/month | Generate audit PDF for a specific customer | Procurement request |
| Quarterly | Refresh NIST AI RMF posture; re-attest org docs | Calendar reminder |
| Monthly | Onboard new customers | Sales pipeline |
| Rarely | Debug a specific decision | Customer complaint / regulator inquiry |

The UI surfaces the top 3 jobs in the first second of opening the page;
the rest are reachable in 2 clicks maximum.

---

## The multi-tenant model — customers are first-class

Vera's customer (Abridge) has many customers (hospitals in medtech; banks
in lending; employers in hiring). The audit PDF is generated
**per-customer**. The BAA / DPA is per-customer. The reviewer roster is
per-customer. The notice attestations are per-customer.

**The customer is the audit target** — the entity facing direct
regulatory liability. Making it a first-class entity in the UI mirrors
the data model.

Terminology note: throughout the UI, "Customers" means *your customers*
(the audit targets you serve). Unambiguous in context because the user
is always logged in as their own org. In medtech, your customers are
hospitals; in lending, banks; in hiring, employers. The data model is
generic.

### Data model

```
Vera Org (Abridge)
├── Agents (org-wide configuration)
│   ├── abridge-scribe v3.2.1
│   ├── abridge-voice  v2.1
│   └── abridge-claims v1.0
│
├── Customers (the multi-tenant first-class concept)
│   ├── Cleveland Clinic
│   │   ├── BAA (signed Mar 12, 2026 · expires Jun 2027)
│   │   ├── Reviewers (derived from actual review callbacks)
│   │   ├── Patient/applicant notice attestations (per subject_id)
│   │   ├── Decisions stream (scoped to this customer)
│   │   └── Generated audit PDFs (history)
│   ├── Mayo Clinic
│   ├── Stanford Health
│   └── ... [many more]
│
└── Compliance (org-wide attestations)
    ├── HIPAA Risk Analysis (counsel-attested)  [medtech pack]
    ├── Section 1557 Nondiscrimination Policy   [medtech pack]
    ├── AI Tool Inventory
    ├── Workforce AI Training records
    ├── NIST AI RMF Posture Statement
    └── Standing Notice Templates (per-jurisdiction)
```

Alternative models considered and rejected:

- **Customer as a tag on decisions/artifacts** — makes the customer
  second-class; per-customer config awkward; PDFs feel like filtered
  exports.
- **Customer as a separate Vera org** — breaks the BAA chain (the audit
  target doesn't know Vera exists; making them log in violates the
  Subcontractor-BA model).

The first-class nested model is the only one that matches the chain
architecture.

### How customers get into Vera (three paths, none required)

Vera doesn't auto-detect customers from agent payloads. The org attests
each call's customer via middleware (default), context manager, or
explicit tag. See [policy-engine-mvp.md](policy-engine-mvp.md) for SDK
patterns.

The wizard offers three explicit paths at signup. None is required:

| Path | Best for | UI |
|---|---|---|
| **Auto-discover** (the default — lowest friction) | Engineering-led teams who want zero pre-setup; "install SDK and watch customers populate" | Wizard skips customer setup; first SDK call with a new tenant_id auto-creates placeholder; org completes setup later |
| **Manual** (1-5 known customers) | Compliance-led teams wanting to add the first few customers proactively | Customers page → "+ Add customer" → form (display name, tenant_id, BAA upload, contact email, jurisdictions) |
| **CSV bulk** (5+ customers from CRM) | Compliance teams wanting to pre-populate the full list before traffic flows | Customers page → "+ Bulk import" → CSV template download + upload + AI-assisted match review |

Paths interoperate. A team using auto-discover can later bulk-import a
CSV; matching tenant_ids update existing placeholders rather than
creating duplicates. The Match Review screen (described below) handles
the case where IDs differ.

### Why we keep CSV bulk upload (despite auto-discover being the default)

Auto-discover handles the engineering path elegantly. But three real
scenarios warrant a CSV path alongside it:

1. **Compliance officer pre-knowledge.** They know all 50 customers on
   day 1; they want them visible in Vera on day 1 (with BAAs attached)
   rather than trickling in reactively.
2. **The "47 decisions awaiting BAA" purgatory.** Without pre-population,
   decisions accumulate in pending-state while the org races to complete
   setup. With CSV upload, the BAA is attached before traffic flows;
   zero purgatory.
3. **Tenant_id → display name mapping.** Internal IDs (`hosp_8h2nf_v2`)
   read awful on the dashboard. CSV lets the org pre-map IDs to display
   names so the dashboard reads cleanly from the first decision.

Auto-discover is the default. CSV is the escape hatch. Both ship in v1
because they serve different (legitimate) workflows.

### CSV template

```csv
tenant_id,display_name,primary_contact_email,jurisdictions,notes
cleveland_clinic,Cleveland Clinic,ann.berg@cc.org,"US-FEDERAL,US-OH",
mayo_clinic,Mayo Clinic,proc@mayo.edu,"US-FEDERAL,US-MN",
stanford_health,Stanford Health,proc@stanford.edu,"US-FEDERAL,US-CA",
```

**Partial commit on errors.** If 50 rows uploaded and 3 have validation
errors, 47 are committed and 3 surface as a downloadable error CSV
("here's what failed and why"). Not all-or-nothing.

### AI-assisted automatching (when CSV meets auto-discovered placeholders)

This is the case the user flagged: customer has been running the SDK for
two weeks, has 8 auto-discovered placeholders with cryptic tenant_ids
(`hosp_8h2nf`, `cc_main`, `mayo_4k2nf`, etc.). They now upload a CSV
with 50 customer entries that use clean tenant_ids (`cleveland_clinic`,
`mayo_clinic`, etc.). The IDs don't match.

Vera runs a three-pass match algorithm on CSV upload:

1. **Exact tenant_id match** (deterministic). CSV row with
   `tenant_id="cleveland_clinic"` matches a placeholder with the same ID.
   → Auto-applied, no review needed.

2. **Fuzzy tenant_id match** (deterministic, Levenshtein + substring).
   `cleveland_clinic` ≈ `clevland_clinic` (typo) → high-confidence
   suggestion.

3. **AI-assisted fuzzy match** (Haiku-class LLM, on-demand at upload
   time). Vera sends the LLM each unmatched placeholder + all CSV rows
   + context (tenant_id strings, agent traffic patterns, contact email
   domains, decision timestamps, jurisdictions). LLM returns suggested
   matches with confidence + reasoning.

Cost: ~$0.02-0.05 per CSV upload event (Haiku-class, batch).

### The Match Review screen

```
┌─ Bulk import: 50 customers from CSV ──────────────────  × ┐
│                                                            │
│   We matched your CSV against your existing customers.     │
│                                                            │
│   ✓ 38 will be created (no existing match)                 │
│   ⚠  8 matched to auto-discovered placeholders             │
│   ✗  4 had errors — [ Download error CSV ]                 │
│                                                            │
│   ──────                                                   │
│                                                            │
│   APPROVE MATCHES                                          │
│                                                            │
│   ●  hosp_8h2nf  →  Cleveland Clinic                       │
│      ▸ High confidence                                     │
│      Match reason: contact email domain matches            │
│      ann.berg@cc.org; auto-discovered customer had 482     │
│      decisions after Cleveland Clinic's stated onboarding  │
│      date in CSV.                                          │
│      [ ✓ Approve match ]  [ ✗ Reject — keep separate ]     │
│                                                            │
│   ●  cc_branch_2  →  Cleveland Clinic Northeast            │
│      ▸ Medium confidence                                   │
│      Match reason: tenant_id "cc_" prefix; CSV contact     │
│      email pattern aligns.                                 │
│      [ ✓ Approve match ]  [ ✗ Reject — keep separate ]     │
│                                                            │
│   ?  mayo_4k2nf  →  ?                                      │
│      ▸ Ambiguous — two possible matches in CSV             │
│      ○ Mayo Clinic                                         │
│      ○ Mayo Health Group                                   │
│      [ Pick one ]  [ Skip — keep separate ]                │
│                                                            │
│   ──────                                                   │
│                                                            │
│   ●  hosp_uda_2  →  no CSV match found                     │
│      Auto-discovered placeholder; no obvious CSV row.      │
│      [ Keep as separate customer ] [ Archive ]             │
│                                                            │
│   ──────                                                   │
│                                                            │
│   [ Apply matches + create the rest ]                      │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Why this works

- **One-click approval** for high-confidence matches — most matches are
  this case
- **Explicit ambiguity surfacing** when multiple matches are plausible
- **Reasoning shown** for every suggested match (the LLM's "why" is
  visible — auditable, not magic)
- **Manual override always available** ("Reject" / "Keep separate" /
  "Skip" / "Archive")
- **No silent matches** — Vera never merges placeholders into CSV rows
  without explicit user approval. Wrong matches are recoverable; silent
  data corruption is not.

### What if the customer disapproves a match?

The auto-discovered placeholder stays as a separate customer. Its
decisions remain under its cryptic tenant_id. The CSV entry creates a
NEW customer.

Two customers, two BAAs, no data linking. This is correct: the customer
explicitly said "don't merge these." Vera respects the call.

Later, the customer can manually merge from the Customer detail page
("Merge with another customer" admin action — v1 ships this for the
typo / mismatch edge case).

### When does the LLM call happen?

Only at CSV upload time. Not at gate-firing time. Not on every dashboard
load. The customer triggers the LLM call by uploading a CSV; one batch
analysis runs; result surfaces in the Match Review screen.

If the LLM call fails or times out, Vera falls back to deterministic
matching only (exact + fuzzy). The user sees: "AI-assisted matching was
unavailable. Matches below are based on exact ID match only." No
silent degradation.

### Auto-discovered customers (when SDK sees an unknown tenant_id)

If the org's app calls a gate with a `tenant_id` that Vera hasn't seen
before, Vera **auto-creates a placeholder customer** with
`status=pending_setup`. The org sees this on the dashboard as a yellow
row:

```
●  cleveland_clinic                                              ← tenant_id shown
   Setup required · 47 decisions captured awaiting BAA
   [ Complete setup ]
```

Clicking "Complete setup" opens an inline form: set display name, upload
BAA, choose jurisdictions. Once complete, the row turns green and PDF
generation unblocks.

This is the "auto-discover + complete-to-enforce" pattern. Engineering
can integrate Vera on day 1 (just pass `tenant_id`); compliance fills in
customer metadata on day 2-7. Decisions in between are captured
(encrypted, hash-chained, redacted) but PDF generation is blocked for
that customer until setup completes.

---

## Information architecture — 4 nav items

Considered 8 pages; collapsed to 4. Every nav item must justify its
existence:

| Page | Why it exists | Answers |
|---|---|---|
| **Home** | Daily 30-second check + the procurement shortcut | "Is everything OK?" + "Generate me a PDF right now" |
| **Customers** | The multi-tenant core; every customer-scoped action lives here. ("Customers" means *your* customers — the hospitals, banks, or employers your AI serves. Unambiguous in context because you're logged in as your own org.) | "Show me Mayo Clinic specifically" |
| **Compliance** | Org-wide attestations and templates | "What docs do we have on file?" |
| **Settings** | Configuration: agents, API keys, team, billing, branding | "Set things up" |

### What was cut and why

- ❌ **Decisions** as a separate page — they live inside each customer
  (debug a decision in the context of its customer); a "Recent activity"
  snippet on Home covers cross-customer glance
- ❌ **Reviews queue** as a separate page — stuck reviews surface in Home's
  "Needs your attention"; reviewers live under each customer
- ❌ **Agents** as a separate nav item — they're configuration (Settings)
  with a brief reference on Home
- ❌ **Audit logs viewer** as a separate page — the audit PDF *is* the audit
  log artifact; raw exports are an advanced action inside each customer

Four nav items. Each is a noun the user already has in their head. No
invented terminology.

---

## Visual system (inherited from DESIGN.md)

- **Surface:** `#FEFAF3` warm cream
- **Card surface:** `#F5EFE3` (paper-2)
- **Primary ink:** `#1F1610` warm near-black
- **Secondary ink:** `#57514D` warm muted gray-brown
- **Status dots:** olive `#3E5C3B` for OK · brick `#7A2E1F` for urgent ·
  ink-3 (45% opacity ink) for neutral
- **Display type:** Petrona 400 — page titles only ("Abridge", "Customers",
  "Cleveland Clinic"). 28-56px depending on hierarchy.
- **Body type:** Inter 400 — paragraph text, table cells
- **Section headers:** Inter 12px, weight 600, tracking 0.10em, uppercase —
  the small-caps editorial pattern from DESIGN.md
- **Numbers:** Inter with `font-feature-settings: "tnum"` (tabular-nums)
- **Spacing:** 8px base. Dashboard density allows 32-48px between sections
  (DESIGN.md says "dashboard is allowed slightly more chrome")
- **Borders:** 1px rgba(31,22,16,0.14) between rows; no outside edges on
  tables
- **Shadows:** soft `--shadow-1` on cards; `--shadow-2` on hover/lift
- **No emerald.** No mono. No purple gradients. No 3-column iconed-circle
  feature grids.

---

## Screen 1 — Home

The 30-second check + the procurement shortcut. If everything is green and
nothing needs attention, the user spends 10 seconds here and closes the
tab. That's the goal.

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│                                                                    │
│   Abridge                                                          │
│                                                                    │
│   ● 12 customers · all chains valid · last verified 30s ago        │
│   Compliance posture: 9.2 / 10  →                                  │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   NEEDS YOUR ATTENTION                                             │
│                                                                    │
│   ●  Stanford Health · BAA expires in 18 days       [ Renew ]     │
│   ●  Cleveland Clinic · 3 reviews pending >4 hrs    [ Investigate]│
│   ●  NIST AI RMF posture · refresh due in 7 days    [ Refresh ]   │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   GENERATE AUDIT PDF                                               │
│                                                                    │
│   For        [ Cleveland Clinic                       ▾ ]          │
│   Period     [ Last 30 days                           ▾ ]          │
│                                                                    │
│                                       [  Generate  →  ]            │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   RECENT ACTIVITY                                  See all →       │
│                                                                    │
│   2:47 PM   abridge-scribe     Cleveland Clinic                    │
│             Dr. Smith approved with modifications                  │
│                                                                    │
│   2:43 PM   abridge-scribe     Mayo Clinic                         │
│             Dr. Adams approved                                     │
│                                                                    │
│   2:41 PM   abridge-voice      Cleveland Clinic                    │
│             Triage escalated to RN                                 │
│                                                                    │
│   2:38 PM   abridge-scribe     Stanford Health                     │
│             Dr. Lee modified controlled-substance order            │
│                                                                    │
│   2:35 PM   abridge-scribe     Mayo Clinic                         │
│             Dr. Adams approved                                     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### Why every element exists (Home)

| Element | Reason |
|---|---|
| "Abridge" (org name, Petrona) | Identity anchor for multi-account users; the page belongs to your org, not Vera |
| Status line | Answers "is everything OK?" in one sentence. If yes, the user closes the tab. |
| "Compliance posture: 9.2 / 10 →" | Single-glance posture indicator; click for full Compliance page breakdown. Deliberately called "posture" not "score" — see Compliance page section. |
| "Needs your attention" | Surfaces 2-5 things needing action. Empty state: "Nothing right now ✓" — the goal state. |
| "Generate audit PDF" panel | The most common ad-hoc workflow elevated to home. Procurement asks 2-5x/month; this puts the answer one click from login. |
| "Recent activity" (5 rows) | Peripheral awareness across all customers. No action required; just situational. |

### What's missing on purpose

- No charts, no graphs
- No "compliance score" gauge (vanity metric; regulators care about evidence, not scores)
- No marketing copy ("welcome back!")
- No "tips" or "what's new"
- No integration suggestions

The compliance officer wants to *leave* the dashboard, not be entertained.

---

## Screen 2 — Customers list

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Customers                                                        │
│                                                                    │
│   12 customers · 2,847 decisions last 30 days                      │
│                                                                    │
│                        [ + Add customer ]   [ Bulk import (CSV) ]  │
│                                                                    │
│   CUSTOMER                BAA          30D       HITL    LAST PDF │
│                           EXPIRES      DECISIONS RATE             │
│   ────────────────────────────────────────────────────────────── │
│   ● Cleveland Clinic      Jun 2027        482     33%     12d ago │
│   ● Mayo Clinic           Apr 2027        671     28%      3d ago │
│   ● Stanford Health       Jun 2026 !      389     31%     18d ago │
│   ● Boston Hospital       Dec 2027        412     29%      5d ago │
│   ● Houston Methodist     Aug 2027        298     35%      7d ago │
│   ● Mass General          Mar 2028        201     27%     11d ago │
│   ● Johns Hopkins         Nov 2027        184     34%      9d ago │
│   ● UCLA Health           Feb 2028         98     30%     22d ago │
│   ● Cedars-Sinai          Oct 2027         76     32%     15d ago │
│   ● ...                                                            │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Specific names like "Cleveland Clinic" stay in examples (proper nouns).
Generic UI labels use "Customer." Same screen works for the lending pack
where rows would be "Chime", "Affirm", "Marlette" or for hiring where
they'd be "Indeed", "LinkedIn", "Greenhouse."

### Why this layout

- **Status dot first column** = immediate green/yellow/red signal at row scan
- **BAA expires** = the most important risk indicator (lapsed BAA breaks the chain)
- **30d decisions + HITL rate** = activity check (are they actually using us?)
- **Last PDF** = "have I given them an audit recently?"
- **Default sort:** attention-needed first (urgent BAAs bubble up)
- **No search bar in v1** — at 12 customers you scroll. v2 adds search at 30+

Click row → customer detail (Screen 3).

---

## Screen 3 — Customer detail (Cleveland Clinic)

The work surface for customer-specific actions. Single-scroll, small-caps
section headers, no tabs.

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   ← Customers                                                      │
│                                                                    │
│   Cleveland Clinic                                                 │
│                                                                    │
│   BAA in effect · expires Jun 23, 2027                             │
│   482 decisions last 30 days · 24 active reviewers                 │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   GENERATE AUDIT PDF                                               │
│                                                                    │
│   Audit period [ Last 30 days       ▾ ]                            │
│                                                                    │
│   [  Generate audit PDF  →  ]    See past PDFs ↓                   │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   STATUS                                                           │
│                                                                    │
│   ● BAA in effect · expires Jun 23, 2027 · 13 months away          │
│   ● 24 active reviewers · 12 MD, 8 NP, 4 RN                        │
│   ● 482 decisions · 158 required HITL · 158 received               │
│   ● Hash chain valid · last verified 30 seconds ago                │
│   ● Patient notice attested for 100% of patients enrolled          │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   RECENT DECISIONS                              See all (482) →    │
│                                                                    │
│   2:47 PM    abridge-scribe                                        │
│              Dr. Smith approved with modifications                 │
│              New diagnosis · controlled substance                  │
│                                                                    │
│   2:41 PM    abridge-voice                                         │
│              Triage escalated to RN                                │
│              Patient described chest pain                          │
│                                                                    │
│   1:58 PM    abridge-scribe                                        │
│              Dr. Chen approved                                     │
│              New diagnosis                                         │
│                                                                    │
│   ... [click for full list]                                        │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   REVIEWERS                                                        │
│                                                                    │
│   Derived from actual reviews. Your product handles reviewer       │
│   routing; Vera records who reviewed what, with what credentials.  │
│                                                                    │
│   Active in the last 30 days                                       │
│                                                                    │
│   Dr. Sarah Smith       MD, DEA           127 reviews              │
│   Dr. James Adams       MD                 89 reviews              │
│   Dr. Maria Chen        MD, DEA            67 reviews              │
│   Dr. Robert Lee        MD                 54 reviews              │
│   Nurse Patricia Wong   RN                 38 reviews              │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   DOCUMENTS                                                        │
│                                                                    │
│   ✓ BAA · signed Mar 12, 2026 · expires Jun 23, 2027    View →     │
│   ✓ Patient AI-use disclosure · version 2026.04         View →     │
│   ✓ Reviewer roster · 24 reviewers attested             View →     │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   PAST AUDIT PDFS                                                  │
│                                                                    │
│   May 6, 2026     Q1 audit · 30 days              Download →       │
│   Apr 9, 2026     Procurement request · 90 days   Download →       │
│   Mar 1, 2026     Initial onboarding              Download →       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### Why this order

1. **"Generate audit PDF" is at the top** because that's the most common
   reason someone visits this page — procurement-unblock, the moment of
   value capture.
2. **"Status"** second — answers "is this customer OK?" in 5 bullet points.
3. **"Recent decisions"** third — peripheral awareness without leaving the
   page.
4. **"Reviewers"** fourth — who's doing the actual review work; click to
   manage the roster.
5. **"Documents"** fifth — BAA / patient notice / roster proof-of-existence.
6. **"Past audit PDFs"** last — historical reference, occasionally needed.

Sections are visually separated by 1px ink-4 dividers and 48px vertical
gaps. Each section is collapsible if the user prefers; default is
"all expanded" because dashboard density is acceptable.

---

## Screen 4 — Compliance (org-wide)

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Compliance                                                       │
│                                                                    │
│   Documents and attestations for your organization.                │
│   These apply across all customers.                                │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   COMPLIANCE POSTURE                                               │
│                                                                    │
│      9.2 / 10        Strong runtime state                          │
│                                                                    │
│   Vera's measurement of your runtime compliance state.             │
│   Not a legal compliance score — that is determined by             │
│   regulators against your actual posture, not by Vera.             │
│                                                                    │
│   Artifact freshness         10/10                                 │
│   HITL completion            10/10                                 │
│   Reviewer integrity          9/10                                 │
│   Notice delivery rate       10/10                                 │
│   Chain integrity            10/10                                 │
│   Workflow timeliness         8/10                                 │
│                                                                    │
│   [ Show insights → ]                                              │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   ATTESTED                                                         │
│                                                                    │
│   ✓ HIPAA Risk Analysis · attested Mar 11, 2026                    │
│     Counsel of record: Sarah Park, General Counsel                 │
│     View →   Re-attest                                             │
│                                                                    │
│   ✓ Section 1557 Nondiscrimination Policy · attested Mar 11        │
│     View →   Re-attest                                             │
│                                                                    │
│   ✓ AI Tool Inventory · current as of May 6, 2026                  │
│     3 agents listed                                                │
│     View →   Update                                                │
│                                                                    │
│   ✓ Workforce AI Training · 87 staff trained                       │
│     Last cycle: Feb 2026 · Next due: Aug 2026                      │
│     View →   Schedule next cycle                                   │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   NIST AI RMF POSTURE                                              │
│                                                                    │
│      Govern  ✓     Map  ✓     Measure  ✓     Manage  ✓             │
│                                                                    │
│   Last refreshed May 1, 2026 · next due May 31, 2026               │
│   View posture statement →   Refresh now                           │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   STANDING NOTICE TEMPLATES                                        │
│                                                                    │
│   For your customers to deliver to affected persons at enrollment. │
│                                                                    │
│   ✓ HIPAA + Section 1557 baseline · deployed at 12 customers       │
│   ✓ California AB 489 supplement · deployed at 3 customers         │
│   ✓ Texas TRAIGA supplement · deployed at 2 customers              │
│                                                                    │
│   Manage templates →                                               │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### Why this page is separate from Settings

These are **attestation artifacts** — documents with legal weight, that the
customer (with counsel) has signed off on, that flow into the audit PDF as
evidence.

They're not "settings you change"; they're "documents you maintain." The
distinction matters for the user's mental model.

The explicit "Counsel of record: Sarah Park, General Counsel" line under
each attested document reinforces the Delve guardrail — the customer + counsel
reviewed this, it's not a Vera-fabricated artifact.

---

## Screen 5 — Settings

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Settings                                                         │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   AGENTS                                                           │
│                                                                    │
│   abridge-scribe v3.2.1   3 gates · review threshold 30s    Edit → │
│   abridge-voice  v2.1     2 gates · review threshold 30s    Edit → │
│   abridge-claims v1.0     1 gate  · review threshold 60s    Edit → │
│                                                                    │
│   + Add agent                                                      │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   API KEYS                                                         │
│                                                                    │
│   al_live_•••••••••3kf2   rotated Mar 1, 2026     Rotate · Revoke │
│   al_test_•••••••••9j8a   rotated Apr 12, 2026    Rotate · Revoke │
│                                                                    │
│   + Generate new key                                               │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   TEAM                                                             │
│                                                                    │
│   Sarah Park   Admin       sarah@abridge.com                       │
│   James Lee    Engineer    james@abridge.com                       │
│   Maya Patel   Read-only   maya@abridge.com                        │
│                                                                    │
│   + Invite member                                                  │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   BILLING                                                          │
│                                                                    │
│   Plan: Growth                                                     │
│   12 customers · 3 agents · 2,847 decisions last 30 days           │
│   Next invoice: Jun 1, 2026                                        │
│                                                                    │
│   Manage billing →                                                 │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   BRANDING                                                         │
│                                                                    │
│   Upload your logo for white-labeled audit PDFs.                   │
│                                                                    │
│   [ Drag a PNG, SVG, or JPG here, or browse ]                      │
│                                                                    │
│   Current logo:  (preview)                                         │
│   Recommended:   square or horizontal, ≥512px, transparent bg      │
│                                                                    │
│   [ Replace ]   [ Remove ]                                         │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   PACK CONFIGURATION                                               │
│                                                                    │
│   ClinicalScribePack v2026.05 · in-app webhook (default channel)   │
│                                                                    │
│   Configure pack →                                                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Standard settings; least visited; least invested in chrome.

---

## Supporting flow — Generate PDF modal

Clicked from Home or any Customer page. One concentrated decision point.

```
┌──── Generate audit PDF for Cleveland Clinic ────────────  × ┐
│                                                              │
│   Period                                                     │
│                                                              │
│   ○ Last 30 days                                             │
│   ● Last 90 days                                             │
│   ○ Year to date                                             │
│   ○ Custom range  [ from ] [ to ]                            │
│                                                              │
│                                                              │
│   Branding                                                   │
│                                                              │
│   ● Your logo (Abridge) — recommended                        │
│   ○ Co-branded (Abridge + Cleveland Clinic logo)             │
│   ○ No branding (Vera technical appendix only)               │
│                                                              │
│                                                              │
│   Recipient note                                             │
│                                                              │
│   "Prepared for Cleveland Clinic procurement, May 19, 2026"  │
│                                                              │
│                                                              │
│   The PDF will include:                                      │
│   · Audit Trail — every AI-assisted decision in the period   │
│   · HITL evidence — physician sign-off per decision          │
│   · NIST AI RMF posture mapping                              │
│   · Section 1557 disparate-impact monitoring summary         │
│   · Cryptographic verification appendix                      │
│                                                              │
│                                                              │
│                                       [  Generate  →  ]      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Why this design

Transparency about what's in the PDF — the user knows what they're handing
to procurement before they generate it. Branding default is "Your logo
(Abridge)" because that's the white-labelable artifact you ship up the chain.

The "Recipient note" pre-fills with a clean phrase the procurement officer
will see on the cover page.

---

## Supporting flow — BAA renewal

Triggered from multiple surfaces:
- **Home banner** when BAA is ≤30 days from expiry: "Stanford Health · BAA expires in 18 days [ Renew ]"
- **Customers list** column flag: "Jun 2026 !" in brick-red when ≤30 days
- **Customer detail** status line: brick-red text + persistent banner when ≤30 days
- **PDF generation modal**: blocked with explanation if BAA expired
- **Email alerts** at 90, 30, 7 days before expiry; daily after expiry
- **Runtime soft warning** in v1 (warning in audit trail); v2 hard-blocks new decisions post-expiry

The renewal modal:

```
┌── Renew BAA · Stanford Health ──────────────  × ┐
│                                                  │
│   Current BAA                                    │
│   Signed Apr 5, 2024 · Expires Jun 6, 2026       │
│   18 days remaining                              │
│   [ View current BAA → ]                         │
│                                                  │
│   ──────                                         │
│                                                  │
│   How do you want to renew?                      │
│                                                  │
│   ●  Upload new signed BAA                       │
│      You've negotiated a new BAA with Stanford   │
│      Health and have a signed PDF.               │
│                                                  │
│   ○  Send Vera's standard BAA to Stanford        │
│      Health for signature  (v2 feature)          │
│      We'll email your contact with the BAA       │
│      template + DocuSign link.                   │
│                                                  │
│   ○  Defer renewal (14 days)                     │
│      Extend the warning. Use if your renewal     │
│      is in progress externally.                  │
│                                                  │
│   [ Continue ]                                   │
│                                                  │
└──────────────────────────────────────────────────┘
```

After "Upload new signed BAA":

```
┌── Upload new BAA · Stanford Health ───────  × ┐
│                                                │
│   Drag a signed BAA PDF here, or [ browse ]    │
│                                                │
│   New expiry date  [ MM / DD / YYYY ]          │
│                                                │
│   Counsel of record (optional)                 │
│   [ Name ]                                     │
│                                                │
│   [ Confirm renewal ]                          │
│                                                │
└────────────────────────────────────────────────┘
```

After confirmation, the new BAA replaces the active one; old BAA stays in
customer's document history; status flips to green; PDF generation
unblocks.

The "Defer renewal" option is honest about reality — sometimes
negotiations are slow. Better to acknowledge the delay than fake a
renewal. Defer adds 14 days to the warning clock; can be used twice max
before requiring escalation.

---

## Supporting flow — Compliance Posture insights

Triggered from the "Show insights →" button on the Compliance Posture
section. Vera calls a Haiku-class LLM on demand with the score breakdown
+ raw counts; insights surface as plain-English recommendations.

```
┌── Compliance Posture · insights ────────────  × ┐
│                                                  │
│   Your current posture: 9.2 / 10                 │
│                                                  │
│   ──────                                         │
│                                                  │
│   Workflow timeliness is your lowest dimension   │
│   (8/10).                                        │
│                                                  │
│   Two adverse-action notices were sent 32-35     │
│   days after the decision, missing the ECOA      │
│   30-day deadline. The pattern is concentrated   │
│   in Stanford Health. Consider reviewing the     │
│   notice-generation step with your team there.   │
│                                                  │
│   ──────                                         │
│                                                  │
│   Three reviewers averaged 25-28 seconds,        │
│   below your 30-second threshold.                │
│                                                  │
│   This appears in 12 reviews last week at        │
│   Cleveland Clinic. If your clinical workflow    │
│   doesn't require a 30-second floor for          │
│   routine acknowledgements, consider lowering    │
│   the threshold; if it does, identify which      │
│   reviewers need workflow adjustment.            │
│                                                  │
│   ──────                                         │
│                                                  │
│   Insights generated by Vera (Haiku-class LLM)   │
│   on May 19, 2026 at 3:47 PM. Insights are       │
│   recommendations, not regulatory advice.        │
│                                                  │
│   Cost: ~$0.02. [ Refresh insights ]             │
│                                                  │
└──────────────────────────────────────────────────┘
```

The "not regulatory advice" disclaimer is essential — the Delve guardrail
applies to insights too. We can recommend; we can't pretend to opine on
compliance.

---

## Compliance Posture — how the score is computed

The posture is six dimensions, each measured deterministically.
Aggregate is a weighted average normalized to 10. **No LLM in the
score formula** — only in the optional insights generation.

| Dimension (universal across packs) | Measurement | Weight |
|---|---|---|
| **Artifact freshness** | % of required artifacts current and unexpired (per pack: BAA + HIPAA RA in medtech, ECOA docs in lending, etc.) | 20% |
| **HITL completion** | % of decisions requiring HITL that received it before commit | 25% |
| **Reviewer integrity** | % of HITL events meeting threshold AND with correct credentials | 15% |
| **Notice delivery rate** | % of required notices delivered (per pack: patient AI disclosure in medtech, adverse-action letters in lending) | 10% |
| **Chain integrity** | % of last 30 days with no hash-chain validation failures | 20% |
| **Workflow timeliness** | % of post-action workflows completed within statutory deadlines | 10% |

The dimensions are **universal across all packs** — the math is the
same in medtech as in lending. Each pack declares its own per-dimension
inputs (which artifacts count, which gates require HITL, which notices
are required). One posture algorithm, many vertical inputs.

The result is a single decimal `X.Y / 10`. Every component is auditable
by the regulator — they can be told exactly how the number was computed.

### Dimension minimums (low-volume guard)

Each dimension requires a minimum data-point count before computing a
score. Below the minimum, the dimension shows "insufficient data" rather
than a misleading number. A customer with 100 decisions and 1 missed
deadline doesn't get 9.9/10 on workflow timeliness based on a single
data point — they get an honest "insufficient data, see raw counts."

### Why "Posture" not "Score"

Deliberate language choice with legal implications. **Compliance is a
legal status determined by regulators; posture is what Vera can observe
at runtime.** You can be sued for misrepresenting compliance; you cannot
be sued for misrepresenting your runtime posture (which is a measurable
fact). The distinction matters.

The score itself sits on the **Compliance page**, with a chip on
**Home**. Not on the Customer detail page in v1 (per-customer posture is
v2 — for now, all measurements are org-wide).

### What scores DON'T do

- ❌ **No comparisons** ("you're better than 80% of similar orgs") — that's noise; nothing to act on
- ❌ **No "HIPAA-compliant" claim** at 10/10 — the score reflects runtime state, not legal compliance
- ❌ **No marketing surface** — we don't show this in sales materials or homepage; it's a customer-internal tool
- ❌ **No regulator-facing surface** — the audit PDF contains the underlying evidence; auditors don't trust Vera's aggregate score, they trust the underlying data

---

## Supporting flow — Decision detail

Clicked from any Recent Activity row. The full evidence chain for one
decision.

```
┌──── Decision detail · 2:47 PM May 19, 2026 ─────────────  × ┐
│                                                              │
│   abridge-scribe v3.2.1                                      │
│   Cleveland Clinic · pat_8h2nf · visit_3k2f                  │
│                                                              │
│                                                              │
│   AI SUGGESTED                                               │
│                                                              │
│   New diagnosis: acute pancreatitis                          │
│   New orders:                                                │
│     · morphine 4mg IV q4h prn (Schedule II)                  │
│     · NPO                                                    │
│     · LR 100 mL/hr                                           │
│                                                              │
│                                                              │
│   WHY THIS NEEDED REVIEW                                     │
│                                                              │
│   · New diagnosis (HIPAA § 164.312(b))                       │
│   · Schedule II medication (21 CFR 1306.04)                  │
│                                                              │
│                                                              │
│   REVIEWER DECISION                                          │
│                                                              │
│   Dr. Sarah Smith · MD, DEA                                  │
│   Approved with modifications · 2:47:42 PM                   │
│   Time to review: 38 seconds                                 │
│                                                              │
│   Comment: "Confirmed pancreatitis on labs;                  │
│             reduced morphine to 2mg q4h."                    │
│                                                              │
│                                                              │
│   MODIFIED OUTPUT                                            │
│                                                              │
│   morphine 4mg → 2mg                                         │
│   (NPO, LR 100 mL/hr unchanged)                              │
│                                                              │
│                                                              │
│   EVIDENCE                                                   │
│                                                              │
│   Hash: 0xabc...def · seq 8h2n                               │
│   Signed by KMS key alias/vera-prod-2026                     │
│   Anchored to OpenTimestamps block 892,341                   │
│   Auth: SAML SSO (Cleveland Clinic IdP)                      │
│                                                              │
│   [ Verify online ]   [ Verify offline ]                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Why this layout

Chronological story: AI did X → it needed review because Y → reviewer Z
decided W → final output → cryptographic proof. Mirrors the audit PDF's
section structure so the user learns the artifact format by reading the
dashboard.

---

## Empty state — brand new customer

```
┌────────────────────────────────────────────────────────────────────┐
│  vera                                Customers  Compliance  ⚙  ◐  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Welcome to Vera.                                                 │
│                                                                    │
│   Two steps to your first audit-ready PDF.                         │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│                                                                    │
│   ●  Install the SDK                                               │
│      pip install vera                                              │
│                                                                    │
│      [ See install guide → ]                                       │
│                                                                    │
│   ○  Add your first agent                                          │
│      Configure your AI scribe, voice agent, or other tool.         │
│                                                                    │
│      [ Add agent → ]                                               │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│   CUSTOMERS — HOW DO YOU WANT TO POPULATE THEM?                    │
│                                                                    │
│   ●  Auto-discover (recommended)                                   │
│      Customers will appear here as your SDK fires gate calls.      │
│      No setup needed — just install the SDK with middleware,       │
│      and we'll create placeholders for each new tenant_id.         │
│      You complete the BAA + display name when you see them.        │
│                                                                    │
│   ○  Add manually                                                  │
│      Best if you have a few customers you want to set up now.      │
│      [ Add customer → ]                                            │
│                                                                    │
│   ○  Bulk import via CSV                                           │
│      Best if you have many customers and want them populated       │
│      proactively (with BAAs attached) before traffic flows.        │
│      We'll run AI-assisted matching against any auto-discovered    │
│      placeholders.                                                 │
│      [ Download template → ]                                       │
│                                                                    │
│                                                                    │
│   ──────────────────────────────────────────────                   │
│                                                                    │
│   Need help getting started?                                       │
│   Read the install guide → · Contact support →                     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Two required steps (SDK + agent), one elective step (customers — pick a
path). The user can't get lost; the auto-discover option means they can
skip explicit customer setup entirely if they want to.

---

## Copy decisions — every text choice has a reason

| Phrase | Why this and not the alternative |
|---|---|
| "Needs your attention" | Sounds like a colleague flagging a thing, not a system shouting. Alternatives: "Alerts", "Action items", "Notifications" — all read more aggressive. |
| "Customers" | Generalizes across verticals (medtech: hospitals; lending: banks; hiring: employers). Unambiguous in context because the user is logged in as their own org — "your customers" reads naturally. Alternatives: "Hospitals" (locks us to medtech), "Tenants" (SaaS-generic), "Deployments" (too technical). |
| "BAA in effect · expires Jun 23, 2027" | Fully spelled-out date. Counsel reads exact dates, not "13 months away" (though we show both). |
| "audit-ready PDF" | The noun phrase the user wants to hand to procurement. Alternatives: "compliance report" (too vague), "audit log" (too raw). |
| "Generate audit PDF" | Verb-first imperative. Matches the user's intent ("I came to do this"). |
| "Counsel of record: Sarah Park" | Surfaces the human who attested. Reinforces Delve guardrail. Alternatives: "Approved by org admin" (impersonal), "Signed by user_142" (technical). |
| "Anchored to OpenTimestamps block 892,341" | Technical evidence is shown, not hidden. Trust through transparency. |
| No "Powered by Vera" branding | Vera is the substrate. The dashboard belongs to Abridge. Ego attribution dilutes the conduit's brand. |
| "Re-attest" (verb) on documents | Reminds the user this is a legal action, not a casual save. |

---

## Edge cases handled

| Edge case | Handling |
|---|---|
| Zero customers | Empty state with 3-step onboarding |
| One customer | Same structure; just one row in the list (no special-casing) |
| 50+ customers | Search bar appears at 30+ (v2); v1 ships with sort-by-attention default |
| BAA expired | Customer row shows red dot + urgent banner on Home; PDF generation blocked with explanation |
| Hash chain integrity violation | Critical banner on every page until resolved; PDF generation blocked |
| Customer eng team only (no compliance officer) | Same UI; eng leads are competent users |
| Customer with multi-agent setup | Each agent appears in Settings; Recent Activity tags each decision with the agent |
| Read-only team member | Same UI; "Generate / Edit / Re-attest" buttons disabled with hover tooltip |

---

## What we deliberately don't build in v1

- **Charts and graphs.** Not a BI tool. Compliance officers want yes/no, not visualizations.
- **Real-time decision streaming.** Recent Activity refreshes on page load. Polling every second is unnecessary.
- **In-dashboard messaging / comments.** Teams use Slack. We don't reinvent collaboration.
- **Pre-registered reviewer roster.** Reviewers are derived from actual reviews. The customer's app already owns identity / routing; their webhook callback attests reviewer + credentials. v1 doesn't ask the customer to pre-fill a roster.
- **PDF preview.** v1 does direct download; preview moves to v2 if asked for.
- **Decision search within a customer.** Defer to v2; v1 customer base won't have the volume to need search.
- **Customizable dashboard.** Users can't hide sections. The default IS the answer.
- **Dark mode.** Inherits cream brand from DESIGN.md. Dark mode is a separate phase.
- **Mobile.** Compliance officers don't generate audit PDFs from phones. Mobile-responsive but not mobile-optimized.

### What we DO build that we initially considered dropping

- **Compliance Posture (renamed from "Score").** Originally pushed back as a vanity metric, but the user is right that a runtime-state indicator is valuable. The Delve guardrail is satisfied by: deterministic formula (no LLM in the score), explicit "posture not compliance" language, on-demand insights labeled as recommendations not advice. See Compliance page section above.
- **AI-generated insights** on the Posture page. On-demand only (not per-page-load), Haiku-class model, disclosed cost, framed as recommendations.

---

## Build order (suggested implementation sequence)

When implementing this design, build in this order to ship value early:

1. **Empty state + onboarding** (Week 1) — the first thing a new customer sees
2. **Settings: Agents + API Keys** (Week 1-2) — they need to add their agent + key before anything works
3. **Customers: Add Customer + Customers list + CSV bulk import + AI-assisted Match Review** (Week 2) — the multi-tenant core
4. **Home: Status line + Recent Activity** (Week 3) — the daily-check surface
5. **Customer detail: Generate PDF button + PDF modal** (Week 3-4) — the moment of value capture
6. **Compliance page + attestation templates + Compliance Posture + AI insights** (Week 4-5) — the org-wide docs + posture engine
7. **Decision detail drill-down** (Week 5) — secondary surface
8. **Home: Needs your attention** (Week 5-6) — derived from artifact freshness + workflow state; can ship empty in v1 and fill in v2

The first sellable demo is reachable by end of Week 4: install SDK →
add customer → see decisions stream → generate first PDF. That's the
5-minute live install demo from the MVP doc.

---

## Resolved product decisions

The earlier draft had open questions; here are the resolutions after
product discussion:

1. **Logo upload — Settings page.** Resolved: dedicated "Branding"
   section in Settings. If a user picks "Your logo" in the PDF modal
   without having uploaded one, the option shows
   "⚠ Upload a logo first →" linking to Settings · Branding inline.

2. **BAA renewal flow — full modal designed above.** Resolved: triggered
   from Home banner / Customers list / Customer detail / blocked PDF
   gen. Modal with three options (upload new signed BAA / send Vera
   template via DocuSign in v2 / defer renewal 14 days).

3. **Reviewer roster — derived, not pre-registered.** Resolved: drop
   pre-registration. Reviewers are added automatically when their first
   webhook callback comes in. Credentials come from the callback. The
   customer's app already owns identity and routing — Vera records the
   attestation and validates the role/credential matches the gate
   requirement.

4. **PDF preview — direct download in v1.** Resolved: no preview. Click
   Generate → PDF downloads. Preview is a v2 polish.

5. **Decision search — not in v1.** Resolved: defer to v2 when customer
   base hits the volume to need it.

6. **Notification preferences — email + dashboard banner in v1.** Slack /
   Teams in v2.

7. **Compliance posture (originally pushed back as vanity, now included).**
   Resolved: build it, frame it as "posture" not "score," compute
   deterministically, surface AI insights on-demand only with explicit
   "recommendations not regulatory advice" disclaimer. Detailed
   formula in Compliance page section.

## Remaining open questions (v1 build-time)

1. **CSV import error handling.** If the org uploads 50 customers and 3
   rows have validation errors, what happens? Partial commit (47
   succeed, 3 surface for fix) or all-or-nothing? Recommend partial
   commit with a clear error report. (Resolved above.)

2. **Compliance posture weighting.** The dimension weights (20/25/15/10/20/10)
   are a first guess. Should be validated with the Big Law opinion
   process — does the weighting reflect what the regulator would
   actually care about?

3. **What happens when posture drops?** If the score drops from 9.2 to
   8.4 overnight (e.g., a BAA quietly expired), do we send an email?
   Add a banner? Both. Threshold to be tuned with first pilot customers.

---

## Inheritance from DESIGN.md

| DESIGN.md element | How the dashboard inherits it |
|---|---|
| Petrona display | Page titles only ("Abridge", "Customers", "Cleveland Clinic") at 28-56px |
| Inter body | Everything else; tabular-nums on numeric data |
| Small-caps section headers | Inter 12px / 600 / 0.10em / uppercase — used for "NEEDS YOUR ATTENTION", "GENERATE AUDIT PDF", etc. |
| Warm cream `#FEFAF3` | Page background |
| Paper-2 `#F5EFE3` | Card surfaces, dropdown backgrounds |
| Espresso primary buttons | "Generate", "Renew", "Add customer" CTAs |
| Cream secondary buttons | "See past PDFs", "Manage", "Configure pack" |
| Status dots | Olive `#3E5C3B` (OK), brick `#7A2E1F` (urgent), ink-3 (neutral) |
| 1px ink-4 dividers between rows | Tables, section dividers |
| `--shadow-1` on cards | Default card lift |
| Generous spacing (32-48px between sections) | Editorial breathing room, dashboard-density per DESIGN.md |
| No emerald | Removed entirely; success indication is olive |
| No mono | Inter tabular-nums for hashes, IDs, numeric data |
| No marketing copy | Dashboard is a work surface, not a brochure |

The dashboard reads as a continuation of the marketing surface — same
typography, same warm-cream paper, same calm posture — with slightly more
chrome appropriate to a work environment.

---

## TL;DR

Four nav items: **Home, Customers, Compliance, Settings.**

Home answers "is everything OK?" and "generate me a PDF right now," plus
a single-line compliance-posture chip (9.2/10) linking to the Compliance
page for the full breakdown.

Customers is the multi-tenant first-class concept — each customer (your
customer: hospital, bank, employer) has its own page with its own BAA,
reviewers (derived from actual reviews, not pre-registered), decisions
stream, and PDF history. Customers are populated three ways: manual (1-5),
CSV bulk import (5-100+, with AI-assisted Match Review against
auto-discovered placeholders), or auto-discovered from SDK calls
(placeholder + "complete setup" prompt).

Compliance holds org-wide attestation documents (HIPAA Risk Analysis,
Section 1557 Policy, NIST AI RMF Posture, Standing Notice Templates) and
the **Compliance Posture** dashboard — a deterministic 6-dimension
runtime measurement aggregated to /10, with on-demand AI insights
(Haiku-class, explicitly framed as "recommendations not regulatory
advice"). Called "posture" not "score" — the legal distinction matters.
The six dimensions are universal across packs (medtech, lending, hiring);
each pack declares its per-dimension inputs.

Settings is configuration: agents, API keys, team, billing, **branding
(logo upload for white-labeled PDFs)**, pack configuration.

Three input methods for the SDK to identify which customer a call
belongs to: middleware (default, one wire-up), context manager
(background jobs), explicit per-call tag (escape hatch). Vera doesn't
auto-detect from payload — the org attests via `tenant_id`. First time
a new tenant_id appears, Vera auto-creates a placeholder customer;
decisions are captured but PDF generation is blocked until the org
completes setup.

HITL invocation is webhook by default — Vera POSTs to a customer URL
with review context; customer renders the prompt in their existing UI;
customer POSTs decision back with reviewer identity + credentials
attestation. Vera is invisible to the practitioner. Slack-direct and
Vera dashboard are fallback channels for solo practitioners or compliance
batch oversight.

The dashboard belongs to the customer — not to Vera. Vera is mentioned
once, in the technical appendix of the PDFs. The whole interface
inherits DESIGN.md's editorial register: warm cream, Petrona display,
Inter body, small-caps section headers, olive for OK, brick for urgent.

Every element exists because the compliance officer has a job to do; the
goal is to let them do it in 30 seconds and leave.
