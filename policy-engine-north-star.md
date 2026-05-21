# Vera Policy Engine — North Star Architecture

**The 12-24 month destination. The thing the MVP grows into.**
**Last updated:** 2026-05-19
**Pairs with:** [policy-engine-mvp.md](policy-engine-mvp.md) (the v1 ship plan)

---

## How to read this document

This is the architectural destination. It is **not** what we build in v1.
The v1 cut is in [policy-engine-mvp.md](policy-engine-mvp.md) — one vertical,
one regulation stack, one PDF, eight weeks.

This document answers a different question: *given that the MVP works, what
do we grow it into, and why?* The answer is shaped by one architectural
premise that the MVP made explicit:

**Vera serves a chain, not a customer.**

Every primitive below is contextualized within that chain. Every product
decision flows from "who at which tier of the chain is the consumer of
this artifact?" The MVP applies this principle to one vertical (medtech)
and one regulator (HHS OCR). The North Star applies it to every regulated
vertical, every jurisdiction, every audit consumer — including the
insurance carriers who become the Act 2 data customer.

If you read one section, read **The chain Vera serves** and **The four
moats**. Those two sections together justify everything else.

---

## The chain Vera serves (the architectural premise)

Vera's product is not consumed by Vera's customer. Vera's customer is the
**conduit** through which Vera's evidence flows up a chain to the actual
audit consumer, while delivering value to several intermediate participants
along the way.

```
                                                              (audit consumer)
Regulator / Auditor ──────────────────────────────────────────────────────┐
   (HHS OCR, state AG, EU MSA, CFPB, EEOC, accrediting bodies)            │
                                                                          │
asks for evidence ↑                                                       │
                                                                          ▼
Audit Target ──────────────────────────────────────────────────  (value recipient)
   (Hospital, bank, employer, insurer — the entity facing                 │
    direct regulatory liability)                                          │
                                                                          │
"show me audit logs / impact assessments / bias audit / explanation"      │
                                                                          ▼
Vera Customer (the conduit) ─────────────────────────────────────  (the relationship)
   (AI vendor — scribe, lender, ATS, voice agent — whose product          │
    operates inside the audit target's environment)                       │
                                                                          │
ships SDK, signs BAA / DPA, owns identity, brands artifacts               │
                                                                          ▼
Vera (the substrate) ─────────────────────────────────────────────  (audit substrate)
   (Runtime policy engine, hash chain, KMS, off-Vera checkpoints,         │
    pack catalog, artifact renderers)                                     │
                                                                          ▼
                                                              (Act 2 data consumer)
Insurance Carrier (future) ───────────────────────────────────────────────┘
   (Aggregate behavioral telemetry → underwriting dataset →
    data licensing / MGA / strategic acquisition)
```

This is the architectural premise. Every product decision asks: **at which
tier does this artifact get consumed?** The PDF is regulator-tier. The
dashboard is conduit-tier. The standing notice is patient-tier. The
behavioral telemetry rollup is carrier-tier (Act 2).

If we get the tier wrong, we build the wrong product. If we get it right,
every artifact has one obvious consumer and one obvious format.

---

## Working backwards: the value at each tier

### Tier 1 — The Regulator (the audit consumer)

What they need: **verifiable evidence** that the audit target met its
regulatory obligations.

What Vera produces for them:
- Audit-consumer PDF, one format per regulation (HIPAA AI Audit Trail, EU
  Conformity Package, NYC AEDT Public Summary, FINRA WORM Archive, ECOA
  Reg B adverse-action substantiation file)
- Cryptographic verification independent of Vera's continued existence
  (off-Vera checkpoints + public timestamping)
- Plain regulatory English, citations to the underlying statute or rule
- BAA / DPA chain traceability — they can see how data flowed and who
  signed what

What Vera does **not** produce for them:
- Compliance certifications. Vera is not a certifying body.
- Legal opinions. Vera commissions opinions from Big Law (see Tier-3 value).
- Domain-specific safety judgments (was this a medical emergency, was this
  a discriminatory loan decision). Vera produces evidence; the regulator
  judges.

### Tier 2 — The Audit Target (the value recipient)

The entity facing direct regulatory liability. The hospital, the bank, the
employer, the insurer. They don't pay Vera directly — they receive value
*through* the conduit (Vera's customer).

What they need: **defensibility**. When the regulator asks, they need to
answer with evidence in 90 seconds, not 90 days.

What Vera produces for them (delivered via the conduit):
- The audit-consumer PDF, white-labeled with the conduit's branding
- Liability shield via correct BAA chain (Subcontractor BA model under HIPAA;
  Sub-processor under GDPR; analogous structures elsewhere)
- Procurement signal — they can answer "does this AI vendor have audit
  infrastructure?" in their diligence
- Patient / customer disclosure trail (standing notice + per-decision
  notice in EU pack)

The audit target rarely sees Vera directly. They see *their AI vendor*
doing the responsible thing. Vera is the substrate; the conduit's brand is
on the artifact.

### Tier 3 — The Vera Customer (the conduit — the relationship Vera owns)

The AI vendor. AI scribe, AI receptionist, AI lender, AI ATS, AI prior-auth
agent. They have the BAA / DPA chain into the audit target. They ship the
product the audit target's users actually use. They are Vera's contractual
customer and revenue source.

What they need:
- **Procurement unblock** — they want to win deals with audit targets who
  ask "show me your AI audit infrastructure." Without Vera, they stall;
  with Vera, they close.
- **Liability reduction** — when their AI tool is named in a regulator
  investigation, Vera's evidence chain is their defense.
- **Engineering simplicity** — `pip install vera`, decorator, done. Their
  engineers don't want to rebuild compliance infrastructure.
- **White-labelable artifacts** — they hand the PDF to their customer
  branded as themselves, not as Vera.
- **Verifiability independent of Vera's existence** — they need to
  reassure their customers that audit logs survive Vera shutting down.

What Vera produces for them:
- The SDK + decorator + framework integrations
- The pack catalog (opinionated bundles per vertical+jurisdiction;
  customers do not author predicates)
- The dashboard (their compliance team's daily ops surface)
- The artifact renderers (one click → PDF, customer-white-labelable)
- The BAA / DPA / sub-processor agreements

What Vera does *not* expose to them:
- The predicate engine internals. They install opinionated packs.
- The hash chain primitives. They get verification commands.
- The translation library source code. That's Vera's moat.

### Tier 4 — The Reviewer (the human in the loop)

A physician, loan officer, recruiter, RCM lead. They have **authority** over
the decision. They are the customer's customer's user. They are not Vera's
user — they don't have a Vera account, they sign in through the conduit's
product.

What they need:
- A clear "this AI decision needs your review" prompt
- Enough context to make a defensible decision
- Approve / modify / reject affordance
- Audit trail of their own decision (because they may later be questioned)

What Vera produces for them: **nothing visible.** Vera fires a webhook to
the conduit. The conduit renders the review prompt inside its existing
product UI. The reviewer reviews. The conduit attests the reviewer's
identity back to Vera. Vera signs the chain.

**Vera is invisible to the reviewer. That's a feature.**

### Tier 5 — The Affected Person (the patient, applicant, candidate)

The patient whose chart was AI-assisted. The applicant whose loan was
denied. The candidate ranked by an AEDT. They are the subject the
regulation exists to protect.

What they need (varies by jurisdiction):
- Standing disclosure that AI was used (CA AB 489, TX TRAIGA, UT AIPA,
  EU Art. 26(11))
- Per-decision notice for high-risk decisions (EU Art. 26(11), Colorado
  adverse-outcome statement, ECOA adverse-action notice with specific
  reasons)
- Right to appeal / right to correct underlying data / right to
  explanation
- Watermark / provenance on AI-generated content affecting them (CA SB 942,
  EU Art. 50(2))

What Vera produces for them: **nothing directly.** Vera triggers the
notice obligation through the conduit. The conduit surfaces it to the
audit target. The audit target delivers through their existing patient /
customer communication channel (MyChart, mailed letter, in-app banner).
The audit target attests delivery back to Vera through the conduit.

**Vera is invisible to the affected person too.** That's also a feature —
the affected person sees their existing care provider / lender / employer
doing the responsible thing, not a third-party compliance vendor.

### Tier 6 — The Insurance Carrier (Act 2, future)

When Vera sits in the runtime path of every signed agent decision across
hundreds of customers, the aggregate becomes **the most valuable
underwriting dataset in AI insurance.** Strategy doc Act 2.

What carriers need:
- Behavioral telemetry across many AI deployments (not from one carrier's
  audit, but cross-customer)
- Loss-history correlation (which AI patterns precede claims)
- Underwriting signal (real-time risk scoring of AI deployments)
- Per-decision evidence for claims defense

What Vera will produce for them (Wave 5+):
- Anonymized behavioral feeds, opt-in by customer, contractually shared
- Risk-scoring API for underwriting
- Per-decision evidence packages on claims trigger

This is not v1. It's not v2. It is the architectural destination that
explains why every primitive in v1 is built to scale to it. The
hash-chained runtime evidence ledger is a stronger underwriting substrate
than anything the carriers can build themselves — they are insurers, not
SaaS builders, as the strategy doc says.

---

## The four moats

The architecture has exactly four durable assets. Everything else can be
re-implemented by a competitor in months. These four cannot.

### Moat 1 — The runtime substrate

Pre-action gate evaluation at low latency. Hash chain with canonical JSON
serialization. KMS signing infrastructure. Encrypted spool for offline
durability. Webhook delivery with retries and idempotency. Multi-tenant
isolation. SDK plumbing for Python + framework hooks (LangChain, CrewAI,
OpenAI, Anthropic). Off-Vera checkpoint mechanism. Independent
verifiability via OpenTimestamps.

This is 12-18 months of engineering. It has to be right the first time —
retrofitting cryptographic chains onto a system that wasn't designed for
them is a rewrite, not a refactor. A competitor starting today is at
minimum a year behind, and they have to win the same customer trust we
spent that year earning.

### Moat 2 — The regulatory translation library

The pack catalog. Each pack is a Python module encoding:
- Curated reference data (DEA controlled-substance lists, RxNorm mappings,
  ECOA reason-code taxonomies, ICD-10 codes, EEO-1 categories)
- Domain-specific gates with deterministic predicates
- Demographic-stratification logic for disparate-impact monitoring
- Role-credential mappings (MD, DEA, NP, RN, JD, CPA, loan officer)
- Per-jurisdiction conditional clauses
- Citation strings for every gate (regulator-facing)
- White-label-able artifact templates per regulator format

Each pack represents hundreds to thousands of hours of regulatory
research + attorney review + quarterly refresh. Colorado rewrote itself in
2026; the EU AI Act high-risk obligations land Aug 2, 2026; the federal
preemption EO will spawn litigation; states will keep shipping new laws.
**This is the moat that compounds.**

The substrate is replicable. The translation library is the thing that
takes years.

### Moat 3 — The legal opinion stack

One written opinion per major regulation, from a credible Big Law practice:
- Hogan Lovells on HIPAA + Section 1557 (medtech)
- Wilson Sonsini or Cooley on ECOA Reg B (lending)
- Seyfarth Shaw on NYC AEDT + EEOC Title VII (employment)
- Bird & Bird on EU AI Act (EU pack)
- McDermott on FDA SaMD (clinical AI device pack)
- Davis Polk on SEC + FINRA (financial AI pack)

Each opinion costs $30-60K and 3-6 months. Each is opinion-of-Vera —
specific to our architecture, our PDF format, our chain primitives. A
competitor commissions their own; they're a year late, against a
different format, and they have to convince the same customers to swap
out reference artifacts.

The opinion stack is what makes the PDF *evidentiary*. Without it, the PDF
is a Word doc. With it, the PDF is the artifact the regulator accepts.

### Moat 4 — The BAA / DPA / sub-processor chain position

To enter the BAA chain, Vera needs:
- HIPAA security posture (encryption at rest, MFA, breach procedures)
- SOC 2 Type II
- Insurance (cyber, E&O, BA-specific endorsements)
- Operational maturity (incident response runbooks, business continuity)
- Customer references in the BA chain (compounding moat)
- Equivalent posture for GDPR DPA, ISO 27001, FedRAMP (where relevant)

A competitor outside the BAA chain literally cannot see the data needed
to produce the audit PDF. Switching cost for an installed customer is
real — re-negotiating BAAs across their entire customer base is
months of work.

---

## The verifiable substrate (engine architecture)

The core engine is built on five primitives, in order of architectural
dependency:

### 1. The pre-action policy engine

Synchronous intercept of agent actions. Returns a Ruling with effect
(ALLOW / BLOCK / REQUIRE_HITL / REQUIRE_NOTICE / REQUIRE_OPTIN /
REQUIRE_DISCLOSURE / REDACT / WATERMARK / DEGRADE). Composes multiple
gates by strictest-effect dispatch. Deterministic — no LLM calls at
runtime in the default path.

Input: a Context object describing the action, subject, agent, decision
attributes, deployment state.

Output: a Ruling with citation links to the regulations that triggered.

### 2. The hash-chained evidence ledger

Every action produces an ActionRecord. Records are linked in a Merkle-style
hash chain (current implementation: linear SHA-256 chain; v3 may upgrade
to Merkle tree for efficient inclusion proofs). Records contain the
full universal capture schema (Appendix A).

Tamper-evident by construction: changing record N invalidates the hash of
record N+1, which invalidates N+2, and so on.

### 3. KMS signing + off-Vera checkpointing

Daily checkpoint of the chain head, signed by an AWS KMS asymmetric key
under Vera's control. Each checkpoint is:
- Pushed to a customer-controlled S3 bucket (customer-owned, customer-paid,
  customer-retained)
- Anchored to OpenTimestamps (public Bitcoin blockchain timestamping
  service, free)
- Mirrored to a public S3 bucket Vera operates (insurance against
  customer S3 misconfiguration)

Verification mechanism:
- `vera verify <hash>` — online check against Vera's API
- `vera verify --offline` — checks against the customer S3 checkpoint +
  the OpenTimestamps anchor; no Vera contact required

**This is the architectural answer to "what if Vera shuts down."** The
audit trail survives. A regulator three years post-Vera-shutdown can still
verify the chain head against the Bitcoin blockchain.

### 4. The pack interface

Each pack is a Python module conforming to:

```python
class Pack(Protocol):
    pack_id: str
    version: str
    covers: list[RegulationCitation]
    safe_harbor_frameworks: list[FrameworkID]

    def pre_action_gate(self, ctx: Context) -> list[Gate]: ...
    def capture_evidence(self, ctx: Context, ruling: Ruling) -> EvidenceRecord: ...
    def render_artifact(self, format: ArtifactFormat, scope: Scope) -> Artifact: ...
    def required_customer_artifacts(self) -> list[TemplateRef]: ...
    def periodic_obligations(self) -> list[ScheduledObligation]: ...
```

Packs compose. A US lending customer operating in CO with EU users would
install ECOA Reg B pack + Colorado pack + EU AI Act pack. Strictest-effect
dispatch resolves conflicts; evidence renderers produce the union of all
required artifacts.

### 5. The artifact renderer matrix

```
                  Artifact format
              ┌────────────────────────────────────────────
              │ HIPAA  EU       NYC     ECOA    NIST  ...
              │ Audit  Conf.    AEDT    Reg B   AI
              │ Trail  Package  Public  Adv-    RMF
              │        (Ann.IV) Summary Action  Posture
              │
Vertical pack │
──────────────┼────────────────────────────────────────────
Medtech       │   ✓       —       —       —      ✓
Lending       │   —       —       —       ✓      ✓
Employment    │   —       —       ✓       —      ✓
EU AI Act     │   —       ✓       —       —      ✓
Insurance     │   —       —       —       —      ✓
...           │   ...
```

One evidence ledger → many artifact renderers. Each renderer is opinion-
backed (Tier 3 moat) and white-labelable. New regulations add new
renderer rows; new verticals add new pack columns.

This is **capture once, render many** — the moat that compounds with every
new pack.

---

## Compliance Posture — universal framework across packs

Vera's Compliance Posture is **the same six dimensions across every
vertical pack**. The dimensions are derived from the six surfaces of
regulation (Surface 2 → Artifact freshness; Surface 3 → HITL completion
and Reviewer integrity; Surface 4 → Chain integrity; Surface 5 → Notice
delivery rate and Workflow timeliness). The math is universal; the
inputs are per-pack.

| Dimension (universal) | What it measures | Surface |
|---|---|---|
| **Artifact freshness** | % of required artifacts current and unexpired | Surface 2 |
| **HITL completion** | % of decisions requiring HITL that received it before commit | Surface 3 |
| **Reviewer integrity** | % of HITL events meeting threshold + correct credentials | Surface 3 |
| **Notice delivery rate** | % of required notices delivered | Surface 5 |
| **Chain integrity** | % of period with no hash-chain validation failures | Surface 4 |
| **Workflow timeliness** | % of post-action workflows completed within statutory deadlines | Surface 5 |

### Per-pack inputs (declared by each pack)

```python
class Pack(Protocol):
    def posture_inputs(self) -> PostureInputs:
        return PostureInputs(
            required_artifacts=[...],     # → Artifact freshness
            hitl_gates=[...],             # → HITL completion
            reviewer_thresholds={...},    # → Reviewer integrity
            credential_requirements={...}, # → Reviewer integrity
            required_notices=[...],        # → Notice delivery rate
            timed_workflows=[...],        # → Workflow timeliness
        )
```

Examples across verticals:

| Pack | Required artifacts | Required notices | Timed workflows |
|---|---|---|---|
| Medtech | BAA, HIPAA RA, Section 1557 Policy, NIST RMF | Patient AI disclosure (standing) | Section 1557 disparate-impact report |
| Lending | ECOA model docs, Fair Lending Policy, NIST RMF | ECOA adverse-action notice (per decision) | ECOA 30-day, FCRA dispute, CFPB 1071 |
| Hiring (NYC AEDT) | Bias audit (independent), data retention policy | Candidate 10-business-day notice | Annual bias audit cycle |
| EU AI Act high-risk | FRIA, declaration of conformity, technical doc | Affected-person notice (Art. 26(11)), AI-interaction disclosure (Art. 50) | Serious-incident report (2/10/15 days) |

One posture algorithm. Many vertical inputs. The framework grows with
each new pack; the customer-facing experience stays consistent.

---

## The six surfaces (each regulation decomposes into the same six)

Every AI regulation Vera must enforce decomposes into the same six
surfaces of obligation. Recognizing this is what makes the engine general
without making it generic.

### Surface 1 — Scope test
*Does this regulation apply to this action, this subject, this system,
today?* Function of jurisdiction × domain × use class × role × size
threshold. Each pack runs its own scope test in parallel; the engine
unions the applicable regulations per decision.

### Surface 2 — Pre-deployment artifacts
*What documents must exist and be current before the agent is allowed to
act at all?* FRIA, impact assessment, bias audit, risk-management policy,
BAA, PCCP, technical documentation, declaration of conformity, public
statement. Each is an Artifact in the registry with type, version,
validity window, origin (`vera_generated_evidence` / `customer_signed_template`
/ `independent_auditor_uploaded`).

**The Delve guardrail lives here.** Origin distinguishes runtime evidence
(safe to auto-generate) from organizational attestations (require
customer + counsel review, red-banner templates, never auto-signed).

### Surface 3 — Per-action runtime gates
*What must be true at the moment the agent is about to act?* The
synchronous intercept point. Hard blocks (Art. 5 prohibited practices,
TX TRAIGA categorical bans, FDA out-of-scope modifications), notice
gates, HITL gates, opt-out checks, artifact freshness checks, watermark
application. Strictest-effect dispatch when multiple gates fire.

### Surface 4 — Per-action evidence capture
*What must be recorded about each decision so a regulator can later
reconstruct what happened?* Universal capture schema in Appendix A.
Captured at decision time, hash-chained, signed.

### Surface 5 — Post-action workflows
*What must happen after the agent acts?* Adverse-action notices (ECOA
30-day clock), right to appeal / correct / explain (Colorado, EU Art. 86),
affected-person notice (EU Art. 26(11)), serious-incident reporting
(EU Art. 73: 2/10/15 days), breach notification (FTC HBNR 60 days),
algorithmic-discrimination disclosure to AG (Colorado 90 days). Each is
a Workflow with a statutory deadline clock.

### Surface 6 — Periodic obligations
*What must happen on a schedule, regardless of whether the agent acted
today?* Annual bias audit (NYC LL 144), annual impact assessment
(Colorado), post-market monitoring (EU Art. 72), HIPAA information system
activity review, PCCP performance review, ECOA model validation, ISO
42001 surveillance. Surface 6 produces the artifacts Surface 2 checks.

```
Surface 6 → produces → Surface 2 (artifact registry)
Surface 1 + Surface 2 → drive → Surface 3 (runtime gates)
Surface 3 → emits → Surface 4 (evidence capture)
Surface 4 → triggers → Surface 5 (post-action workflows)
```

The six surfaces are universal. Every pack implements all six (some
trivially — a pack may have no Surface 6 obligations).

---

## The seven primitives (engineering decomposition)

| Primitive | What it is | Lives in |
|---|---|---|
| **Context** | Per-decision input — subject, jurisdiction, domain, use class, action class, agent, decision attributes, active artifacts snapshot | SDK + ActionRecord |
| **Predicate** | Composable boolean language over Context. Internal AST; YAML DSL for power users in v3+ | Pack modules |
| **Gate** | Predicate + Effect (ALLOW / BLOCK / REQUIRE_HITL / REQUIRE_NOTICE / REQUIRE_OPTIN / REQUIRE_DISCLOSURE / REDACT / WATERMARK / DEGRADE). Composes by strictest-effect dispatch | Pack modules |
| **Artifact** | Typed registry entity (FRIA, IA, bias_audit, BAA, model_card, ...) with version, validity, origin tag, citations | Artifact registry |
| **Workflow** | Stateful post-action process with statutory deadline (adverse-action, appeal, AG disclosure, incident report) | Workflow engine |
| **Scheduler** | Periodic obligation cron + reminder ladder + artifact-production hooks | Scheduler subsystem |
| **Artifact renderer** | Format-specific export over the same evidence store (HIPAA PDF, EU Conformity Package, NYC Public Summary, NIST AI RMF posture, FINRA WORM, ECOA letter, ...) | Renderer matrix |

Customers interact with: Context (implicitly via SDK), Gate effects (via
SDK exceptions), Artifact registry (uploads + template signoffs), Workflow
state (via dashboard + webhooks), Artifact renderers (via "Generate PDF"
button). They do *not* interact with Predicates directly in v1-v3; v3+
optionally exposes a YAML DSL for power users with custom rules.

---

## The pack catalog at scale

Each pack covers (regulation × jurisdiction × vertical). The catalog at
the 24-month horizon:

| Pack | Regulations | Jurisdiction | Vertical | MVP wave |
|---|---|---|---|---|
| Medtech Clinical | HIPAA + Section 1557 + NIST AI RMF | US-FEDERAL | Healthcare AI | **MVP (v1)** |
| Medtech + California | + CMIA + CA AB 489 | + US-CA | Healthcare AI | Wave 2 |
| Medtech + Texas | + TX TRAIGA healthcare | + US-TX | Healthcare AI | Wave 2 |
| Lending US | ECOA Reg B + FCRA + EEOC | US-FEDERAL | Financial AI | Wave 2 |
| Lending + Colorado | + CO SB 26-189 | + US-CO | Financial AI | Wave 2 |
| Employment NYC | NYC LL 144 + EEOC + Title VII | US-NY-NYC | HR / ATS | Wave 3 |
| Employment IL | + IL HB 3773 + AIVICA + BIPA | + US-IL | HR / ATS | Wave 3 |
| EU AI Act High-Risk | Reg 2024/1689 + GDPR Art. 22 | EU | Cross-vertical | Wave 3 |
| FDA SaMD / PCCP | FDA QMSR + Lifecycle | US-FEDERAL | Medical Devices | Wave 4 |
| ONC HTI-1 DSI | ONC Cures Act | US-FEDERAL | EHR / Clinical | Wave 4 |
| FINRA / SEC | Rule 3110/2210/4511 + SEC PDA | US-FEDERAL | Broker-dealer AI | Wave 4 |
| Insurance underwriting | NAIC AI bulletins + state | US various | Insurance AI | Wave 4 |
| CPPA ADMT | California ADMT regs | US-CA | Cross-vertical | Wave 4 |

Each pack ships with its own Big Law opinion. Packs compose — a US lending
customer in CO with EU users installs `Lending US` + `Lending + Colorado`
+ `EU AI Act High-Risk`. Strictest-effect dispatch resolves runtime
conflicts; artifact renderers produce the union of required artifacts.

---

## What customers see (the simplicity model at scale)

The architecture above is large. The customer's view is small.

### Customer-facing surface (what they touch)

1. **System manifest** — they declare per agent: vertical, jurisdictions
   served, intended action types, model identity, framework.
2. **Pack selection** — auto-suggested from system manifest, customer
   confirms. Toggleable. v1 has one pack; v3 has the full matrix.
3. **Pack parameters** — pack-defined knobs (HITL threshold seconds,
   reviewer-role roster, reason-code taxonomy extensions, jurisdiction
   set).
4. **Artifact uploads + template signoffs** — they upload independently-
   produced artifacts (bias audit from independent auditor) and sign-off
   on Vera-provided templates (HIPAA Risk Analysis filled in with their
   actual practice, counsel-reviewed).
5. **SDK install** — `pip install vera`, decorator. Same in v1, same in v5.
6. **Dashboard** — their compliance team's daily ops surface: recent
   decisions, gates fired, HITL events, workflow queue, artifact
   freshness.
7. **Artifact renderer button** — "Generate HIPAA Audit Trail" / "Generate
   EU Conformity Package" / "Generate NIST AI RMF Posture." One click.

### Customer-invisible surface (what Vera owns)

1. **Predicate engine** — packs ship as compiled Python with hardcoded
   gates. Customers don't write predicates. (v3+ may expose YAML DSL for
   power users with bespoke risk policies.)
2. **Hash chain primitives** — customers verify via CLI, never touch
   directly.
3. **Translation library** — pack source code is internal Vera asset,
   licensed but not exposed.
4. **Strictest-effect dispatch logic** — opaque algorithm; customers see
   the resulting Ruling.
5. **Big Law opinion library** — Vera assembles, customers cite.
6. **Off-Vera checkpoint plumbing** — runs invisibly; customers see
   "verification passed."

### What the practitioner / loan officer / recruiter sees

**Nothing of Vera.** The review prompt is rendered inside the conduit's
product (the AI vendor's app), branded as the conduit. Identity flows
through the conduit's SSO. The reviewer experiences a slightly better
version of their existing workflow — AI suggestions surfaced for approval
before commit.

### What the affected person sees

**Nothing of Vera.** Standing AI-use disclosure delivered through the
audit target's existing channels (MyChart, adverse-action letter, employee
handbook update). Per-decision notice (EU pack) delivered via the same
channels. Vera triggers the obligation; the conduit surfaces it; the
audit target delivers.

### What the regulator sees

**Vera mentioned once.** In the technical appendix of the audit PDF:
*"Audit infrastructure provided by Vera (Subcontractor Business Associate
/ Sub-processor / [equivalent role per jurisdiction]). Independent
verification at verify.vera.io/<hash>, or offline via OpenTimestamps anchor
block <N>."* The rest of the PDF is the audit target's evidence, white-
labeled through the conduit.

The regulator trusts the cryptographic chain + the BAA structure + the
legal opinions, not Vera's brand.

---

## The Act 2 evolution: insurance data substrate

The strategy doc names this as the long-term moat. The architecture above
makes it inevitable.

### Why the data exists

Vera sits in the runtime path of every signed agent decision across
hundreds of customers. The aggregate is:

- Cross-vendor (we serve Abridge AND Suki AND Ambience AND smaller
  competitors)
- Cross-domain (medtech AND lending AND hiring AND insurance underwriting)
- Cross-jurisdiction (US Federal AND EU AND state-specific)
- Cryptographically verified (the data is provably what it claims)
- Real-time (telemetry, not annual reports)

No carrier can replicate this on their own. They are insurers, not SaaS
builders.

### What carriers want

| Carrier need | Vera supplies |
|---|---|
| Underwriting signal — which AI deployments are riskier? | Behavioral feeds, opt-in by customer, anonymized |
| Loss correlation — which patterns precede claims? | Multi-customer time-series |
| Claims defense — when an AI deployment causes harm, what's the evidence? | Per-decision evidence packages on claims trigger |
| Risk pricing — real-time risk score per insured AI deployment | API: customer_id → risk_score, derived from Vera evidence |

### How Wave 5 ships

- Customer opts in to "data network participation" with explicit terms
  and revenue share
- Vera produces anonymized aggregate feeds (no per-decision identifiers,
  no customer attribution)
- Carrier licenses feed at $200K-$2M/year (Armilla, AIUC, Testudo,
  Munich Re, Beazley, Chubb per strategy doc)
- Vera + carrier optionally co-develop risk-scoring API
- v6+ (5+ year horizon): Vera operates as MGA, underwriting directly off
  the data

### Why this is the destination, not a pivot

Every primitive in v1 — the hash chain, the signed evidence, the
captured decision context, the demographic stratification, the model-
version traceability — is **already underwriting-ready**. We don't need
to retrofit. We just need to grow the dataset for 24-36 months.

This is why the v1 schema (Appendix A) is over-specified relative to v1
regulatory requirements. The fields that v1 doesn't strictly need (model
confidence, alternatives considered, tool-graph hash) are precisely the
fields a carrier later wants for risk scoring.

**Build for the carrier today. Sell to the AI vendor today. Sell to the
carrier in 24 months.**

---

## Sequencing — the waves

### Wave 1 — MVP (8 weeks, ship now)
See [policy-engine-mvp.md](policy-engine-mvp.md). Medtech wedge: AI scribes
+ HIPAA + Section 1557 + NIST AI RMF halo. One pack, one PDF, three gates,
in-app webhook HITL default. Off-Vera checkpoint mechanism ships in v1.

### Wave 2 — Vertical expansion (Months 3-6)
- Medtech state overlays (CA CMIA, TX TRAIGA, IL state)
- Lending pack (ECOA Reg B + EEOC + Colorado lending overlay)
- EU AI Act pack (Aug 2, 2026 forcing function)
- NIST AI RMF mapping document published as public trust artifact
- Workflow engine ships: adverse-action notice, appeal, correction,
  explanation, AG-disclosure types
- Periodic obligation scheduler with reminder ladder

### Wave 3 — Catalog breadth (Months 6-12)
- Employment pack (NYC AEDT + IL HB 3773 + EEOC)
- California stack (CPPA ADMT, SB 942, SB 1001, SB 53)
- Texas TRAIGA standalone pack
- Connecticut SB 5 (if enacted)
- Pack auto-suggestion UI (customer declares system manifest, Vera
  suggests applicable packs)
- Predicate DSL v1 for power-user customers

### Wave 4 — Sector specialization (Months 12-24)
- FDA PCCP + ONC HTI-1 packs (narrower buyers, high ACV)
- FINRA + SEC packs (broker-dealer / RIA AI)
- Insurance underwriting pack (NAIC AI model bulletin + state insurance regs)
- ISO 42001 SoA renderer (procurement-grade)
- Full EU Conformity Package PDF renderer (Annex IV)
- Multi-region deployment (EU residency for EU customers)

### Wave 5 — The carrier data network (Months 18-36)
- Customer opt-in to anonymized aggregate data sharing
- First carrier data-licensing deal (Armilla / AIUC / Testudo)
- Risk-scoring API (private beta with 1-2 carriers)
- Public co-marketing of carrier endorsements

### Wave 6 — MGA / strategic exit (Months 30+)
- Vera operates as Managing General Agent, underwriting AI policies
  directly off its own data
- OR: strategic acquisition by a major reinsurer wanting the data
  exclusively
- OR: continued independent operation as the AI insurance data backbone

---

## What we don't build, ever

- **A general-purpose rules engine.** OPA exists. We ship opinionated
  packs all the way. The opinion is the value.
- **A GRC dashboard for policy management.** That's Vanta's lane. We
  are the runtime infrastructure layer below Vanta.
- **Audit-firm software, model-card builders, dataset-card builders.**
  Adjacent markets, not the wedge.
- **Independent third-party audits** (NYC AEDT bias audit, etc.). The
  regulations explicitly require independence from the deployment.
  Vera cannot be the auditor; Vera produces the data the auditor
  consumes.
- **Clinical / legal / financial domain decisions** (was this a stroke,
  was this redlining, was this insider trading). Customers do domain
  classification; Vera enforces structural compliance. Mixing them puts
  Vera in the medical / legal / financial liability chain — bad
  architecture.

---

## Appendix A — Universal capture schema (the union across all packs)

Every consequential decision Vera captures should include the union of
these fields. Each maps to one or more regulations and is the input to
one or more artifact renderers. Fields not required by v1's medtech pack
are captured anyway to feed Act 2 underwriting.

| Field | Required by |
|---|---|
| decision_id, timestamp, sequence_number | All |
| org_id, system_id, model_id, model_version, framework | All |
| tool_graph_hash | Colorado substantial-modification, FDA PCCP, drift detection |
| subject_id_hash | EU Art. 12, NYC LL 144, Colorado §1703, HIPAA, ECOA |
| subject_jurisdiction[] | All scope tests |
| subject_age_band | EU Art. 5(1)(b), CA SB 243 |
| subject_self_id_demographics? | NYC LL 144 audit, EEOC, HMDA, ECOA disparate-impact |
| domain | All |
| use_class | All (EU classification, CO HRAIS, NYC AEDT, CPPA ADMT, FDA SaMD) |
| action_class | EU Art. 26(11), Colorado §1701 |
| substantial_factor | NYC LL 144 prong test, Colorado §1701 |
| decision_inputs_hash | EU Art. 12, HIPAA §164.308 |
| decision_outputs_hash | EU Art. 12, HIPAA §164.308 |
| decision_outcome | All |
| decision_confidence, alternatives_considered | ECOA reason codes, EU Art. 13, Act 2 risk scoring |
| decision_reason_codes[] | ECOA Reg B, Colorado §1703(4)(b)(i) |
| reviewer_id, reviewer_role, reviewer_credentials | EU Art. 14, Colorado meaningful review, HIPAA workforce |
| reviewer_override_decision, override_rationale | Colorado meaningful review, EU Art. 14(4)(d) |
| client_review_started_at, client_review_decided_at | Review-time enforcement |
| auth_method, session_token_hash | Non-repudiation tie-back |
| disclosures_emitted[] | EU Art. 26(11)+50, TX TRAIGA, UT AIPA, CA SB 1001 |
| notice_acknowledged_at, notice_channel | NYC LL 144 10-business-day rule, CA AB 489 |
| consent_state | CCPA, GDPR, IL BIPA |
| opt_out_state | CCPA, CPPA ADMT |
| watermark_hash | CA SB 942, EU Art. 50(2) |
| artifact_snapshot{fria_id, ia_id, bias_audit_id, baa_id, pccp_id, ...} | All Surface-2 artifacts |
| previous_hash, record_hash, signature | Cryptographic chain |
| checkpoint_anchor_block | OpenTimestamps verifiability |
| retention_policy_id | Per-regulation retention |

---

## Appendix B — Retention policy matrix

Retention is a property of the evidence class, not a global setting.
Each ActionRecord is tagged with the union of all applicable retention
windows; the engine retains until the longest applicable window expires.

| Evidence class | Retention | Source |
|---|---|---|
| Per-decision record (lending) | 25 months minimum, default 6 years | ECOA Reg B |
| Per-decision record (healthcare) | 6 years | HIPAA § 164.316 |
| Per-decision record (employment AEDT) | 2 years minimum | NYC LL 144 + OFCCP |
| Per-decision record (EU high-risk) | ≥6 months logs; 10 years for technical-file linkage | EU Art. 18, Art. 26(6) |
| Impact assessment | 3 years post-final-deployment | Colorado §1703 |
| Bias audit report | annual cycle + 1 year residual | NYC LL 144 |
| FRIA | lifetime of system + statutory retention | EU Art. 27 |
| Technical documentation | 10 years post-market | EU Art. 18 |
| Adverse action records | 25 months | ECOA Reg B |
| Watermark / provenance metadata | lifetime of generated artifact | CA SB 942 |
| Workflow records (appeals, corrections) | 3 years | Colorado §1703 |
| Periodic obligation logs | 3 years | NIST AI RMF + practice |
| Off-Vera checkpoints | indefinite (customer-controlled) | survives Vera |

Default for unknown: 6 years (HIPAA-aligned floor).

---

## Appendix C — Strictest-effect dispatch

When multiple gates fire on a single decision (a Colorado lending decision
about an EU resident is subject to EU AI Act + Colorado + ECOA + GDPR
Art. 22), the engine combines effects:

1. If any gate returns **BLOCK**, the action is blocked. Reason
   includes every citation.
2. Else if any gate returns **REQUIRE_HITL**, queue for human review
   with strictest role and shortest SLA.
3. Else if any gate returns **REQUIRE_OPTIN**, check consent; if
   missing, queue consent flow.
4. **Notice / disclosure / watermark / redaction effects are additive** —
   all apply. Emit EU Art. 50 disclosure AND Colorado pre-decision
   notice AND ECOA adverse-action notice if all are triggered.
5. The evidence record captures every gate's evaluation trace, not just
   the dispatch winner. A regulator might later challenge a different
   gate.

---

## Appendix D — The regulations Vera enforces at North Star

| # | Regulation | Status (May 19, 2026) | Hits |
|---|---|---|---|
| 1 | EU AI Act (Reg. 2024/1689) | Art. 5 + GPAI in force; Annex III high-risk Aug 2, 2026 | EU users, extra-territorial like GDPR |
| 2 | Colorado AI Act (SB 24-205 → SB 26-189) | Federally stayed Apr 27, 2026; SB 26-189 effective Jan 1, 2027 | CO consumers, 8 consequential domains |
| 3 | NYC Local Law 144 (AEDT) | In force since Jul 5, 2023 | Hiring/promotion of NYC residents |
| 4 | Texas TRAIGA (HB 149) | In force Jan 1, 2026 | TX residents, prohibited uses + gov/healthcare |
| 5 | Utah AI Policy Act | In force, sunset Jul 1, 2027 | UT consumers, regulated occupations |
| 6 | California stack: AB 2013, SB 942, SB 1001, AB 489, SB 243, SB 53, CPPA ADMT | Layered Jan 2026 → 2028 | CA users; CPPA ADMT is the heaviest |
| 7 | Illinois HB 3773 + AI Video Interview Act + BIPA | HB 3773 Jan 1, 2026; AIVICA since 2020 | IL employees/candidates |
| 8 | Connecticut SB 5 (Colorado-style) | Pending; effective Feb 1, 2026 if enacted | CT consumers |
| 9 | HHS Section 1557 + OCR AI guidance | DSI provisions in force May 1, 2025 | Healthcare providers receiving HHS funds |
| 10 | FDA AI/ML SaMD + PCCP + QMSR | QMSR Feb 2, 2026; PCCP guidance Dec 2024 | Manufacturers of AI medical devices |
| 11 | ONC HTI-1 (DSI source attributes) | Certification updated by Dec 31, 2024 | EHR-certified health IT |
| 12 | ECOA / Reg B (CFPB Circulars 2022-03, 2023-03) + FCRA + Section 1071 | In force; 1071 likely pushed to Jan 1, 2028 | Any creditor |
| 13 | EEOC Title VII + ADA AI guidance | In force May 2023 | All employers |

Plus three universal safe-harbor frameworks (not laws, but how reasonable
care is proven): **NIST AI RMF v1.0 + GenAI Profile (AI 600-1)**,
**ISO/IEC 42001:2023**, **OMB M-25-22** (federal procurement).

Plus the federal context: **EO 14179** (Jan 2025) revoked prior EO; the
**December 2025 preemption EO** establishes an AI Litigation Task Force
to challenge state laws but does not preempt as a matter of law. State
laws remain binding through 2026-2027 and likely beyond.

The North Star architecture supports all of the above. The MVP enforces
HIPAA + Section 1557 + NIST AI RMF for one vertical. Each subsequent wave
adds packs; the engine doesn't change.

---

## Appendix E — Operational edge cases and architectural responses

Edge cases surfaced during MVP design that the architecture must handle.
Most are v1; a few are v2+ deferrals. Each is documented here so the
architecture's response is explicit rather than implicit.

### Identity and tenancy

| Edge case | Architectural response | When |
|---|---|---|
| PHI in tenant_id | Regex validation (`^[a-zA-Z0-9_-]{1,64}$`); entropy red-flag warning | v1 |
| Typo in tenant_id | Auto-create placeholder; surface "no setup completed in 7 days" warning; ship admin "merge customers" action | v1 |
| tenant_id changes after customer merger | Manual merge in v1; tenant-aliasing system in v2 | v1 / v2 |
| Missing tenant_id at runtime | Configurable: strict (reject) or lenient (tag as `unknown_tenant`, surface, block PDF gen) | v1 lenient default |
| Sandbox vs. production data split | `al_test_` keys (synthetic data, no BAA) vs. `al_live_` (real PHI/PII, BAA required) | v1 |
| Customer uses Vera through multiple AI vendors | Each vendor has its own Vera tenant; same customer-of-customer appears as two separate entries; v3 ships customer-side portal for cross-vendor view | v1 / v3 |
| AI-assisted CSV match against auto-discovered placeholders | Three-pass match (exact / fuzzy / LLM-assisted); user approves/rejects each suggestion | v1 |

### Runtime and gates

| Edge case | Architectural response | When |
|---|---|---|
| Voice agent / latency-critical workflow | Real-time mode: deterministic gates inline; HITL becomes deferred post-action review; audit PDF labels them explicitly | v1 opt-in |
| Free-text outputs (agent doesn't produce structured data) | Opt-in Haiku-class extraction helper (`vera.LLMExtract`); off by default; logged per-decision | v1 opt-in |
| False-positive gate (curated data error) | Customers pin pack versions; quarterly refresh cycle; 48h SLA on reported false positives | v1 |
| Customer needs to override a gate | v1 ships opinionated packs without override; v2 ships per-action overrides with audit-trail justification + regulator visibility | v2 |
| Customer wants custom predicates | YAML DSL for power users in v3+; v1-v2 ships hardcoded packs only | v3+ |

### HITL and webhooks

| Edge case | Architectural response | When |
|---|---|---|
| Webhook endpoint down | Exponential backoff (1m → 5m → 30m → 2h → 8h → 24h → abort); surface to dashboard after 24h; action stays `PENDING_REVIEW` | v1 |
| Race: two reviewers approve same review | Idempotent on review_id; first attestation wins; second logged as "attestation conflict" | v1 |
| Review expires before reviewer responds | `review.expired` webhook to customer; action stays `PENDING_REVIEW` until customer takes action | v1 |
| Credentials mismatch (e.g., MD attests Schedule II but no DEA) | Vera rejects callback with HTTP 403; rejection logged in audit | v1 |
| Reviewer rubber-stamps (clicks Approve in <threshold) | Logged as `reviewed_below_threshold: true` in evidence; dashboard surfaces pattern | v1 |
| Reviewer revokes after approval | Hash chain is immutable; customer's product logs a corrective action; audit trail shows both | v1 |
| Customer wants tighter UI control over review-time enforcement | v2 ships embedded Vera review widget (React component); v1 measures round-trip + attests | v2 |

### Chain integrity and verifiability

| Edge case | Architectural response | When |
|---|---|---|
| Database restore from older backup | Vera detects sequence_number / previous_hash mismatch on next write; critical incident; recover from KMS checkpoint or OpenTimestamps anchor; orphaned writes documented | v1 |
| KMS key compromised | Immediate rotation; old chain remains verifiable against retained old key; new writes signed with new key; OpenTimestamps anchors immutable | v1 |
| Vera shuts down | Off-Vera mechanism: customer-controlled S3 mirror + OpenTimestamps anchors. `vera verify --offline` works without Vera. Audit trail outlives the company. | v1 (foundational) |
| Customer disputes a posture score / chain finding | Posture math is auditable (deterministic formula); chain is cryptographically verifiable; v2 ships posture-history versioning so regulator can ask "what was the formula on date X?" | v1 audit / v2 history |

### Posture

| Edge case | Architectural response | When |
|---|---|---|
| Low-volume distortion (100 decisions, 1 miss = 9.9/10) | Per-dimension minimums (≥10 HITL events, ≥7 days, etc.); below minimum = "insufficient data" not a number | v1 |
| Posture gaming via omission (customer skips a workflow that should fire) | Pack declares expected workflows; gap penalizes the dimension; audit PDF enumerates `should_have_fired` vs `did_fire` | v1 |
| Posture drops overnight after pack update | Email + diff explanation; old pack versions stay available for 30+ days; new posture is baseline after grace period | v2 |
| Insights LLM unavailable | Graceful fallback: "Insights temporarily unavailable. Your posture is X/Y; lowest dimension is Z. Drill into raw data." | v1 |

### Onboarding ergonomics

| Edge case | Architectural response | When |
|---|---|---|
| Customer has 50 hospitals to add at signup | CSV bulk import + AI-assisted Match Review against auto-discovered placeholders | v1 |
| Customer wants CRM sync (Salesforce, HubSpot, custom) | API connector | v2 |
| CSV upload has 50 rows, 3 with errors | Partial commit (47 succeed, 3 surface as downloadable error CSV); not all-or-nothing | v1 |
| Customer's BAA expires during active review | Accept review completion (action was initiated under valid BAA); block new actions on this customer | v1 |
| Customer uploads fake BAA PDF | Vera doesn't validate content; customer is on the hook for the attestation; audit records uploader + hash + timestamp; v2 integrates DocuSign for cryptographic signature validation | v1 / v2 |

### Multi-vertical and scale

| Edge case | Architectural response | When |
|---|---|---|
| Customer ships multiple packs (lending + medtech) | Each customer-of-customer (tenant_id) is bound to one pack; org runs both packs; posture aggregates across (weighted by volume) | v2 |
| 1,000+ customers per Vera org | Postgres sharding by org_id; hash chain checkpoint batching already supports it | v3 (data engineering) |
| Multi-region deployment (EU residency) | Frankfurt + Dublin regions; data-residency tagging per customer | v2 (EU pack) |

---

## Appendix F — Wave 2+ backlog (explicit)

Items deferred from v1 with planned wave. Captured so they don't get lost.

### Wave 2 (during YC batch, May-Aug 2026)

- EU AI Act pack (Aug 2, 2026 forcing function)
- Colorado AI Act pack (dual-mode CAIA + SB 26-189)
- Lending pack (ECOA Reg B + EEOC)
- HIPAA + Section 1557 medtech state overlays (CA CMIA, TX TRAIGA)
- Workflow engine (adverse-action, appeal, correction, explanation, AG disclosure, incident report types)
- Periodic obligation scheduler with reminder ladder + soft blocking
- NIST AI RMF posture renderer (public trust artifact)
- DocuSign integration for BAA-template-send workflow
- Per-action gate overrides with audit-trail justification
- Posture-drift email notifications + thresholds
- Tenant_id aliasing (for customer mergers)
- Embedded Vera review widget (React component) for customers wanting Vera-controlled UI timing

### Wave 3 (Months 6-12)

- Employment pack (NYC AEDT + IL HB 3773)
- California stack (CPPA ADMT, SB 942, SB 1001, SB 53)
- Texas TRAIGA standalone
- Connecticut SB 5 (if enacted)
- API connectors (Salesforce, HubSpot, custom CRM)
- Predicate DSL v1 (YAML, for power-user customers)
- Pack auto-suggestion UI (system manifest → recommended packs)
- Decision search (when customer base hits volume justifying it)
- Cross-vendor customer-side portal (audit-target sees all AI vendors)

### Wave 4 (Months 12-24)

- FDA PCCP + ONC HTI-1 packs
- FINRA + SEC packs (broker-dealer / RIA)
- Insurance underwriting pack (NAIC bulletins + state)
- ISO 42001 SoA renderer
- Full EU Conformity Package PDF renderer (Annex IV)
- Multi-region deployment (EU residency)
- PDF preview in modal (deferred from v1)

### Wave 5 (Months 18-36) — Act 2

- Customer opt-in to anonymized aggregate data sharing
- First carrier data-licensing deal (Armilla / AIUC / Testudo)
- Risk-scoring API (private beta)
- Co-marketing with carrier endorsements

### Wave 6 (Months 30+)

- MGA operation OR strategic acquisition path
- Continued data-network operation

---

## Appendix G — Citations for further reading

Primary regulatory texts:
- [EU AI Act (Reg. 2024/1689)](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)
- [Colorado SB 24-205](https://leg.colorado.gov/bills/sb24-205) +
  [SB 25B-004](https://leg.colorado.gov/bills/sb25b-004) +
  [SB 26-189](https://leg.colorado.gov/bills/sb26-189)
- [NYC DCWP AEDT](https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page) +
  [Final Rule (6 RCNY Subchapter T)](https://rules.cityofnewyork.us/rule/automated-employment-decision-tools-updated/)
- [Texas TRAIGA HB 149](https://capitol.texas.gov/BillLookup/History.aspx?LegSess=89R&Bill=HB149)
- [California CPPA Final ADMT Regulations](https://cppa.ca.gov/announcements/2025/20250923.html)
- [California SB 942](https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202320240SB942)
- [Illinois HB 3773](https://www.ilga.gov/legislation/billstatus.asp?DocNum=3773&GAID=17)
- [HHS Section 1557 Final Rule](https://www.federalregister.gov/documents/2024/05/06/2024-08711/nondiscrimination-in-health-programs-and-activities)
- [FDA PCCP Final Guidance (Dec 2024)](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/marketing-submission-recommendations-predetermined-change-control-plan-artificial-intelligence)
- [ONC HTI-1 Final Rule](https://www.healthit.gov/topic/laws-regulation-and-policy/health-data-technology-and-interoperability-certification-program)
- [CFPB Circular 2022-03](https://www.consumerfinance.gov/compliance/circulars/circular-2022-03-adverse-action-notification-requirements-in-connection-with-credit-decisions-based-on-complex-algorithms/) +
  [Circular 2023-03](https://www.federalregister.gov/documents/2024/04/17/2024-08003/consumer-financial-protection-circular-2023-03-adverse-action-notification-requirements-and-proper)
- [EEOC Title VII Technical Assistance (May 2023)](https://www.eeoc.gov/laws/guidance/select-issues-assessing-adverse-impact-software-algorithms-and-artificial-intelligence)
- [NIST AI RMF 1.0](https://www.nist.gov/itl/ai-risk-management-framework) +
  [GenAI Profile (NIST AI 600-1)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- [ISO/IEC 42001:2023](https://www.iso.org/standard/42001)
- [OpenTimestamps](https://opentimestamps.org/) — public timestamping for
  off-Vera checkpoint anchoring

Internal references:
- [policy-engine-mvp.md](policy-engine-mvp.md) — the v1 ship plan
- [regs.md](regs.md) — current regulations page content
- [strategy.md](strategy.md) — product strategy, Act 1 + Act 2
- [use_cases.md](use_cases.md) — seven medtech use cases
- [backend/app/services/policy_engine.py](backend/app/services/policy_engine.py)
- [backend/app/services/hashing.py](backend/app/services/hashing.py),
  [chain.py](backend/app/services/chain.py)
- [backend/app/models/action_record.py](backend/app/models/action_record.py)
- [sdk/vera/](sdk/vera/)

---

## TL;DR

Vera serves a chain, not a customer. The chain runs from the **regulator**
(audit consumer) through the **audit target** (value recipient, e.g.,
hospital) through the **conduit** (Vera's direct customer, e.g., AI vendor)
to the **substrate** (Vera itself), with two other participants —
**reviewers** (the HITL humans) and **affected persons** (patients,
applicants, candidates) — receiving artifacts derived from the same
underlying evidence ledger. In Wave 5+, a sixth tier — **insurance
carriers** — consumes anonymized behavioral telemetry as an underwriting
substrate.

Every product decision flows from "which tier consumes this artifact?"
The PDF is regulator-tier. The dashboard is conduit-tier. The standing
notice is patient-tier. The behavioral feed is carrier-tier.

The architecture has four moats: the runtime substrate (12-18 months to
build), the regulatory translation library (years to assemble), the legal
opinion stack ($30-60K and 3-6 months per regulation), and the BAA / DPA
chain trust position (months of operational and contractual work). The
PDF format itself is commodity; the moats are everywhere else.

The runtime substrate is hash-chained, KMS-signed, and verifiable
independently of Vera via OpenTimestamps and customer-controlled S3
checkpoints. The audit trail outlives Vera. This is a first-class
architectural requirement, not a feature.

Each regulation decomposes into the same six surfaces (scope test,
pre-deployment artifacts, runtime gates, evidence capture, post-action
workflows, periodic obligations). The engine implements all six once and
parameterizes them per pack. The pack catalog grows in waves; the engine
doesn't change.

Customers see a small surface: SDK install, system manifest, pack
selection, artifact uploads/signoffs, dashboard, one-click PDF renderer.
Predicates, hash chains, translation library, opinion stack, off-Vera
checkpoints — all invisible.

The MVP in [policy-engine-mvp.md](policy-engine-mvp.md) is the strict
subset that ships first. Every primitive in v1 is a strict subset of the
architecture above. Same engine, more packs, more renderers, more legal
opinions, more BAAs over time. The destination is the AI insurance data
substrate — the strategy doc's Act 2. We build for the carrier today and
sell to the AI vendor today.
