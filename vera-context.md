# Vera Context — Conversation Summary

**Purpose:** Context loader for future sessions. Captures everything
researched, decided, approved, denied, and deferred over the
conversation spanning May 18-22, 2026. Use this file as the
single-source onboarding for any future Vera work.

**Not in this file:** the full content of the design docs themselves.
Those live in:
- [policy-engine-mvp.md](policy-engine-mvp.md)
- [policy-engine-north-star.md](policy-engine-north-star.md)
- [dashboard-design.md](dashboard-design.md)
- [landing-design.md](landing-design.md)
- [dashboard-design-system.md](dashboard-design-system.md)

This file is the **why** behind those docs — what the user pushed
back on, what got reframed mid-conversation, what's still open.

---

## 1. Product context

**Vera** is the runtime trust layer for AI agents in regulated
industries. Sits between an AI agent and any consequential action,
intercepts the action synchronously, routes high-risk actions to a
qualified human reviewer, and emits a cryptographically signed
evidence trail.

**Strategic positioning** (from [strategy.md](strategy.md)):
- *Vanta* sells **paperwork** to GRC buyers. *Vera* sells **runtime
  evidence** to platform engineering buyers. Different product,
  different buyer, complementary.
- Act 1 — Compliance SDK ($50K-$150K ACV, $1M ARR target Year 1)
- Act 2 — Insurance data network ($1B+ ceiling, 24-36 months out)

**ICP (existing marketing positioning):** CEOs and in-house counsel
at companies deploying AI in regulated spaces — lending, underwriting,
clinical decision support, hiring. Secondary: heads of risk,
compliance, audit. Engineering buyers are tier-3 on the marketing
surface but **tier-1 on the dashboard** (they install the SDK).

**Pivot during conversation:** the user overruled my initial
"lending first" recommendation and pivoted v1 to **medtech first**
(AI scribes, voice receptionists, prior-auth agents). Reasons:
network access via LeapYear, depth of use cases in
[use_cases.md](use_cases.md), HITL is native to medtech workflows
(physicians already sign off), HIPAA § 164.312(b) is the cleanest
regulatory hook in any industry, Section 1557 § 92.210 is in force
NOW (May 2025).

---

## 2. The regulatory landscape (researched)

Four parallel deep-research dossiers were run at the start of the
conversation, then refined. Thirteen regulations Vera must enforce
between now and end of 2027:

| # | Regulation | Status (May 2026) | Hits |
|---|---|---|---|
| 1 | EU AI Act (Reg. 2024/1689) | Art. 5 + GPAI in force; Annex III Aug 2, 2026 | EU users, extra-territorial |
| 2 | Colorado AI Act (SB 24-205 → SB 26-189) | **Federally stayed Apr 27, 2026**; SB 26-189 effective Jan 1, 2027 | CO consumers, 8 consequential domains |
| 3 | NYC Local Law 144 (AEDT) | In force since Jul 2023 | Hiring/promotion of NYC residents |
| 4 | Texas TRAIGA (HB 149) | In force Jan 2026 | TX residents, prohibited uses + gov/healthcare |
| 5 | Utah AI Policy Act (SB 149 + 226 + 332) | In force, sunset Jul 2027 | UT consumers, regulated occupations |
| 6 | California stack (AB 2013, SB 942, SB 1001, AB 489, SB 243, SB 53, CPPA ADMT) | Layered Jan 2026 → 2028 | CA users; CPPA ADMT is the heaviest |
| 7 | Illinois HB 3773 + AIVICA + BIPA | HB 3773 Jan 2026; AIVICA since 2020 | IL employees/candidates |
| 8 | Connecticut SB 5 | Pending; Feb 2026 if enacted | CT consumers |
| 9 | HHS Section 1557 § 92.210 + OCR AI guidance | DSI provisions in force May 1, 2025 | Healthcare providers receiving HHS funds |
| 10 | FDA AI/ML SaMD + PCCP + QMSR | QMSR Feb 2026; PCCP guidance Dec 2024 | AI medical device manufacturers |
| 11 | ONC HTI-1 (DSI source attributes) | Cert updated Dec 31, 2024 | EHR-certified health IT |
| 12 | ECOA Reg B + FCRA + Section 1071 | In force; 1071 likely Jan 2028 | Any creditor |
| 13 | EEOC Title VII + ADA AI guidance | In force May 2023 | All employers |

Plus three safe-harbor frameworks (not laws, but how reasonable care
is proven): **NIST AI RMF v1.0 + GenAI Profile**, **ISO/IEC 42001:2023**,
**OMB M-25-22** (federal procurement).

Plus federal context: **EO 14179** (Jan 2025) revoked prior EO;
**December 2025 preemption EO** establishes AI Litigation Task Force
to challenge state laws but does not preempt. State laws remain
binding through 2026-2027.

### Key research surprises

- **Colorado is a moving target.** SB 26-189 repealed and reenacted
  the framework in May 2026; federally stayed since April 2026.
  Build for both regimes simultaneously.
- **HIPAA § 164.312(b) "record and examine activity"** is the
  cleanest one-to-one regulatory hook for Vera in any industry.
- **CFPB Circular 2022-03/2023-03** explicitly says "AI black-box"
  is not a defense for ECOA — specific reasons required.
- **OCR Jan 10, 2025 Dear Colleague letter** on Section 1557:
  "liability flows to the covered entity using the tool, not just
  the vendor" — confirms hospital is the audit target.

---

## 3. The architectural premise (the load-bearing insight)

**Vera serves a chain, not a customer.** This phrase reshapes every
product decision.

```
            (audits — HHS OCR, state AG, EU MSA, etc.)
                    ▼
[Tier 1] Regulator / Audit Consumer
                    ↑ asks for evidence
[Tier 2] Audit Target (hospital, bank, employer)
                    ↑ "show me your audit logs"
[Tier 3] Vera Customer / Conduit (the AI vendor — Abridge, Suki, etc.)
                    ↑ ships SDK, signs BAA, brands artifacts
[Tier 4] Vera (the substrate)
                    ↓ (Act 2, future)
[Tier 5] Insurance Carrier
```

Plus two participants who receive artifacts but aren't audit consumers:
- **Tier 6** — The Reviewer (HITL human — physician, loan officer,
  recruiter)
- **Tier 7** — The Affected Person (patient, applicant, candidate)

Every Vera artifact has one tier as its consumer:
- PDF → Tier 1 (regulator), flowing through 2 and 3
- Dashboard → Tier 3 (customer's compliance team)
- Standing notice → Tier 7 (affected person), delivered by Tier 2
- HITL review prompt → Tier 6 (reviewer), rendered inside Tier 3's product

Vera is **invisible** to Tiers 1, 2, 6, and 7. Tier 1 trusts the
cryptographic chain + BAA structure, not Vera's brand. The dashboard
in Tier 3 is the only place Vera's brand actually appears.

---

## 4. The four moats (explicit)

These are the durable assets a competitor cannot easily replicate:

1. **Runtime substrate** — pre-action gate engine, hash chain, KMS
   signing, encrypted spool, webhook delivery with retries, SDK
   plumbing, off-Vera checkpoint mechanism. **12-18 months of
   engineering minimum.**

2. **Regulatory translation library (the packs)** — DEA controlled-
   substance lists, RxNorm mappings, ECOA reason-code taxonomies,
   demographic-stratification logic, role-credential mappings, per-
   jurisdiction conditional clauses, citation strings. **Hundreds
   to thousands of hours of regulatory research per pack, plus
   quarterly refresh as regulations shift.**

3. **Legal opinion stack** — one written opinion per major
   regulation from a credible Big Law practice (Hogan Lovells for
   HIPAA + Section 1557, Wilson Sonsini for ECOA, etc.). $30-60K
   and 3-6 months per opinion. Opinion-of-Vera — not transferable.

4. **BAA / DPA / Sub-processor chain trust position** — Vera signs
   BAAs as a Subcontractor BA. Requires HIPAA security posture,
   SOC 2, insurance, operational maturity, customer references.
   Competitor outside the chain cannot see the data needed to
   produce the PDF. Switching cost is real.

**Key user concern surfaced midway:** they worried I'd accidentally
de-emphasized the runtime engine in favor of the PDF. I clarified:
the PDF is the *output*; the engine is *what makes the PDF
defensible*. Without the engine, the PDF says "per the customer's
report, X happened" — which OCR rejects as non-auditable.

---

## 5. The six surfaces of regulation (universal pattern)

Every AI regulation decomposes into the same six surfaces:

1. **Scope test** — does this regulation apply? (jurisdiction × domain
   × use class × role × size threshold)
2. **Pre-deployment artifacts** — what docs must exist + be current?
   (BAA, FRIA, IA, bias audit, RMF posture, public statement)
3. **Per-action runtime gates** — what must be true at action time?
   (block, HITL, notice, opt-out, disclosure, watermark, redact,
   degrade)
4. **Per-action evidence capture** — what must be recorded?
   (universal schema in Appendix A of north-star)
5. **Post-action workflows** — what must happen after? (adverse-
   action notice 30d, appeal, correction, explanation, AG
   disclosure 90d, incident 2/10/15d)
6. **Periodic obligations** — what must happen on a schedule?
   (annual bias audit, IA refresh, post-market monitoring, RMF
   review)

The Compliance Posture surface uses these directly as its 6
dimensions (see §10).

---

## 6. The seven primitives (engineering decomposition)

| Primitive | What it is | Lives in |
|---|---|---|
| Context | Per-decision input — subject, jurisdiction, domain, use_class, action_class, agent, decision attributes, active artifacts | SDK + ActionRecord |
| Predicate | Composable boolean language over Context. Internal AST. YAML DSL for power users in v3+ | Pack modules |
| Gate | Predicate + Effect (ALLOW/BLOCK/REQUIRE_HITL/REQUIRE_NOTICE/REQUIRE_OPTIN/REQUIRE_DISCLOSURE/REDACT/WATERMARK/DEGRADE). Composes by strictest-effect dispatch | Pack modules |
| Artifact | Typed registry entity (FRIA, IA, bias_audit, BAA, etc.) with version, validity, origin tag, citations | Artifact registry |
| Workflow | Stateful post-action process with statutory deadline | Workflow engine |
| Scheduler | Periodic obligation cron + reminder ladder + artifact-production hooks | Scheduler subsystem |
| Artifact renderer | Format-specific export over the same evidence store (HIPAA PDF, EU Conformity Package, NYC Public Summary, NIST RMF posture, etc.) | Renderer matrix |

---

## 7. Product decisions — the big ones

### 7.1 Vertical: medtech first (user overruled my lending pick)

**My initial recommendation:** lending wedge (US ECOA + NIST AI RMF
halo), $50K-$150K ACV, AI lending startups.

**User's correction:** medtech is the actual first market —
LeapYear network, depth of use cases, HITL is native, HIPAA + Section
1557 are clean hooks. AI scribes (Abridge, Suki, Ambience, DAX) are
engineering-led startups already facing hospital procurement
obstacles around AI audit logs.

**Final v1 wedge:** **AI scribe → chart entry**. Customer's scribe
generates a clinical note; Vera intercepts before chart commit; new
diagnosis or controlled-substance order routes via webhook to the
customer's product (which surfaces the review to the attending
physician inside its own UI); physician approves/modifies/rejects;
customer attests reviewer ID + credentials back; Vera signs the
chain.

Lending stays Wave 2 (ECOA Reg B + EEOC + Colorado overlay).

### 7.2 "Auditable" not "compliant" (the Delve guardrail)

The Delve cautionary tale (an AI compliance startup that lost
customer trust by generating boilerplate policies that didn't
reflect actual practices) shapes Vera's positioning:

- **Vera auto-generates evidence artifacts** (HIPAA audit log,
  Compliance evidence PDF, NIST RMF posture, disparate-impact
  monitoring report) — these are derivatives of runtime data, true
  by construction.
- **Vera provides templates with red banners** for organizational
  attestations (HIPAA Risk Analysis, Section 1557 Nondiscrimination
  Policy, AI Tool Inventory) — customer + counsel must review and
  sign, never one-click signoff.
- **Vera never claims the customer is "compliant"** — only that
  they're "auditable" through the BAA chain.

The honest pitch: *"Vera doesn't make you HIPAA-compliant. Vera
makes every AI decision provable. When a regulator asks, you have
the answer in one PDF."*

### 7.3 The PDF is the central artifact, but the engine is the moat

User explicitly worried this might shift Vera away from being a
policy engine. I confirmed: the engine IS the moat (4 moats above).
The PDF is the moment of value capture but worthless without the
engine attesting to its claims.

The PDF must be:
- **Customer-white-labelable** — Cleveland Clinic forwards it to OCR
  branded as Abridge. Vera is mentioned once in a technical appendix.
- **Self-verifying without contacting Vera** — verification URL +
  customer-controlled S3 mirror + OpenTimestamps anchor. Audit trail
  outlives Vera.
- **Written for an OCR investigator**, not for Abridge — plain
  regulatory English, citations to 45 CFR § 164.312(b) and §
  92.210, no Vera jargon.
- **Counsel-reviewed before v1 ship** — commission Big Law
  healthcare practice in Week 1 ($30-60K, 3-6 months for letter).

### 7.4 Tenant identification: middleware default, CSV optional

User's instinct: middleware auto-detection means bulk CSV upload
isn't needed. **My pushback:** auto-discover handles the engineering
path, but three real scenarios warrant keeping CSV as an option:

1. Compliance officer pre-knowledge (50 customers known on day 1)
2. The "47 decisions awaiting BAA" purgatory state
3. Tenant_id → display name mapping (`hosp_8h2nf_v2` reads awful
   without pre-mapping)

**Resolution:** three onboarding paths, none required —
auto-discover (default), manual (1-5), CSV bulk (5+, with
**AI-assisted Match Review** against auto-discovered placeholders).
User accepted.

### 7.5 AI-assisted Match Review (the bridge between auto-discover and CSV)

When a customer uploads a CSV and Vera has auto-discovered
placeholders (e.g., `hosp_8h2nf`), Vera runs three-pass match:
1. Exact tenant_id (deterministic)
2. Fuzzy tenant_id (Levenshtein + substring)
3. AI-assisted (Haiku-class LLM compares display_name, email
   domain, jurisdictions, traffic patterns)

LLM returns suggested matches with confidence + reasoning. User
approves or rejects each. **No silent merges.** Cost: ~$0.02-0.05
per CSV upload event. On-demand only, not runtime.

### 7.6 Terminology: Customers (not Hospitals) — UI generalization

User's instruction: in the UI, always say "Customers" so it
generalizes across verticals (medtech → hospitals, lending → banks,
hiring → employers). Unambiguous in context because the user is
always logged in as their own org.

Internal data model: `tenant_id` (SDK), `Customer` entity. Specific
names (Cleveland Clinic, Abridge) stay as proper nouns. Medtech-
specific prose (HIPAA chain analysis, AI scribe use cases) keeps
"hospital" when discussing the vertical.

### 7.7 HITL: in-app webhook is the default

The reviewer is the practitioner (Dr. Smith), who has clinical
authority over the patient. Dr. Smith is **not** Vera's user — no
Vera account, no Vera dashboard login. Cleveland Clinic doesn't
know Vera exists (Vera is a Subcontractor BA under Abridge's BAA).

So the review must happen **inside the customer's product**
(Abridge's app), branded as Abridge, rendered in the workflow Dr.
Smith already uses. Vera POSTs a webhook with review context;
customer's product surfaces the prompt; customer POSTs decision
back with identity + credential attestation.

**Vera is invisible to the practitioner.** Feature, not bug.

Channels in v1:
- **In-app webhook (default for medtech)** — Vera invisible
- **Slack** — for solo practitioners or compliance team
- **Vera dashboard** — for compliance officer batch oversight

v2 adds: embedded Vera review widget (React component) for
customers wanting Vera-controlled UI timing.

### 7.8 Reviewer roster: derived, not pre-registered

User pushed back on my pre-registered reviewer roster: "if the
agent is going to bring a HITL, whoever is using the agent will end
up reviewing right?"

**My partial pushback:** roster isn't pre-registered, but Vera DOES
validate credentials passed in the callback. If a gate requires DEA
(for Schedule II), Vera rejects callbacks attesting only MD without
DEA. Credentials check is at attestation time, not registration time.

**Resolution:** reviewer list is a derived view ("active reviewers
in last 30 days"), populated from real callbacks. No upfront roster
to manage. Vera validates the role match at attestation.

### 7.9 Standing notice (v1), not per-decision (v2)

For affected persons (patients), v1 ships a **standing AI-use
disclosure** delivered once at enrollment via the hospital's
existing channels (MyChart, paper intake, verbal). Per-patient
attestation captured via customer webhook callback.

Per-decision notice (EU Art. 26(11) style — "this specific decision
was AI-assisted") is **v2/EU pack**, not v1. Per-decision delivery
requires notice infrastructure specific to each hospital's stack
and is overkill for US Federal medtech.

State patchwork (CA AB 489, TX TRAIGA healthcare, UT AIPA) handled
via conditional clauses in the standing notice template based on
the customer's declared state footprint.

### 7.10 Compliance Posture (renamed from "Score"), universal across packs

Initially I pushed back on a "compliance score" as vanity metric.
User insisted with specific criteria: violations, severity,
normalized to /10, AI insights for improvements.

**Final design:** six universal dimensions, deterministic formula,
no LLM in score math, AI insights on-demand with disclaimer
"recommendations not regulatory advice."

| Dimension | Weight | Universal across packs |
|---|---|---|
| Artifact freshness | 20% | Required artifacts current + unexpired |
| HITL completion | 25% | Decisions requiring HITL that received it pre-commit |
| Reviewer integrity | 15% | HITL events meeting threshold + correct credentials |
| Notice delivery rate | 10% | Required notices delivered |
| Chain integrity | 20% | Period with no hash-chain validation failures |
| Workflow timeliness | 10% | Post-action workflows completed within statutory deadlines |

Per-pack inputs declared by each pack (Medtech: BAA + HIPAA RA + Section 1557; Lending: ECOA model docs + Fair Lending Policy; etc.).

**Why "Posture" not "Score":** compliance is a legal status
determined by regulators; posture is what Vera observes at runtime.
Legal distinction — Delve guardrail.

Dimension minimums (low-volume guard): each dimension requires
≥N data points before computing. Below minimum = "insufficient data"
not a misleading number.

AI insights: on-demand only, Haiku-class LLM, ~$0.02-0.05 per
insight generation, framed as recommendations.

### 7.11 Zero runtime LLM calls (v1 default)

Compliance gates are **deterministic predicates** over structured
fields. Three medtech scenarios proven without LLM:

1. **AI scribe → chart entry:** structured field check (`new_diagnoses`
   non-empty? → HITL; DEA Schedule lookup on `new_medications`? → HITL+DEA)
2. **AI receptionist → scheduling:** intent enum check + disclosure
   timestamp check
3. **Prior-auth → denial:** reason_code taxonomy validation + amount
   threshold

**Customer responsibility:** domain classification (e.g., "is this
chest pain a clinical emergency?"). **Vera responsibility:**
structural compliance (was reason captured? did HITL happen? was
log signed?). Mixing them puts Vera in the medical-liability chain.

**Optional LLM uses (off by default or batch):**
- Free-text → structured extraction (opt-in, ~$0.001/call,
  Haiku-class)
- Compliance Posture insights (on-demand)
- Drift / anomaly detection (batch, v2)
- PDF narrative polish (batch, ~$0.02/PDF)

Frontier LLM never needed — Haiku-class sufficient.

### 7.12 Real-time mode for voice agents

Voice agents (AI receptionists) can't tolerate 100-1500ms gate
latency on a phone call. Real-time mode: deterministic gates run
inline; HITL becomes deferred post-action review.

Trade-off: loses pre-action HITL enforcement. Audit PDF explicitly
labels "12 decisions reviewed post-action (real-time mode)."
Regulator sees the trade-off; customer must justify why real-time
was operationally required. **Big Law opinion should specifically
address whether deferred review meets Section 1557 reasonable-
efforts when latency is sub-second-critical.**

### 7.13 Off-Vera checkpoint mechanism

Architectural answer to "what if Vera shuts down":

1. Daily KMS-signed checkpoint of hash-chain head
2. Pushed to **customer-controlled S3** (customer owns the data)
3. **Anchored to OpenTimestamps** (Bitcoin blockchain, free public
   service, no Vera dependency)
4. Verification: `vera verify --offline` works without contacting
   Vera

Removes "what if you shut down" procurement objection. Audit trail
genuinely outlives Vera. Engineering: ~5 days, ships in v1.

### 7.14 Cost model (no runtime LLM = beautiful unit economics)

Per-customer monthly total (at 1M actions/month, 5% HITL rate):

| Component | $ |
|---|---|
| Runtime compute | 1.00 |
| HITL routing | 0.10 |
| Artifact generation (ReportLab, deterministic) | 0.25 |
| Storage (12 months hot retention) | 0.50 |
| Infra overhead | 5.00 |
| Customer support / human-ops allocation | 25.00 |
| **Total marginal** | **~$32/month** |

At $50-150K ACV → **gross margin 99%+**.

Bottleneck at scale isn't compute — it's customer support burden
on compliance questions, BAA admin, and the growing Big Law opinion
library.

### 7.15 Sandbox vs. production split

`al_test_*` keys (sandbox: synthetic data, no BAA required) vs.
`al_live_*` keys (production: real PHI, BAA between Vera and
customer org required).

Customer can develop and test before BAA is signed; production
unlocks after BAA execution.

### 7.16 Branding (logo upload in Settings)

User confirmed: logo upload lives in Settings → Branding section.
If user picks "Your logo" in PDF generation modal without having
uploaded, inline prompt links to Settings → Branding.

PDF modal has three branding options:
- Your logo (recommended) — default
- Co-branded (customer + audit target)
- No branding (Vera technical appendix only)

### 7.17 BAA renewal flow

Triggered from: Home banner (≤30 days), Customers list flag, Customer
detail status banner, blocked PDF gen, email at 90/30/7 days.

Modal options:
1. Upload new signed BAA (default, ships v1)
2. Send Vera template via DocuSign (v2)
3. Defer 14 days (honest acknowledgment that negotiations are slow)

### 7.18 What we don't build (v1 explicit exclusions)

- No pre-registered reviewer roster
- No PDF preview in modal (direct download)
- No decision search within a customer (defer to v2 when volume justifies)
- No charts/graphs (compliance officers want yes/no)
- No real-time decision streaming (refresh on page load)
- No in-dashboard messaging (use Slack)
- No customizable dashboard layout
- No dark mode in v1
- No mobile optimization (responsive but not mobile-first)
- No 3-column iconed-circle "SaaS slop" feature grids
- No customer-authored predicates (DSL is v3+)
- No multi-pack composition in v1 (one medtech pack only)
- No per-action gate overrides in v1 (v2 with audit trail)

---

## 8. The 26 operational edge cases (categorized)

Surfaced during /grill-with-docs. Documented with architectural
responses in Appendix E of north-star doc.

**Identity and tenancy** (7):
- PHI in tenant_id (regex validation + entropy red-flag)
- Typo in tenant_id (placeholder + 7-day warning + admin merge action)
- tenant_id changes after merger (manual merge v1; aliasing v2)
- Missing tenant_id at runtime (lenient default; strict opt-in)
- Sandbox vs. production split (test_/live_ keys)
- Customer uses Vera through multiple AI vendors (each vendor = separate Vera tenant; v3 cross-vendor portal)
- AI-assisted CSV match against auto-discovered placeholders

**Runtime and gates** (5):
- Voice/latency-critical workflow (real-time mode opt-in)
- Free-text outputs (Haiku-class extraction helper, opt-in)
- False-positive gate (pinned versions + 48h SLA on reports)
- Customer wants to override a gate (v2 with audit-trail justification)
- Customer wants custom predicates (v3+ YAML DSL)

**HITL and webhooks** (7):
- Webhook endpoint down (exponential backoff 1m → 24h → abort)
- Race: two reviewers approve (idempotent on review_id, first wins)
- Review expires (`review.expired` webhook, action stays PENDING_REVIEW)
- Credentials mismatch (HTTP 403, rejection logged)
- Reviewer rubber-stamps (`reviewed_below_threshold: true` flagged)
- Reviewer revokes after approval (chain is immutable; corrective action)
- Customer wants tighter UI control (v2 embedded Vera review widget)

**Chain integrity and verifiability** (4):
- DB restore from older backup (detect on next write, recover from KMS checkpoint or OpenTimestamps)
- KMS key compromised (immediate rotation, retained old key, OT anchors immutable)
- Vera shuts down (off-Vera S3 + OpenTimestamps — survives)
- Customer disputes posture / chain finding (auditable math, cryptographic verification)

**Posture** (4):
- Low-volume distortion (per-dimension minimums)
- Posture gaming via omission (audit PDF enumerates should-fire vs did-fire)
- Posture drops overnight after pack update (email + diff explanation, 30-day grace)
- Insights LLM unavailable (graceful fallback, no crash)

**Onboarding ergonomics** (5):
- 50 customers at signup (CSV + AI Match Review)
- CRM sync (API connector v2)
- 50-row CSV with 3 errors (partial commit + downloadable error CSV)
- BAA expires during active review (accept completion; block new actions)
- Fake BAA PDF uploaded (Vera doesn't validate content; customer on the hook; v2 DocuSign integration)

**Multi-vertical and scale** (3):
- Customer ships multiple packs (v2)
- 1000+ customers per Vera org (sharding v3)
- Multi-region for EU residency (Frankfurt + Dublin, v2 with EU pack)

---

## 9. Sequencing — six waves

**Wave 1 — MVP (8 weeks)** — Medtech wedge. AI scribes. One pack.
Off-Vera checkpoint ships now.

**Wave 2 — Months 3-6 (during YC batch + EU Aug 2 deadline)** —
Medtech state overlays (CA, TX, IL), Lending pack (ECOA + EEOC),
EU AI Act pack, Workflow engine, Scheduler, NIST AI RMF posture
renderer, BAA DocuSign integration.

**Wave 3 — Months 6-12** — Employment pack (NYC AEDT + IL HB 3773),
California stack (CPPA ADMT, SB 942, SB 1001, SB 53), Texas TRAIGA,
Connecticut SB 5 (if enacted), API connectors, Predicate DSL v1
(power users), Decision search, Cross-vendor customer portal.

**Wave 4 — Months 12-24** — FDA PCCP + ONC HTI-1, FINRA + SEC,
Insurance underwriting (NAIC), ISO 42001 SoA renderer, Full EU
Conformity Package PDF, Multi-region EU deployment, PDF preview.

**Wave 5 — Months 18-36 (Act 2 begins)** — Customer opt-in to
anonymized aggregate data, first carrier data-licensing deal
(Armilla / AIUC / Testudo), risk-scoring API private beta,
co-marketing with carrier endorsements.

**Wave 6 — Months 30+** — MGA operation OR strategic acquisition by
major reinsurer OR continued independent data-network operation.

---

## 10. The 8-week MVP shipping plan (Wave 1)

**Weeks 1-2 — Core engine extension** (mostly existing code):
- Add 5 fields to ActionRecord (jurisdiction, domain, use_class,
  action_class, reason_codes) — metadata blob for v1 to avoid
  schema churn
- New `pre_action_gate` endpoint: `POST /v1/gates/evaluate`
- New `ClinicalScribePack` Python module
- Webhook delivery for review-complete / -expired / -escalated
- **Off-Vera checkpoint mechanism** (KMS daily checkpoint → customer
  S3 + OpenTimestamps; ~5 days engineering)

**Weeks 3-4 — SDK + integrations:**
- `@vera.gate` decorator update for sync ruling handling
- `vera.PendingReview`, `vera.PolicyBlock` exception classes
- Slack channel routing
- In-app webhook channel
- CLI: `vera verify`, `vera review-status <id>`
- HIPAA Safe Harbor redaction schema as default

**Weeks 5-6 — Frontend:**
- Onboarding wizard (5 questions + 3 customer-population paths)
- Coverage map dashboard (single page)
- Review queue UI (for dashboard-channel reviewers)
- "Generate HIPAA AI Audit Trail" button → ReportLab PDF
- Templates section (HIPAA Risk Analysis skeleton, Section 1557
  Policy, red-banner-on-every-section design)

**Weeks 7-8 — Legal + GTM:**
- **Big Law HIPAA opinion engagement signed in Week 1** (lands
  Week 12-16; not gating v1 ship)
- Publish NIST AI RMF mapping document (free trust artifact)
- BAA template finalized, e-sign workflow live
- 3 paid pilot conversations
- YC application submitted (already done in this conversation)

---

## 11. The 4-page dashboard IA

User confirmed 4 nav items, no more:

| Page | Why it exists |
|---|---|
| **Home** | Daily 30-second check + procurement-PDF shortcut + compliance posture chip |
| **Customers** | Multi-tenant first-class; per-customer BAA, reviewers, decisions, PDFs |
| **Compliance** | Org-wide attestations (HIPAA RA, Section 1557 Policy, AI Tool Inventory, NIST RMF posture, Standing Notice Templates) + Compliance Posture surface |
| **Settings** | Agents, API keys, team, billing, **branding (logo upload)**, pack config |

Hospitals/Banks/Employers are first-class nested entities under the
customer's Vera org. Per-customer:
- BAA + status
- Reviewers (derived from callbacks)
- Patient/affected-person notice attestations
- Decisions stream
- Generated audit PDFs (history)

Aggregate views still exist (across all customers).

---

## 12. The design system (light + minimal + OpenAI-like)

Visual language unified across marketing and dashboard surfaces:

**Foundational tokens (shared):**
- Paper: `#FEFAF3` warm cream
- Paper-2: `#F5EFE3` (cards)
- Paper-3: `#EDE5D2` (table headers, hover)
- Ink: `#1F1610` (text, primary button bg)
- Ink-2: `#57514D` (secondary text)
- Ink-3: rgba(31,22,16,0.45) (tertiary)
- Ink-4: rgba(31,22,16,0.14) (borders)
- Petrona 400 for display (page titles)
- Inter 400/500/600 for body/UI
- No emerald, no purple, no gradient

**Dashboard-specific:**
- Denser spacing (32-48px section gaps vs 96-160px landing)
- Status colors: olive `#3E5C3B` / amber `#9C6A1D` / brick `#7A2E1F`
- Sidebar + content (default), or + right panel (split work)
- ~20 components specified with anatomy (Sidebar, ProjectSwitcher,
  UserChip, TopBar, Breadcrumb, PageHeader, Button, Toggle,
  IntegrationCard, RecommendationCard, SeverityBadge, StatusDot,
  Table, Modal, Form fields, Avatar, **CollaborationCursor**,
  **Comment + InlineHighlight**, **AI Chat panel**, DocumentIcon,
  EmptyState, Spinner, ProgressBar, Tooltip)
- Aesthetic reference: **OpenAI platform console** — light, minimal,
  generous whitespace, calm

User shared 5 screenshots (Novera-class contract-management product)
that anchored the visual language extraction.

---

## 13. The five documents (state as of May 22, 2026)

| Doc | What it covers | PR | Status |
|---|---|---|---|
| [policy-engine-mvp.md](policy-engine-mvp.md) | The 8-week v1 ship plan: medtech wedge, three gates, customer identification, HITL invocation, posture, cost model | [#178](https://github.com/Ad0420/Agent_Compliance/pull/178) | merged |
| [dashboard-design.md](dashboard-design.md) | Dashboard UX: 4-page IA, wireframes for Home/Customers/Compliance/Settings, supporting flows (Generate PDF modal, Decision detail, BAA renewal, AI Match Review, empty state), copy decisions | [#179](https://github.com/Ad0420/Agent_Compliance/pull/179) | merged |
| [policy-engine-north-star.md](policy-engine-north-star.md) | 12-24 month architecture: chain Vera serves, four moats, six surfaces, seven primitives, pack catalog at scale, artifact renderer matrix, Act 2 insurance evolution, six-wave sequencing, 26 operational edge cases | [#180](https://github.com/Ad0420/Agent_Compliance/pull/180) | merged |
| [landing-design.md](landing-design.md) | Marketing surface design system (renamed from DESIGN.md); typography, color, spacing, motion, voice for landing/regulations/marketing pages | [#181](https://github.com/Ad0420/Agent_Compliance/pull/181) | open / green |
| [dashboard-design-system.md](dashboard-design-system.md) | Dashboard visual tokens + component library; ~20 components with anatomy + tokens; implementation notes (CSS custom properties, file structure, icon library, font loading, a11y) | [#182](https://github.com/Ad0420/Agent_Compliance/pull/182) | open / green |

---

## 14. User opinions, approvals, denials — synthesis

**Approved (with no pushback or after my reasoning):**
- Medtech-first pivot (user originated this)
- "Auditable" not "compliant" framing
- The chain-of-trust premise
- Four-moat framework
- In-app webhook as default HITL channel
- Standing notice (v1) vs per-decision (v2)
- "Customers" terminology (UI generalization)
- AI-assisted CSV Match Review with explicit approve/reject
- Reviewer roster derived from callbacks (not pre-registered)
- Logo upload in Settings; inline prompt during PDF gen
- BAA renewal modal with three options
- Direct PDF download (v1; preview deferred)
- No decision search in v1
- The 4-page dashboard IA
- The 5-doc structure
- OpenAI-platform-console aesthetic
- Off-Vera checkpoint mechanism (audit trail outlives Vera)
- Sandbox vs production key split
- Real-time mode for voice agents (with clear audit labeling)

**Denied / pushed back:**
- My initial lending-first vertical pick → **user pivoted to medtech**
- My pushback that "bulk upload is unnecessary if middleware
  auto-detects" → **user kept both, asked me to surface real
  scenarios for CSV — I did, accepted my partial pushback**
- My pushback that "compliance score is a vanity metric" → **user
  insisted with criteria; I renamed to "Posture" + designed
  deterministic formula + AI insights with disclaimer**
- My all-Slack default HITL channel → **user implicitly corrected
  by asking about practitioner reviewing — I switched to in-app
  webhook default**
- Pre-registered reviewer roster → **user pushed back; I dropped
  registration but kept credential validation at attestation time**

**User added beyond my initial recommendations:**
- Compliance posture with AI-generated insights
- AI-assisted Match Review for CSV vs auto-discovered
- "Customers" generic terminology throughout UI
- Custom branding upload + co-branded PDF option
- Defer renewal option in BAA renewal flow
- Explicit dashboard design system separate from wireframes
- OpenAI as the visual reference for dashboard

**Tensions surfaced but not fully resolved:**
- Real-time mode loses pre-action enforcement — does this satisfy
  Section 1557 "reasonable efforts" when latency is sub-second?
  → **Big Law opinion should explicitly address this**
- Posture gaming via omission — workflow timeliness shows 10/10 if
  customer skips workflows entirely. **Need to refine in v1.1
  once we see real customer behavior.** Audit PDF enumerates
  should-fire vs did-fire as the regulator-facing safeguard.
- The "deferred-review" mode complicates the clean pitch ("every
  decision reviewed before commit" → "...sometimes before, sometimes
  after"). Honest trade-off worth surfacing to early customers.

---

## 15. Open offers — not yet executed

These were offered but the user didn't pick:

- **Big Law engagement brief** — draft engagement letter for the
  HIPAA opinion ($30-60K, 3-6 months)
- **OCR-investigator-facing PDF template sketch** — sections in
  OCR's checklist order with sample paragraphs
- **Off-Vera checkpoint mechanism spec** — technical detail of
  KMS + S3 mirror + OpenTimestamps anchoring
- **Wizard onboarding flow at full fidelity** — the 5 questions,
  the SDK install moment, the three customer-population paths
- **`frontend/components/dashboard/` stub** — empty file scaffolding
  matching the component library, so engineering has a build target

Any of these are still pickup-able in future sessions.

---

## 16. Key links and references

**Internal:**
- [strategy.md](strategy.md) — product strategy, Act 1 + Act 2
- [regs.md](regs.md) — current regulations page content
- [use_cases.md](use_cases.md) — 7 medtech use cases
- [README.md](README.md) — repo overview
- [BETA_ONBOARDING.md](BETA_ONBOARDING.md) — beta customer flow
- [mvp-hardening-plan.md](mvp-hardening-plan.md) — engineering roadmap
- [backend/app/services/policy_engine.py](backend/app/services/policy_engine.py)
- [backend/app/services/hashing.py](backend/app/services/hashing.py)
- [backend/app/services/chain.py](backend/app/services/chain.py)
- [backend/app/models/action_record.py](backend/app/models/action_record.py)
- [sdk/vera/](sdk/vera/) — current SDK surface

**External (regulations):**
- [EU AI Act (Reg. 2024/1689)](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)
- [Colorado SB 24-205](https://leg.colorado.gov/bills/sb24-205) +
  [SB 26-189](https://leg.colorado.gov/bills/sb26-189)
- [NYC DCWP AEDT](https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page)
- [CPPA Final ADMT Regulations](https://cppa.ca.gov/announcements/2025/20250923.html)
- [HHS Section 1557 Final Rule](https://www.federalregister.gov/documents/2024/05/06/2024-08711/nondiscrimination-in-health-programs-and-activities)
- [FDA PCCP Final Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/marketing-submission-recommendations-predetermined-change-control-plan-artificial-intelligence)
- [CFPB Circular 2022-03](https://www.consumerfinance.gov/compliance/circulars/circular-2022-03-adverse-action-notification-requirements-in-connection-with-credit-decisions-based-on-complex-algorithms/)
- [EEOC Title VII Technical Assistance](https://www.eeoc.gov/laws/guidance/select-issues-assessing-adverse-impact-software-algorithms-and-artificial-intelligence)
- [NIST AI RMF 1.0](https://www.nist.gov/itl/ai-risk-management-framework)
- [OpenTimestamps](https://opentimestamps.org/)
- [ISO/IEC 42001:2023](https://www.iso.org/standard/42001)

---

## 17. Cross-conversation principles (user's standing preferences)

Extracted from interaction patterns; these should govern future
sessions:

- **No clarifying questions.** Make the reasonable call and continue.
  If wrong, user redirects.
- **Skip the gstack preamble** (telemetry / sessions / learnings
  discovery bash blocks) unless explicitly invoked.
- **Substance over ceremony.** Don't pad findings, don't invent
  issues to look thorough, don't soften with "could potentially" —
  say what's wrong and how to fix it.
- **Push back when warranted.** User explicitly says "contest me
  without fear" when they want it. Honest disagreement > false
  agreement.
- **Save artifacts to disk** as named .md files in the repo root —
  user's established pattern (strategy.md, use_cases.md, etc.).
- **Cross-link docs** with markdown links so navigation works in
  GitHub.
- **PR convention:** kebab-case branch names (docs/foo-bar),
  Co-Authored-By trailer in commits, clear PR body with test plan
  checklist.
- **CI is path-filtered** to specific directories — docs-only PRs
  trigger 9 generic checks that all pass quickly. Don't be surprised
  by check counts.
- **Wait for CI to be green** before reporting PR complete (user's
  CLAUDE.md rule). Use Monitor with `gh pr checks` polling.

---

## 18. TL;DR for a future session

If you're reading this fresh in a new conversation:

1. **Read [strategy.md](strategy.md) and [regs.md](regs.md) first.**
   They give the existing product story + regulatory landscape.
2. **Read [policy-engine-mvp.md](policy-engine-mvp.md) for the v1
   ship plan.** This is what gets built in the next 8 weeks.
3. **Read [policy-engine-north-star.md](policy-engine-north-star.md)
   for the 12-24 month architecture.** Read the four-moats and
   chain-of-trust sections at minimum.
4. **Read [dashboard-design.md](dashboard-design.md) for IA +
   wireframes,** then [dashboard-design-system.md](dashboard-design-system.md)
   for component-level visual specs.
5. **Read [landing-design.md](landing-design.md)** for the marketing
   visual system (foundational tokens shared with dashboard).
6. **This file** is the why behind those docs — every decision, every
   pushback, every deferral.

The core architectural insight to keep in mind: **Vera serves a chain,
not a customer.** Every product decision flows from "which tier of
the chain consumes this artifact?" The PDF is the regulator's
artifact (Tier 1). The dashboard is the conduit's artifact (Tier 3).
The standing notice is the affected person's artifact (Tier 7).
Vera itself (Tier 4) is invisible to everyone except the conduit.

The next session's likely starting point is one of:
- Big Law engagement brief
- OCR PDF template sketch
- Off-Vera checkpoint mechanism spec
- Wizard onboarding flow detail
- frontend/components/dashboard/ scaffolding

Or something entirely new the user surfaces. This context loader
covers everything decided up to May 22, 2026.
