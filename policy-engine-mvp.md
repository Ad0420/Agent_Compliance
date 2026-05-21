# Vera Policy Engine — MVP

**The thing we ship in 8 weeks.**
**Last updated:** 2026-05-19
**Status:** v1 design. Pairs with [policy-engine-north-star.md](policy-engine-north-star.md).

---

## What you're reading

This is the **MVP cut** of Vera's policy engine. It is deliberately narrow:
one vertical, one regulation stack, one SDK contract, one PDF.

The longer architectural vision is in [policy-engine-north-star.md](policy-engine-north-star.md).
That document is the right architecture for 12-24 months out. It is the wrong
product for v1. The two pair: every primitive in this MVP is a strict subset
of the north-star architecture. No throwaway code.

If you only read one section, read **What Vera is, what Vera is not**.

---

## What Vera is, what Vera is not

**Vera is the runtime evidence layer for AI agents in healthcare.** It sits
between an AI agent and any consequential action, intercepts the action
synchronously, routes high-risk actions to a qualified human reviewer, and
emits a cryptographically signed evidence trail of every decision.

**Vera is not a compliance certification.** We do not make customers HIPAA
compliant. We do not replace their compliance officer. We do not issue audit
opinions. We do not sign BAAs with their hospitals on their behalf.

### The chain Vera serves (read carefully — this shapes every product decision)

The audit target is not Vera's customer. The audit target is the entity
**upstream** of Vera's customer. The chain:

```
            (audits — HHS OCR, state AG, hospital internal audit)
                    ▼
Cleveland Clinic ──────────  Covered Entity — primary audit target
                    │
   "show me audit logs of AI-assisted chart entries"
                    ▼
Abridge ──────────────────  Business Associate — Vera's customer, the conduit
                    │
                    ▼
Vera ─────────────────────  Subcontractor BA — the audit substrate
```

This means:
- **The audit happens at the hospital, not at Vera's customer.** Abridge can be
  named in a BA-level investigation, but the principal regulatory pressure
  lands on Cleveland Clinic.
- **Vera's audit PDF is consumed at the top of the chain** (OCR investigator),
  not by Abridge's compliance officer.
- **Vera's customer is the conduit, not the destination.** Abridge hands the
  PDF to Cleveland Clinic; Cleveland Clinic forwards to OCR.
- **The practitioner (Dr. Smith) is almost never individually audited** under
  federal frameworks. He's a workforce member. Vera doesn't need
  per-practitioner audit artifacts in v1.

### What Vera does (in chain terms)

When a regulator (OCR, state AG, accrediting body) or hospital procurement
team asks **Cleveland Clinic** (audit target):

- *"Show me your audit trail of AI-generated chart entries"* → Cleveland Clinic asks Abridge → Abridge hands them Vera's signed log PDF, white-labeled with Abridge's branding
- *"Show me physician sign-off on every new diagnosis"* → same chain
- *"Show me your AI decision support documentation per Section 1557 § 92.210"* → Vera's evidence report + NIST AI RMF posture statement, white-labeled

…and Cleveland Clinic has the answer. Vera makes the hospital **auditable**
through the BAA chain. Vera's customer is the relationship; the hospital is
the value recipient; the regulator is the ultimate audit consumer.

This is the pitch. It is honest. It does not invite the Delve trap.

---

## Why medtech first

The strategy doc said "fintech first, healthtech fast-second." We're swapping.
Reasons:

1. **Network access.** LeapYear interview, founder contacts in healthtech, seven
   detailed use cases already mapped in [use_cases.md](use_cases.md).

2. **Buyer fit.** AI scribe vendors (Abridge, Suki, Ambience, DAX, and the long
   tail of seed-stage scribes / voice agents / prior-auth agents) are
   engineering-led startups selling into hospitals. Technical buyers. They
   already face hospital procurement obstacles ("show me audit logs of every
   chart entry"). Vera dissolves that obstacle directly.

3. **HITL is native.** Physicians already approve chart notes. Voice receptionists
   already escalate to clinical staff. Vera does not ask anyone to *add* a
   review step; it makes the existing review *signed*. Tiny behavioral ask.

4. **HIPAA § 164.312(b) is the cleanest regulatory hook in the industry.** Three
   words — "record and examine activity" — and Vera is literally what that
   describes. Mapping is one-to-one. No interpretation required.

5. **Section 1557 § 92.210 (in force May 2025)** gives us a named, federal AI rule
   for healthcare *today*. Not waiting for EU Aug 2026 or stayed Colorado.
   "Reasonable efforts to identify and mitigate discrimination risk" in AI
   patient-care decision support — Vera's demographic-stratified outcome
   monitoring + HITL routing = the reasonable effort.

6. **Hospital procurement is the forcing function.** When Cleveland Clinic asks
   an AI scribe vendor "do you produce HIPAA-compliant audit logs of every
   AI-generated chart entry?" — the vendor either has Vera or loses the deal.
   That's a closeable signal, faster than CFPB enforcement cycles in lending.

Lending stays on the roadmap (Wave 2, ~Q3 2026). Same engine, additional pack.

---

## The customer & the wedge

**Vera's customer (the relationship)**: an AI scribe / receptionist /
prior-auth / triage vendor — think Abridge, Suki, Ambience, DAX, plus
seed-stage competitors. Series A-C, 20-200 engineers, selling into 10-500
hospitals.

**Vera's customer's customer (the value recipient)**: the hospital or clinic
group. They are the audit target. They get value from Vera *through* Abridge.

**Vera's customer's customer's user (the reviewer)**: a physician, nurse, or
RCM staffer. They are the HITL reviewer. They never see Vera — the customer's
product renders the review prompt inside its own UI.

**Vera's customer's customer's user's customer (the patient)**: the patient.
They never see Vera. They receive a standing AI-use disclosure at enrollment
through the hospital's existing patient communication channel.

**Vera's customer's customer's customer's regulator (the audit consumer)**:
HHS OCR, state AG, accrediting body. The PDF that flows up the chain is
written for them. They have never heard of Vera; they trust the
cryptographic chain + the BAA structure.

The wedge use case: **AI scribe → chart entry** ([use_cases.md](use_cases.md) #1).

> Scribe vendor generates a clinical note. Vera intercepts before chart commit.
> Any new diagnosis or controlled-substance order POSTs a review webhook to
> the scribe vendor's product, which surfaces the review to the attending
> physician inside its own UI. Physician approves / modifies / rejects.
> Scribe vendor's product POSTs decision back with identity attestation. Vera
> signs the chain: AI suggestion + physician edits + final accepted note +
> model version + timestamp + attested reviewer ID. Note commits. White-
> labeled audit PDF flows up the chain on procurement / regulator request.

Sales pitch (sharpened by chain analysis):

> *"Cleveland Clinic procurement just asked Abridge for AI audit logs.
> Without Vera, Abridge stalls and loses the deal. With Vera, Abridge hands
> Cleveland Clinic a customer-branded HIPAA AI Audit Trail PDF that Cleveland
> Clinic forwards to OCR in 90 seconds. We're the layer that lets you win
> hospital sales by closing the audit question before it's even asked."*

This is the wedge sale. The buyer is engineering / product / sales leadership
at the AI vendor (Abridge), not their compliance officer. The buying trigger
is **lost or stalled hospital sales**, not abstract compliance posture. The
forcing function is upstream procurement, not OCR enforcement.

---

## How Vera identifies which hospital is affected by an agent call

Vera does **not** auto-detect the hospital from the action payload — the
hospital is customer state (the customer's app already knows which hospital
each session is for, via their authenticated user / routing / session
context). The customer attests it; Vera records.

Three ways the customer can attest, picked by their codebase shape:

### 1. Middleware (cleanest — recommended default)

One wiring step at framework startup. Every gate downstream is auto-tagged:

```python
from vera.middleware import VeraMiddleware

app.add_middleware(
    VeraMiddleware,
    get_tenant_id=lambda req: req.user.hospital_id,
)

@vera.gate(action="commit_chart_note")
def commit_chart_note(...):
    ...  # auto-tagged with current request's tenant_id
```

### 2. Context manager (for background jobs / non-HTTP code)

```python
with vera.tenant("cleveland_clinic"):
    process_batch_of_charts()
```

### 3. Explicit per-call (escape hatch)

```python
@vera.gate(action="commit_chart_note", tenant="cleveland_clinic")
def ...
```

Customer wires the resolver once, never thinks about it again. Their
existing identity system already knows the hospital — they hand that
identifier to Vera.

### Auto-discover + complete-to-enforce

First time Vera sees a new `tenant_id`, it auto-creates a placeholder
hospital with `status=pending_setup` and `baa_status=missing`. Decisions
continue to be captured (encrypted, hash-chained, redacted). **Audit PDF
generation is blocked** for that hospital until the customer completes
setup (uploads BAA, sets display name).

Engineering can integrate Vera and start capturing decisions on day 1;
compliance can complete per-hospital setup on day 2-7 without blocking
engineering work.

On the dashboard, the customer sees yellow rows: *"Cleveland Clinic ·
Setup required · 47 decisions captured awaiting BAA."*

### Three onboarding paths (none required)

The wizard offers three explicit paths at signup. Customer picks
whichever matches their workflow:

| Path | When to pick | What happens |
|---|---|---|
| **Auto-discover** (recommended for engineering-led teams) | "I'll let my SDK calls populate hospitals as they fire" | Customer installs SDK + middleware; first call with a new tenant_id auto-creates a placeholder; customer completes setup later |
| **Manual** (1-5 hospitals known upfront) | "I want to add a few hospitals now" | Standard add-hospital form (display name, tenant_id, BAA upload, contact, jurisdictions) |
| **CSV bulk** (5+ hospitals from CRM) | "I have a list of 50 hospitals; let me upload them all" | Download CSV template, fill from CRM, upload. All hospitals created with `pending_baa_upload`; customer uploads BAAs separately |

Auto-discover is the lowest-friction default. CSV exists for customers
who want to **proactively control the list** rather than wait for traffic
to populate it — typically compliance-led teams who'd rather see all 50
hospitals listed on day 1 (even pending BAAs) than discover them
reactively.

Both methods can coexist. If a customer auto-discovers a hospital and
later uploads a CSV that includes the same tenant_id, the placeholder is
updated with the CSV metadata (display name, BAA reference). No
conflict.

API connector (CRM → Vera sync) ships in v2+.

### tenant_id validation

The tenant_id is a customer-attested string. Vera validates:

- **Format**: must match `^[a-zA-Z0-9_-]{1,64}$` (alphanumeric, underscore,
  hyphen, max 64 chars). Reject calls with non-conforming tenant_ids.
- **PHI check**: high-entropy or human-name-shaped strings flagged as
  potential PHI exposure. Vera logs a warning and surfaces on the
  customer's dashboard ("tenant_id 'hospital_john_doe' looks like it may
  contain PHI — please review").
- **Uniqueness**: scoped per Vera org. `cleveland_clinic` under Abridge
  is distinct from `cleveland_clinic` under Suki.

### Sandbox vs. production split

Customer can integrate Vera before BAA is signed by using **sandbox
keys** (`al_test_*`):

- Sandbox: synthetic / scrubbed data only; harder redaction defaults;
  no BAA required; rate-limited.
- Production (`al_live_*`): real PHI; requires signed BAA between Vera
  and customer org; full ingress.

Same architecture, different operational posture. Customer can develop
in sandbox while BAA is being negotiated.

---

## What v1 enforces — three gates + two always-on properties

The medtech pack ships first. Three runtime gates fire conditionally; two
behaviors are always-on regardless of which gate triggered.

### Gate 1 — HITL on new diagnosis

**Trigger:** scribe output contains non-empty `new_diagnoses` field.
**Effect:** route to reviewer with role=`attending_physician`.
**Citation:** HIPAA § 164.312(b) (audit controls); Section 1557 § 92.210
(reasonable efforts to mitigate AI discrimination risk).

### Gate 2 — HITL on controlled-substance order

**Trigger:** scribe output contains a medication whose RxNorm ID is in the
DEA Schedule I-V list (curated quarterly).
**Effect:** route to reviewer with role=`dea_licensed_physician`.
**Citation:** 21 CFR 1306.04 (DEA prescription requirements).

### Gate 3 — Block on stale BAA

**Trigger:** the BAA between Vera and the customer org has expired or is
missing.
**Effect:** hard block. Customer's app receives `vera.PolicyBlock` with
`fix_url` pointing to BAA renewal.
**Citation:** HIPAA § 164.504(e) (business associate contracts).

Plus two implicit always-on behaviors:

### Always-on — PHI redaction in audit log

The action record stores hashed PHI fields (patient_id_hash, not patient_id),
encrypted full payloads, and redacted free-text via existing
[sdk/vera/redaction.py](sdk/vera/redaction.py). HIPAA Safe Harbor pattern set
ships as the default schema for the medtech pack.

### Always-on — Signed evidence chain (survives Vera)

Every action is hash-chained per existing
[backend/app/services/hashing.py](backend/app/services/hashing.py) and
[chain.py](backend/app/services/chain.py). The chain is verifiable
independently of Vera's continued existence:

1. **Daily KMS-signed checkpoints** of the chain head (existing infrastructure).
2. **Off-Vera mirror** — each checkpoint is also written to a
   customer-controlled S3 bucket (customer owns the data; Vera cannot delete it).
3. **Public timestamping** — each checkpoint is anchored via OpenTimestamps
   to the Bitcoin blockchain (free public service, no Vera dependency).
4. **Verification** — `vera verify <hash>` checks against Vera's public key;
   `vera verify --offline` checks against the customer's S3 mirror + the
   OpenTimestamps anchor, no Vera contact required.

This is the architectural answer to "what if Vera shuts down" and a real
procurement objection-killer. The audit trail outlives Vera.

---

## What v1 generates vs. templates

**The Delve rule:** auto-generate evidence (facts derived from runtime data).
Provide templates with red banners for organizational attestations (statements
about what the company *does*). Never let a customer sign a Vera-generated
policy claiming a practice they don't actually follow.

### Auto-generated artifacts (SAFE — derived from runtime data)

| Artifact | What it is | Source |
|---|---|---|
| **HIPAA AI Audit Trail PDF** (THE central product artifact) | 30-day summary written for an OCR investigator: decisions counted, HITL events, reviewer identities (attested by customer), hash chain head, NIST AI RMF posture mapping. Customer-white-labelable. | Aggregation + ReportLab |
| **HIPAA audit log export** (raw) | Every action record, last N days, with hashes — for technical inspection | Direct query over ActionRecord |
| **Per-decision evidence package** | Single decision: AI suggestion + edits + approval + signed hash, exportable on demand | Direct serialization |
| **Section 1557 disparate-impact monitoring report** | Demographic-stratified outcome data, weekly auto-refresh | Aggregation over captured demographic self-ID |
| **NIST AI RMF posture statement** | Govern/Map/Measure/Manage mapping showing which functions Vera enforces (Map 5.1, Measure 3.2, Manage 2.3, etc.) | Generated from observed runtime controls |

These are pure derivatives of logged evidence. They cannot be false unless the
underlying logs are false (which the hash chain prevents).

### Why the policy engine is the moat, not the PDF (read this if you're tempted to skip building the engine)

The PDF is the visible artifact. The policy engine is what makes it defensible.
A competitor could reverse-engineer the PDF format in an afternoon. They
cannot reverse-engineer:

1. **The runtime substrate.** Pre-action gate evaluation, hash chain, KMS
   signing, encrypted spool, webhook delivery, idempotency, multi-tenant
   isolation, SDK plumbing. 12-18 months of engineering minimum, and the
   architecture has to be right the first time (retrofitting cryptographic
   chains onto a system that wasn't designed for them is a rewrite, not a
   refactor).

2. **The regulatory translation layer (the packs).** DEA schedule lookups,
   HIPAA Safe Harbor redaction, Section 1557 demographic-stratification,
   RxNorm controlled-substance mappings, BAA chain attestation validation,
   HITL role mappings against medical credentials. Hundreds of hours of
   regulatory research per regulation compressed into code, plus attorney
   review, plus quarterly refresh as regulations shift (Colorado rewrote
   itself in 2026; the EU AI Act high-risk obligations land Aug 2, 2026).
   This is the "translation library" work — substrate is replicable, the
   library is what takes years.

3. **The Big Law opinion on this specific format and runtime.** A written
   opinion that Vera's architecture satisfies HIPAA § 164.312(b) and Section
   1557 § 92.210. Not transferable. A competitor commissions their own
   ($30-60K, 3-6 months), against their own (different) format, and they're
   a year late and one customer-bake-off behind.

4. **The BAA chain trust position.** Vera signs BAAs as a Subcontractor BA.
   Requires HIPAA security posture, SOC 2 pursuit, insurance, operational
   maturity, and customer references in the BA chain. A competitor outside
   the BAA chain literally cannot see the data needed to produce the PDF.
   Switching cost for existing customers is real.

What the PDF actually attests to — and what each claim requires from the
engine:

| PDF claim | Requires |
|---|---|
| "2,847 AI-assisted entries, all captured" | Hash chain (completeness + tamper-evidence) |
| "947 required HITL; 947 received HITL before commit" | Pre-action gate, not post-hoc log |
| "Reviewer Dr. Smith, attested by SAML SSO at 14:47" | Real-time customer webhook callback signed into chain |
| "100% of controlled-substance orders reviewed by DEA-licensed prescriber" | Runtime role validation at gate fire |
| "No prohibited use detected" | Block gates refusing the action — not just logging it |
| "Hash chain verifiable at verify.vera.io and OpenTimestamps anchor" | KMS signing + off-Vera checkpointing |

A "just the PDF" competitor cannot make any of these claims defensibly. Their
PDF says "per the customer's report, X happened" — which OCR rejects as
non-auditable. The PDF is worthless without the engine; the engine is what's
expensive and hard to copy.

**Build the engine. The PDF is how the engine's value reaches the regulator.**

### The PDF — design requirements (because this is the audit-consumer artifact)

The HIPAA AI Audit Trail PDF is the artifact that flows up the chain to an
OCR investigator. It is the moment of value capture. Design requirements:

- **Audience is the OCR investigator, not Abridge's compliance team.** Written
  in plain regulatory English, with citations (45 CFR § 164.312(b), 45 CFR
  § 92.210), no Vera-internal jargon.
- **Customer-white-labelable.** Cover page shows Abridge's logo, then
  "Prepared for [Hospital Name]." Vera mentioned once in a technical
  appendix: "Audit infrastructure provided by Vera (Subcontractor Business
  Associate). Independent verification at verify.vera.io/<hash>." OCR
  shouldn't have to "trust Vera" — they trust the cryptographic chain and the
  BAA structure.
- **Self-verifying without contacting Vera.** The PDF contains a verification
  URL whose underlying hash is *also* published to a customer-controlled S3
  bucket (daily checkpoint) and to a public timestamping service. If Vera
  shuts down tomorrow, OCR can still verify the chain. Removes the "what if
  Vera goes out of business" procurement objection.
- **Structured for OCR's mental model.** Sections in OCR's checklist order:
  scope of AI use → audit controls in place → HITL evidence → demographic
  monitoring → workforce training (customer-attested) → BAA chain → technical
  verification.
- **Counsel-reviewed before v1 ship.** Commission a Big Law healthcare-tech
  practice (Hogan Lovells, McDermott, Ropes & Gray) to review the template
  and produce a written opinion that the PDF satisfies HIPAA § 164.312(b)
  audit-control documentation and Section 1557 § 92.210 reasonable-efforts
  documentation. Pull-quote becomes homepage hero. Budget $30-60K. The PDF
  *is* the product; the opinion *is* the moat.

### Templates (CUSTOMER COMPLETES — red banner on every section)

| Template | What it is | What customer fills in |
|---|---|---|
| **HIPAA Risk Analysis skeleton** (§ 164.308(a)(1)(ii)(A)) | Standard structure with prompts | Their actual data inventory, threat model, controls assessment |
| **Section 1557 Nondiscrimination Policy** | Boilerplate skeleton | Their nondiscrimination coordinator, grievance procedure, training program |
| **AI Tool Inventory** | Listing template | Names of every AI tool they deploy + intended uses |
| **Workforce AI Training Module Outline** | Suggested topics | Their training delivery, attendance records |
| **AI-Assisted Care Disclosure (standing notice)** | Patient-facing template covering AI use, patient rights, contact for questions. Conditional sections for CA AB 489, TX TRAIGA, UT AIPA based on customer's declared state footprint. | Their AI tool list (per state), compliance officer contact, MyChart / intake delivery method |

### On patient-facing notice — standing, not per-decision (v1)

For US Federal medtech, no per-patient AI-use notice is required (HIPAA
doesn't, Section 1557 doesn't). State patchwork creates targeted requirements
(CA AB 489, TX TRAIGA, UT AIPA) but these can be satisfied with a **standing
notice** — a one-time disclosure delivered at patient enrollment, signed
once, recorded as acknowledged.

Architecturally, the same chain applies as HITL — **Vera is invisible to the
patient**:

1. Vera detects the customer operates in CA/TX/UT (declared at onboarding) and
   surfaces the conditional clauses in the standing notice template.
2. Customer (Abridge) hands the template to Cleveland Clinic during onboarding.
3. Cleveland Clinic's compliance officer + counsel review, fill in specifics
   (hospital's AI tool list, contact info), sign.
4. Cleveland Clinic delivers via their existing patient communication channel
   (MyChart, intake paperwork, waiting-room poster, verbal at registration).
5. Patient acknowledges once at enrollment.
6. Customer POSTs acknowledgment event to Vera: `{patient_id_hash, acknowledged_at,
   channel, jurisdiction_clauses_included}`.
7. Vera records and surfaces in the audit PDF: "Patient acknowledged AI
   disclosure on date X via channel Y; hospital attestation."

Per-decision patient notice (EU Art. 26(11) style — "this specific decision
was AI-assisted") is **v2/EU pack**, not v1. Per-decision delivery requires
notice infrastructure (MyChart push, email, SMS) that's specific to each
hospital's stack and overkill for US Federal medtech.

### Template completion guardrail

Each template arrives as a Markdown file in the customer's Vera workspace with
clear `<<REPLACE WITH YOUR ACTUAL PRACTICE>>` markers in red, and a checkbox
banner: *"☐ Counsel has reviewed this document. I attest the statements
reflect my organization's actual practices."* That checkbox is required
before sign-off. The customer cannot one-click these into production — the
banner is the Delve guardrail.

### Vera-side artifacts (Vera signs)

- **Vera BAA**: bilateral contract between Vera and the customer org. Standard
  HHS-modeled BAA, customer redlines, both sign. This is *not* auto-generated;
  it is sales / legal workflow. Vera ships a model BAA in the onboarding flow.
- **Vera SOC 2 Type II report** (~year 2): standard procurement artifact.
- **Vera HIPAA security attestation** (Vera's own posture): not the
  customer's — ours.

---

## HITL — who, where, when, how

### Who's the reviewer? (read this carefully — it shapes the architecture)

The reviewer is the **practitioner who has clinical authority over the
patient.** For the AI scribe case, that's Dr. Smith at Cleveland Clinic.

Dr. Smith is **not** Vera's user. He's not even Vera's customer's user in
the SaaS sense. The identity chain:

```
Vera                       (policy engine vendor)
  ↓ BAA with
Customer (Abridge)         (Vera's customer — AI scribe vendor)
  ↓ BAA with
Cleveland Clinic           (Abridge's customer — covered entity)
  ↓ employs
Dr. Smith                  (the practitioner — the reviewer)
  ↓ documents care for
Mr. Jones                  (the patient)
```

For the review to satisfy the regulatory requirements (EU Art. 14, Colorado
meaningful review, HIPAA workforce, Section 1557 reasonable efforts), the
reviewer must have:

- Clinical competence and training
- Authority to override the AI's output
- Appropriate licensure (MD/DO; DEA for controlled substances)
- Authority over *this specific patient's* chart

Only Dr. Smith fits all four. Not Abridge — they have no clinical authority
over Mr. Jones. If Abridge tried to "review on behalf of" Cleveland Clinic's
patients, that's practicing medicine without a license and breaks the BAA
chain.

### What this means for the architecture

**Vera has no direct relationship with Dr. Smith.** He has no Vera account.
He doesn't sign into Vera's dashboard. Cleveland Clinic doesn't know Vera
exists (Vera is a Subcontractor BA under Abridge's BAA with the hospital).

So Vera **cannot** be the surface where Dr. Smith reviews. The review must
happen inside the product Dr. Smith is already using — Abridge's app —
which is also the only product Cleveland Clinic's IT has approved for his
account.

**Vera is invisible to the practitioner. That's a feature.**

### The flow (in-app webhook, the default channel for medtech)

1. Abridge's scribe generates a draft note.
2. Abridge's code calls `@vera.gate(action="commit_chart_note")`.
3. Vera's gate fires: new diagnosis + controlled substance → REQUIRE_HITL.
4. Vera POSTs to Abridge's webhook with the review context and a `review_id`.
5. Abridge's product surfaces the review prompt in Dr. Smith's existing UI
   (visit task list, mobile app, EHR embed — Abridge's call).
6. Dr. Smith clicks Approve / Modify / Reject **inside Abridge's app**,
   branded as Abridge.
7. Abridge POSTs the decision back to Vera:
   ```json
   POST /v1/reviews/{review_id}/complete
   {
     "decision": "approve",
     "reviewer_id": "dr_smith@clevelandclinic.org",
     "reviewer_role": "attending_physician",
     "reviewer_credentials": ["MD", "DEA"],
     "auth_method": "SAML_SSO",
     "session_token_hash": "...",
     "comment": "Confirmed pancreatitis on labs",
     "client_review_started_at": "...",
     "client_review_decided_at": "..."
   }
   ```
8. Vera validates the role matches the gate's required role, signs the
   evidence chain, returns success.
9. Abridge's code commits the chart to Epic.

**Dr. Smith never sees "Vera" anywhere.** He sees Abridge doing the
responsible thing: surfacing AI suggestions for his approval before they
hit the chart. The audit trail captures Dr. Smith's identity, role, and
decision via Abridge's attestation — without Dr. Smith ever being a Vera
user.

### Identity provisioning — Vera doesn't onboard practitioners

Abridge owns the identity layer for their physicians. They typically run
SSO (SAML or OIDC) against each hospital's IdP. When Dr. Smith reviews,
Abridge has a verified session for him; Abridge passes that attestation to
Vera in the webhook callback.

**Vera trusts Abridge's identity attestation.** If a regulator later
challenges whether it was really Dr. Smith, the chain flows back: Vera's
record → Abridge's session log → Cleveland Clinic's IdP audit log. Vera is
one link, not the originating point. This is the correct architecture under
HIPAA's Subcontractor BA model — Vera should not be authenticating clinical
staff at hospitals; that would be outside its scope.

What Abridge attests in the callback (Vera enforces these fields are
present):

- `reviewer_id` — opaque identifier scoped to Abridge's tenant
- `reviewer_role` — must match the gate's required role
- `reviewer_credentials` — MD / DO / DEA / NP / RN etc.
- `auth_method` — SAML_SSO / OIDC / direct (direct flags for audit)
- `session_token_hash` — for non-repudiation tie-back if challenged
- `client_review_started_at` / `client_review_decided_at` — timing the
  customer measured (used for review-time enforcement; see below)

### BAA chain — Vera does not BAA with hospitals

Cleveland Clinic does not need a direct BAA with Vera. The standard
HIPAA Subcontractor BA chain:

```
Cleveland Clinic (CE)
  ↓ BAA ↓
Abridge (BA)
  ↓ BAA ↓  (flows down all obligations)
Vera (Subcontractor BA)
```

Abridge's BAA with Vera covers the subcontract. This is huge for sales
velocity: one BAA per Abridge-tier customer, not one per hospital. AWS,
Snowflake, Datadog all operate this way.

### What the regulations require (the hard rules)

| Requirement | Source | Vera enforces |
|---|---|---|
| Reviewer has authority to override | EU Art. 14(4)(d); CO SB 26-189 | API requires `decision ∈ {approve, modify, reject}`; no `defer` |
| Reviewer is not original decision-maker | CO meaningful review | `reviewer_id ≠ originating_agent_id`; flag if same human always reviews own AI assistant output |
| Reviewer has required role/credentials | EU Art. 14(1); HIPAA workforce | Callback must include `reviewer_role` matching the gate's required role |
| Decision logged with reviewer ID + timestamp + comment | EU Art. 12; HIPAA § 164.312(b) | Captured in ApprovalRecord, hash-chained |
| Two-person verification for biometric ID | EU Art. 14(5) | v1 doesn't ship biometric ID; gate to v2+ |

### What's flexible (Vera's design choice)

- Channel (in-app webhook / Slack / dashboard / future: SMS, mobile, Teams)
- Review time floor (not statutorily fixed)
- UI presentation (entirely the customer's call when in-app webhook is used)
- Reviewer training (the customer's responsibility, not Vera's)

### Channels (v1 ships three, in-app webhook is the default)

| Channel | When to use | How it works |
|---|---|---|
| **In-app webhook** (default for medtech) | Reviewer is the customer's customer's user (practitioner using customer's product). ~95% of medtech flow. | Vera POSTs webhook to customer; customer renders review UI inside their own app; customer POSTs decision back to Vera with identity attestation. Vera is invisible to the reviewer. |
| **Slack** | Reviewer is the customer's own staff (solo practitioner, compliance officer, small clinic where customer = end user) | Vera posts to the customer's Slack with context + buttons; Slack interactivity → callback. Use when the customer has no separate end-user product to embed in. |
| **Vera dashboard** | Compliance officer at the customer (Abridge's compliance team) wants a batch queue of decisions to audit, not approve in flight | Direct Vera login, queue view. Mostly a forensics surface, not a clinical-flow surface. |

A single customer can use multiple channels concurrently:
- In-app webhook for routine clinical reviews (default routing)
- Vera dashboard for compliance team batch oversight
- Slack for dev/staging traffic from their engineering team

v2 adds: email + magic link, SMS, mobile push, Microsoft Teams, embedded
Vera review widget (React component) for customers who want Vera-controlled
review-time enforcement without rebuilding the UI themselves.

### Minimum review time — measured at the customer, enforced via attestation

**Default: 30 seconds. Configurable per agent action at onboarding.**

Because the review happens inside the customer's app (in-app webhook is
default), Vera does **not** control the UI and cannot directly inject a
2-step "are you sure" confirmation. Instead, Vera measures time at the
boundary and uses attestation:

- The customer's callback includes `client_review_started_at` and
  `client_review_decided_at` (when the customer's UI rendered the prompt and
  when the reviewer clicked).
- Vera also independently measures `webhook_sent_at` → `callback_received_at`
  as a server-side cross-check.
- If either delta is below the configured threshold, the evidence record is
  tagged `reviewed_below_threshold: true` and the customer's compliance
  dashboard surfaces the count.
- The customer's product is **expected** to enforce its own friction (scroll-
  to-bottom-before-enable, 2-step confirmation, etc.) — Vera flags
  violations rather than blocking them.

Customers who want tighter enforcement install the v2 embedded Vera review
widget (React/JS component), which Vera controls fully — including the
2-step confirmation, the scroll-to-bottom gate, and accurate timing.

Why hardcoded threshold vs. dynamic:
- **Predictable for reviewers.** Dr. Smith knows controlled-substance reviews
  take ~60 seconds, routine acknowledgements ~15.
- **Auditable.** A regulator can be told "we required ≥30s on diagnosis
  reviews"; defensible policy. Dynamic adjustment puts Vera's classifier in
  the audit chain — we don't want that.
- **No automation-bias surface.** If Vera dynamically said "this is
  low-stakes, speed-review it," and a regulator finds a missed harm, Vera is
  implicated. Customer-set thresholds keep responsibility on the customer.
- **Simpler to ship.** One number per agent action class, wizard time.

Dynamic adjustment is v2.

### Example review prompt — rendered inside the customer's app

This is what Dr. Smith sees, **inside Abridge's product, branded Abridge,
with no Vera surface visible**:

```
┌─ Visit needs your review ─ Mr. Jones (2:47 PM) ─────────────┐
│                                                              │
│ AI suggested changes to this chart:                          │
│                                                              │
│   NEW DIAGNOSIS:  acute pancreatitis                         │
│   NEW ORDERS:                                                │
│     • morphine 4mg IV q4h prn  (Schedule II)                 │
│     • NPO                                                    │
│     • LR 100 mL/hr                                           │
│                                                              │
│ Why your review is needed: new diagnosis + Schedule II med   │
│                                                              │
│ Source: AI-generated from your 2:47 PM visit recording       │
│ Lab note: lipase 450 (elevated)                              │
│                                                              │
│   [ Approve ]   [ Modify ]   [ Reject ]                      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Notice: no "Powered by Vera," no compliance / audit branding, no
"submitted to Vera." From Dr. Smith's perspective, Abridge is doing the
responsible thing — surfacing AI suggestions before commit. Vera is the
audit substrate underneath, invisible.

Modify opens an edit dialog. Reject requires a comment. Both flow back to
Vera through the webhook callback.

### Webhook delivery semantics (the unhappy path)

Vera POSTs to the customer's configured endpoint with exponential backoff
on failure: 1m → 5m → 30m → 2h → 8h → 24h → abort. After 24h of failed
delivery, the review surfaces on Vera's dashboard with `delivery_failed`
status; the action remains `PENDING_REVIEW` (neither approved nor
blocked). The customer's compliance team must manually escalate or
reconfigure the endpoint.

**Idempotency.** review_ids are globally unique. Customer's callback can
POST the same review_id multiple times; only the first attestation is
recorded as the canonical decision. Subsequent attestations are logged
as "attestation conflict" if they differ (e.g., two reviewers race to
approve).

**Expiry.** Each review has a configurable expiry (default 4h for
medtech, set per agent action). On expiry, Vera POSTs `review.expired`
to the customer's webhook. The action remains in `PENDING_REVIEW` state
in Vera until the customer takes action (re-route to another reviewer,
escalate, or surface as denial to the end user). The audit trail records
the expiry + any subsequent resolution.

**Credentials mismatch.** If the customer's callback attests a reviewer
with credentials that don't match the gate's required role (e.g.,
attesting an RN for a Schedule II controlled-substance review that
required DEA), Vera rejects the callback with HTTP 403
`reviewer_credentials_insufficient`. The review remains pending. The
rejection is logged in the audit trail — regulators see "the customer
attempted to attest a reviewer without required credentials; Vera
correctly rejected."

---

## Failure modes — what the customer's software handles

Three outcomes from `@vera.gate`:

### 1. Pass (normal return)

```python
@vera.gate(action="commit_chart_note")
def commit_chart_note(note: dict) -> dict:
    # model produces draft
    return note
```

Vera captures evidence + signs. Customer's code receives the return value
unchanged. Most actions hit this path.

### 2. Pending review (async — most common denial in medtech)

```python
try:
    final_note = commit_chart_note(draft)
except vera.PendingReview as p:
    # p.review_id, p.expected_resolution, p.webhook_url
    customer_ui.show_status("Note submitted for physician review.")
    customer_db.register_pending(p.review_id, draft)
```

When reviewer approves (via Slack/in-app/dashboard), Vera POSTs to the
customer's webhook:

```json
POST /vera-webhooks/review-complete
{
  "review_id": "rev_8b2c...",
  "decision": "approve",
  "modified_payload": null,
  "reviewer_id": "user_dr_smith",
  "reviewer_comment": "Confirmed pancreatitis on labs",
  "signed_evidence_url": "https://app.usevera.xyz/evidence/...",
  "timestamp": "2026-05-18T17:23:00Z"
}
```

Or with modification:

```json
{
  "decision": "modify",
  "modified_payload": {
    "new_diagnoses": ["acute pancreatitis"],
    "new_medications": [
      {"name": "morphine", "dose": "2mg", "freq": "q4h"}
    ]
  },
  ...
}
```

Or rejection:

```json
{
  "decision": "reject",
  "reviewer_comment": "Lab values don't support pancreatitis dx; recommend re-record visit",
  ...
}
```

Customer's app commits the modified version (or surfaces rejection to user).
The "AI suggested X, human approved Y, final is Y" lineage is captured cleanly
in the evidence chain.

### 3. Hard block

```python
try:
    final_note = commit_chart_note(draft)
except vera.PolicyBlock as e:
    # e.reason, e.citation, e.fix_url, e.retryable
    customer_ui.show_error(f"AI charting unavailable: {e.user_facing_reason}")
    customer_ops.alert(e)
```

Rare in medtech — mostly fires on stale BAA, prohibited use detected, or
schema-violating output. Customer's app shows a clear error to the user and
notifies their ops team.

### Retry loops — explicitly: do not auto-retry

Vera does **not** automatically re-run the customer's agent on denial. That's
a runaway-loop risk and a separation-of-concerns violation. The customer's
agent design owns whether to:

- Surface to user (let them decide)
- Re-run with adjusted parameters
- Drop the action
- Escalate

Vera provides the *signal* (denial.reason, denial.fix_url, denial.retryable)
so the customer can build intelligent handling. Vera does not orchestrate it.

### UX patterns the customer's app must support

1. **"In review" state** in the customer's UI — spinner, "submitted for
   physician review," optional queue position.
2. **"Denied" state** — clear non-technical reason. Vera returns
   `e.user_facing_reason` separate from `e.developer_reason`.
3. **"Modified by reviewer" state** — show diff between AI suggestion and
   approved version.
4. **Webhook listener** — subscribe to `review-complete`, `review-expired`,
   `review-escalated`.
5. **Audit surface (optional)** — let user click on a chart entry to see
   "reviewed by Dr. Smith at 2:47 PM, who changed morphine 4mg → 2mg before
   approving."

UX patterns 1-4 are non-negotiable for any medtech integration. Pattern 5 is
nice-to-have but increases trust visibly.

---

## SDK contract (Python)

```python
import vera
from vera.packs import ClinicalScribePack

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="abridge-scribe",
    agent_version="3.2.1",
    model_id="gpt-4o-scribe-finetune",
    pack=ClinicalScribePack(
        jurisdiction="US-FEDERAL",
        reviewer_routing="webhook",   # default for medtech; or "slack" / "dashboard"
        review_webhook_url="https://api.abridge.com/vera-reviews",
        review_thresholds={
            "new_diagnosis": 30,             # seconds
            "controlled_substance": 60,
            "routine_chart_entry": 15,
        },
    ),
)

@vera.gate(action="commit_chart_note")
def commit_chart_note(
    patient_id: str,
    visit_id: str,
    new_diagnoses: list[str],
    new_medications: list[dict],
    new_orders: list[str],
    note_text: str,
) -> dict:
    # The customer's existing scribe logic. No changes needed.
    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "new_diagnoses": new_diagnoses,
        "new_medications": new_medications,
        "new_orders": new_orders,
        "note_text": note_text,
    }
```

What the decorator does:

1. Wraps the function call.
2. Builds a Context object from kwargs + Vera init config + customer's
   declared system manifest.
3. Runs the pack's `pre_action_gate(ctx)` synchronously → returns a Ruling.
4. If `Ruling.effect == ALLOW`: invoke the function, capture inputs/outputs,
   write signed ActionRecord, return the result.
5. If `Ruling.effect == REQUIRE_HITL`: invoke the function (to compute the
   draft), but instead of returning it, queue an Approval, raise
   `vera.PendingReview`. Customer's webhook gets called on completion.
6. If `Ruling.effect == BLOCK`: do not invoke the function. Raise
   `vera.PolicyBlock`.

The customer's agent code is unchanged in 95% of cases. They write their
business logic; Vera intercepts at the boundary.

For framework-specific integrations (LangChain, CrewAI), Vera ships hooks via
`from vera.integrations.langchain import VeraTool` etc. — existing
[sdk/vera/integrations/](sdk/vera/integrations/) module gets a medtech-aware
extension.

---

## How we classify without LLMs (concrete proof)

Three realistic medtech scenarios. Zero LLM calls at runtime.

### Scenario 1 — AI scribe chart entry

Scribe outputs structured data:

```json
{
  "new_diagnoses": ["acute pancreatitis"],
  "new_medications": [
    {"name": "morphine", "dose": "4mg", "freq": "q4h", "rx_norm_id": "7052"}
  ],
  "new_orders": ["NPO", "LR 100mL/hr"]
}
```

Pack logic:

```python
class ClinicalScribePack:
    def pre_action_gate(self, ctx):
        gates = []

        if ctx.payload.get("new_diagnoses"):
            gates.append(Gate(
                effect="REQUIRE_HITL",
                role="attending_physician",
                reason="New diagnosis — physician sign-off required",
                citation="HIPAA § 164.312(b) + Section 1557 § 92.210",
            ))

        controlled = self._check_dea_schedule(ctx.payload.get("new_medications"))
        if controlled:
            gates.append(Gate(
                effect="REQUIRE_HITL",
                role="dea_licensed_physician",
                reason=f"Controlled substance: {controlled}",
                citation="21 CFR 1306.04",
            ))

        if not self._baa_valid(ctx.org_id):
            gates.append(Gate(
                effect="BLOCK",
                reason="BAA expired",
                citation="HIPAA § 164.504(e)",
            ))

        return strictest(gates)
```

Structural checks against curated reference data. RxNorm IDs lookup against a
static DEA-published schedule list (~3000 entries, quarterly refresh). No LLM.

### Scenario 2 — AI receptionist scheduling

Voice agent emits:

```json
{
  "intent": "schedule_appointment",
  "appointment_type": "annual_physical",
  "datetime": "2026-06-15T10:00",
  "model_version": "voice_v2"
}
```

```python
class ReceptionistPack:
    AUTHORIZED_INTENTS = {
        "schedule_appointment", "reschedule", "cancel",
        "answer_office_hours", "transfer_to_human",
    }
    HIGH_STAKES_INTENTS = {
        "medical_advice", "prescription_request", "test_results",
    }

    def pre_action_gate(self, ctx):
        intent = ctx.payload.get("intent")
        if intent not in self.AUTHORIZED_INTENTS | self.HIGH_STAKES_INTENTS:
            return Gate(effect="BLOCK", reason=f"Intent {intent} not authorized")
        if intent in self.HIGH_STAKES_INTENTS:
            return Gate(effect="REQUIRE_HITL", role="clinical_staff")
        if not self._disclosure_emitted_for_call(ctx.payload.get("call_id")):
            return Gate(
                effect="BLOCK",
                reason="AI disclosure not emitted at call start",
                citation="CA SB 243 + EU Art. 50(1) + TX TRAIGA healthcare",
            )
        return Gate(effect="ALLOW")
```

Intent classification is the agent's job (customer's domain). Vera enforces
the intent is in the authorized list + disclosure was emitted. No LLM.

**Counter-example.** Patient describes chest pain. Agent's intent classifier
mistakenly labels this `schedule_appointment` (routine). Is this Vera's
problem?

**No.** The agent's clinical-risk detection is the customer's domain expertise
and clinical liability. Vera enforces *structural* compliance — was the action
in scope, was the user notified of AI, was the decision logged. Vera does not
second-guess the agent's clinical judgment. Trying to do so would put Vera in
the medical-liability chain, which is the opposite of what we want.

This is the critical boundary: **customers do domain classification; Vera
enforces structural compliance.**

### Scenario 3 — Prior-authorization denial

```json
{
  "decision": "deny",
  "procedure_code": "70553",
  "denial_reasons": ["medical_necessity_not_established"],
  "amount_at_risk": 2400.00
}
```

```python
class PriorAuthPack:
    def pre_action_gate(self, ctx):
        if ctx.payload.get("decision") == "deny":
            if not ctx.payload.get("denial_reasons"):
                return Gate(effect="BLOCK",
                            reason="Denial without reasons is not permitted")
            invalid = [r for r in ctx.payload["denial_reasons"]
                       if r not in PA_DENIAL_TAXONOMY]
            if invalid:
                return Gate(effect="BLOCK",
                            reason=f"Invalid reason codes: {invalid}")
            if ctx.payload.get("amount_at_risk", 0) > 2000:
                return Gate(effect="REQUIRE_HITL", role="rcm_lead",
                            reason=f"Adverse decision >$2K")
        return Gate(effect="ALLOW")
```

Pure structural checks against a static taxonomy (~50 entries, CMS-aligned).
No LLM.

### Where LLMs *might* show up (and where they don't)

| Use | Runtime? | v1? | Model class |
|---|---|---|---|
| Structural compliance gates | Runtime | ✅ Deterministic, no LLM | n/a |
| Free-text → structured extraction (for scribes outputting unstructured notes) | Runtime, opt-in | Optional add-on; ~$0.001/call if enabled | Haiku-class |
| Reviewer message polish | Runtime | v1 ships templates; optional polish in v2 | Haiku-class |
| Drift / anomaly detection over action stream | Batch (nightly) | v2 | Haiku-class |
| **AI-generated compliance insights** (Compliance Posture page) | On-demand only | ✅ v1, when user clicks "Show insights" | Haiku-class |
| Policy authoring assistant | On-demand | v2 | Haiku-class |
| Auditor Q&A bot | On-demand | v3 | Sonnet-class |
| Document narrative generation in compliance PDFs | Batch (per report) | v1 optional flag, ~$0.02/PDF | Haiku-class |

**v1 default: zero runtime LLM calls in the gate path.** Frontier LLM is
never needed — Haiku-class is sufficient for every LLM use Vera has,
because each use is a narrow, structured task (schema-bound extraction,
insight generation against a known data shape, polish over a template).

### Real-time mode for voice agents (latency-sensitive)

Default gate mode is **sync**: gate evaluates synchronously, action
blocks if HITL needed, function returns / raises after Ruling.

For real-time agents (voice receptionists, live triage), 100-1500ms gate
latency may be unacceptable. Vera offers a **real-time mode**:

```python
@vera.gate(action="answer_caller", realtime=True)
def answer_caller(...):
    ...
```

In real-time mode:
- Deterministic gates run instantly (<10ms); ALLOW or BLOCK returns
  immediately
- HITL gates return `REQUIRE_DEFERRED_REVIEW` — action proceeds, review
  is queued for *post-action* sign-off
- LLM extraction (if enabled) runs async; evidence is captured after the
  action

Trade-off: loses pre-action HITL enforcement. The audit PDF explicitly
labels deferred-review decisions: "12 decisions reviewed post-action
(real-time mode)." Regulators see the trade-off, can interrogate the
customer about why real-time was justified.

Real-time mode is per-agent, opt-in. Off by default. Recommended only
where latency is genuinely operational (voice, real-time triage). Not
recommended for batch / async workloads where sync mode is free.

### Free-text extraction fallback (optional, opt-in)

For customers whose agent emits free-text rather than structured fields,
Vera ships an opt-in extraction helper:

```python
@vera.gate(
    action="commit_chart_note",
    extraction=vera.LLMExtract(
        schema={
            "new_diagnoses": "list of new clinical diagnoses",
            "new_medications": "list of {name, dose, freq, rx_norm_id?}",
        },
    ),
)
def commit_chart_note(free_text: str):
    ...
```

When enabled:
- Vera calls Haiku-class LLM to extract structured fields from free text
- Cost: ~$0.001 per extraction
- Logged on every decision: `extraction_method: "llm_haiku_2026_05"`
- Audit PDF discloses: "Of 2,847 decisions, 3 used LLM extraction (customer opted in for free-text scribe output)."

Off by default. Customer's product is expected to emit structured fields
in the vast majority of cases (they already do, because their downstream
EHR / payment / database systems require structured data).

---

## Cost model

### Runtime per action

| Component | Cost |
|---|---|
| Postgres write (action record + hash) | ~$0.0000005 |
| Compute (predicate evaluation, hash chain) | ~$0.0000005 |
| Network egress | ~$0.0000001 |
| S3 archive after 30 days | ~$0.0000002 |
| **Per action** | **~$0.000001** |

### HITL per event

| Component | Cost |
|---|---|
| Slack API call | $0 (within rate limits) |
| Webhook delivery | ~$0.0000005 |
| DB writes (review record, reviewer lookup) | ~$0.000001 |
| **Per HITL event** | **~$0.000002** |

### Artifact generation

| Artifact | Per-instance cost |
|---|---|
| Compliance PDF (ReportLab, deterministic) | $0 compute + $0.0001 storage |
| Per-decision evidence package | $0 compute |
| Adverse-action / chart modification notice | $0 (template fill) |
| NIST AI RMF posture (auto-refresh weekly) | $0 |
| Disparate-impact monitoring report (weekly) | $0 |
| Optional: LLM polish on PDF narrative | ~$0.02/PDF |

### Per-customer monthly total (1M actions, 5% HITL rate)

| Component | $ |
|---|---|
| Runtime (1M actions) | 1.00 |
| HITL (50K events) | 0.10 |
| Artifact generation | 0.25 |
| Storage (12 months hot retention) | 0.50 |
| Infra overhead (CDN, monitoring, k8s baseline, RDS minimum) | 5.00 |
| Customer support / human-ops (loaded allocation) | 25.00 |
| **Total marginal cost** | **~$32/customer/month** |

At $50-150K ACV ($4-12K MRR) → **gross margin 99%+.**

### Scaling

| Scale | Compute cost / mo | Inflection |
|---|---|---|
| 10 customers | $320 | None |
| 100 customers | $3.2K | Need on-call rotation, monitoring depth |
| 1,000 customers | $32K | Postgres ActionRecord sharding becomes necessary at ~100M actions/mo aggregate; hash chain checkpointing already batches |
| 10,000 customers | $320K | Data engineering team, multi-region |

The actual scaling bottleneck is not compute. It is:

- **Customer support burden** on compliance questions (the consultative
  load). Hire #1 should be a regulatory-savvy support engineer, not a
  backend engineer.
- **BAA / legal contract administration**. Standard BAA + customer redlines
  + signature workflow. Solvable with DocuSign + a part-time legal ops.
- **Legal-opinion library**. As new packs ship (lending, hiring, EU), each
  needs its own legal opinion. Budget $25-50K per opinion.

Plan for those, not for compute.

---

## Compliance Posture — Vera's runtime-state measurement

Six **universal dimensions** that apply across every vertical (medtech,
lending, hiring, insurance). Each pack declares per-dimension inputs;
the math is the same across packs. No LLM in the score formula;
on-demand AI insights (Haiku-class) labeled "recommendations not
regulatory advice."

| Dimension (universal) | What it measures | Weight | Medtech inputs | Lending inputs |
|---|---|---|---|---|
| **Artifact freshness** | % of required artifacts current and unexpired | 20% | BAA, HIPAA RA, Section 1557 Policy, NIST RMF | ECOA model docs, Fair Lending Policy |
| **HITL completion** | % of decisions requiring HITL that received it before commit | 25% | Physician sign-off on diagnoses | Loan officer review on adverse decisions |
| **Reviewer integrity** | % of HITL events meeting threshold AND with correct credentials | 15% | Min review time + MD/DEA validation | Min review time + role validation |
| **Notice delivery rate** | % of required notices delivered (renamed from "attestation rate" for cross-vertical use) | 10% | Patient AI-use disclosure | ECOA adverse-action letters within 30 days |
| **Chain integrity** | % of last 30 days with no hash-chain validation failures | 20% | Same | Same |
| **Workflow timeliness** | % of post-action workflows completed within statutory deadlines | 10% | Section 1557 reporting | ECOA 30-day, FCRA dispute |

### Why these dimensions generalize

Every AI regulation Vera enforces decomposes to the same six surfaces
(see [policy-engine-north-star.md](policy-engine-north-star.md)). The
posture dimensions are derived directly from those surfaces — they're
universal because the surfaces are universal. Each pack provides
per-vertical inputs; the engine runs the same math.

### Dimension minimums (low-volume guard)

Each dimension requires a minimum number of data points before
computing a score. Below the minimum, the dimension shows "insufficient
data" rather than a misleading number. Defaults:

- Artifact freshness: any artifact present (no minimum)
- HITL completion: ≥10 HITL-triggering decisions in period
- Reviewer integrity: ≥10 HITL events in period
- Notice delivery rate: ≥5 required notices in period
- Chain integrity: ≥7 days of decisions
- Workflow timeliness: ≥3 timed workflows in period

A customer with 100 decisions and 1 missed deadline doesn't get 9.9/10
based on a single data point — they get "insufficient data, see raw
counts."

### Why "Posture" not "Score"

Compliance is a legal status determined by regulators. Posture is what
Vera observes at runtime. The two are not synonymous, and conflating
them is the Delve trap. Vera's UI consistently uses "posture" to avoid
implying that a 10/10 posture means "you are compliant." A 10/10 posture
means "every runtime check Vera observes is passing."

### Why "Posture" not "Score"

Compliance is a legal status determined by regulators. Posture is what
Vera observes at runtime. The two are not synonymous, and conflating
them is the Delve trap. Vera's UI consistently uses "posture" to avoid
implying that a 10/10 posture means "you are compliant." A 10/10 posture
means "every runtime check Vera observes is passing."

### Constraints

- **Not on the audit PDF** — the PDF contains underlying evidence; auditors don't trust aggregated scores
- **Not in marketing** — internal customer tool, not a sales artifact
- **Not on Hospital detail page in v1** — aggregate is org-wide for v1; per-hospital posture is v2
- **No comparisons** — no "you're better than X% of orgs"

---

## What v1 deliberately does not do

- **No multi-pack composition.** v1 ships one pack (medtech). v2 adds lending,
  v3 adds employment. No customer toggles "EU + Colorado + NYC AEDT" in v1.
- **No customer-authored policies.** No DSL, no UI for policy CRUD. Vera
  authors and ships the medtech pack as opinionated code.
- **No artifact upload UX.** v1 generates evidence; templates are filled out
  via wizard, not uploaded as PDFs.
- **No multi-jurisdictional subject resolver.** US healthcare only. (Patient
  jurisdiction inferred from customer's hospital network.)
- **No periodic obligation scheduler.** Reminder emails ("annual NIST AI
  RMF posture review due in 30 days"). No runtime blocking after deadline.
- **No state-specific overlays.** v1 ships HIPAA + Section 1557 + NIST AI RMF.
  Colorado / Texas / EU come in later packs.
- **No clinical safety classifier.** Customer's agent owns clinical risk
  detection. Vera enforces structural compliance only.
- **No auto-retry.** Denials are signals; customer's agent handles
  retry/escalation/drop.

Every "no" above is an opportunity for v2. Every "no" keeps v1 sellable in 8
weeks.

---

## Sales path without 100 customer logos

We're selling AI-deploying engineering teams a runtime infrastructure layer.
Their evaluation hierarchy:

1. Can I install it in 5 minutes? (yes — `pip install vera`, decorator)
2. Does the PDF satisfy my customer's procurement / auditor? (yes — sign-off
   from credible authority needed)
3. Is this real, or a slide deck? (yes — open-source SDK, signed evidence,
   demo)
4. Will my counsel accept it? (yes — legal opinion + NIST AI RMF mapping)

Five substitutes for customer logos:

### 1. The 5-minute live install

On every sales call, the prospect's engineer types `pip install vera`, adds a
decorator, runs an action, sees it in the dashboard. The demo *is* the proof.
No reference customers needed because the buyer proves it themselves.

### 2. The Big Law HIPAA opinion (one lawyer beats 100 logos)

Commission a written opinion from a healthcare-tech practice (Hogan Lovells,
Ropes & Gray, McDermott Will & Emery, Wilson Sonsini's healthtech group):

> "Vera's signed evidence chain and HITL routing satisfy the audit-controls
> requirement of 45 CFR § 164.312(b) and constitute reasonable efforts to
> mitigate AI discrimination risk under HHS Section 1557 § 92.210."

Budget: $30-60K. Pull-quote becomes the homepage hero. Strategy doc names this
as a 6-month goal — bring it forward to month 1-2.

### 3. The NIST AI RMF mapping document (free trust artifact)

Publish a public 8-page PDF: *How Vera's Runtime Controls Satisfy NIST AI
RMF v1.0 Govern/Map/Measure/Manage.* Compliance officers ask for this first;
pre-empt the ask. NIST RMF is a public federal framework, no license issues.

### 4. The open-source SDK as social proof

[vera-sdk on PyPI](https://pypi.org/project/vera-sdk/) under MIT. Download
counts substitute for customer logos in the early sales narrative. Engineering
buyers trust open-source SDK + polished SaaS more than closed-source compliance
tool with logos.

### 5. The audit-firm channel partnership

One mid-tier accounting / healthcare-compliance consultancy (think CliftonLarsonAllen
healthcare group, Plante Moran, or boutique HIPAA shops) endorses Vera as
their recommended tool for AI-deploying healthcare clients. They become a
sales channel. Their lead generation > 100 logos.

Cost: a co-marketing partnership, possibly revenue share. Sell into one
auditor, and every HIPAA engagement they run mentions Vera.

### Pitch (memorize)

> "You don't need 100 reference customers. You need a Big Law HIPAA opinion in
> your hand, a NIST AI RMF mapping on your website, an auditor in your corner,
> and a 5-minute live install. Vera ships all four — and the runtime
> evidence layer that makes every AI chart entry audit-ready, signed, and
> defensible against a procurement RFP from any hospital in the country."

---

## 8-week shipping plan

### Weeks 1-2: Core engine extension (existing code)

- Add 5 fields to ActionRecord: `subject_jurisdiction`, `domain`,
  `use_class`, `action_class`, `reason_codes`. Use metadata blob for v1
  to avoid schema churn.
- New `pre_action_gate` endpoint: `POST /v1/gates/evaluate`. Returns Ruling
  with `effect`, `reason`, `citation`, `review_id?`, `fix_url?`.
- New `ClinicalScribePack` Python module under `backend/app/packs/clinical/`.
  Three gates, hardcoded predicates.
- Webhook delivery for `review-complete`, `review-expired`,
  `review-escalated` events. Reuse existing webhook infrastructure.
- **Off-Vera checkpoint mechanism**: daily KMS-signed chain-head export to a
  customer-controlled S3 bucket + OpenTimestamps anchor. `vera verify
  --offline` works without contacting Vera. Removes "what if you shut down"
  procurement objection. ~5 days of engineering.

### Weeks 3-4: SDK + integrations

- `@vera.gate` decorator update for sync ruling handling.
- `vera.PendingReview`, `vera.PolicyBlock` exception classes.
- Slack channel routing (Bolt SDK).
- In-app webhook channel.
- CLI: `vera verify`, `vera review-status <id>`.
- Medtech-specific redaction schema (HIPAA Safe Harbor) as default.

### Weeks 5-6: Frontend

- Onboarding wizard (5 questions): vertical (medtech only in v1, hardcoded),
  agent type, decision volume tier, jurisdiction (US healthcare default),
  reviewer routing channel.
- Coverage map dashboard (single page).
- Review queue UI (for dashboard-channel reviewers).
- "Generate HIPAA AI Audit Trail" button → ReportLab PDF.
- Templates section: customer fills out HIPAA Risk Analysis skeleton,
  Section 1557 Nondiscrimination Policy. Red-banner-on-every-section design.

### Weeks 7-8: Legal + GTM

- **Big Law HIPAA opinion** — engagement letter signed Week 1; first counsel
  review of PDF template Week 4; opinion lands ~Week 12-16 (Big Law opinions
  take 3-6 months; the *engagement* must start in Week 1, the *letter* is
  not gating v1 ship).
- Publish NIST AI RMF mapping document (PDF + website page).
- BAA template finalized, e-sign workflow live.
- 3 paid pilot conversations (target: Abridge-like Series A scribes).
- YC application submitted.

### Data retention & residency (v1)

- **Action records**: 6-year retention (HIPAA § 164.316 default), hot in
  Postgres for 12 months, then archived to S3 Glacier.
- **PHI payloads**: encrypted at rest (AES-256-GCM, customer-scoped keys
  via AWS KMS), redacted free-text via HIPAA Safe Harbor pattern.
- **Identity attestations**: stored alongside ActionRecord (reviewer_id,
  role, session_token_hash) for non-repudiation tie-back.
- **Off-Vera checkpoints**: customer-controlled S3 bucket, customer owns
  the lifecycle.
- **Residency**: v1 is US-only (us-east-1 + us-west-2 multi-AZ). EU
  residency is a v2 / EU-pack concern (Frankfurt + Dublin).
- **Vera staff access**: no access to customer PHI payloads. Vera staff
  can see aggregate metrics, hash chain integrity, and gate decision
  metadata, but not raw inputs/outputs. Enforced by IAM + audited.

---

## Appendix A — Wizard onboarding flow (5 questions)

```
1. What kind of AI agent are you running?
   ○ AI scribe / chart entry assistant
   ○ AI receptionist / voice agent
   ○ AI prior-auth / claims agent
   ○ AI triage / symptom checker
   ○ Other clinical AI

2. What jurisdictions do you operate in?
   ☑ US Federal (HIPAA + Section 1557)  [required, can't deselect]
   ☐ California (CMIA add-on)
   ☐ Other state-specific (v2)

3. How many AI decisions per month, roughly?
   ○ < 10,000     (Starter)
   ○ 10K - 100K   (Growth)
   ○ 100K - 1M    (Scale)
   ○ > 1M         (Enterprise)

4. Which channel for human review?
   ○ In-app webhook (default — your product handles review UI;
                     Vera invisible to your end users)
   ○ Slack (for solo practitioners or your own dev/compliance team)
   ○ Vera dashboard (compliance officer batch oversight, not clinical flow)
   ○ Multiple (combine — e.g., webhook for clinical, dashboard for compliance)

5. Your designated HIPAA Privacy Officer (name + email):
   [text input]

→ On submit, generate: HIPAA Risk Analysis template skeleton,
  Section 1557 Nondiscrimination Policy skeleton, BAA draft for review.
  Customer fills in templates; counsel reviews; signs.
```

---

## Appendix B — The honest pitch deck slide

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  Vera makes your AI auditable.                               │
│                                                              │
│  We do not make you HIPAA-compliant.                         │
│  We make every AI decision provable.                         │
│                                                              │
│  • Every chart entry, signed                                 │
│  • Every diagnosis, physician-reviewed                       │
│  • Every controlled substance, DEA-authority-checked         │
│  • Every audit log, hash-chained                             │
│  • Every NIST AI RMF function, mapped                        │
│                                                              │
│  Your hospital procurement asks: "show us audit logs."       │
│  We give you the answer in one PDF.                          │
│                                                              │
│  pip install vera                                            │
│  @vera.gate                                                  │
│  Done.                                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

This slide does not lie. Every claim above is structurally true if Vera is
installed correctly. No Delve trap.

---

## Appendix C — What this MVP teaches us before we build packs 2-N

After 8 weeks shipping + 5-10 paid medtech customers, we will have learned:

1. **Whether the SDK contract is too thin or too thick.** v1 ships a small
   surface; we'll see what customers ask for. v2 adds *only* what they ask for,
   not what we imagine.

2. **What HITL throughput limits look like.** 50K HITL events/month/customer
   was our estimate. Reality will tell us.

3. **Whether the PDF satisfies real auditors.** We'll watch which sections
   procurement and counsel actually read, and what they ask for.

4. **What the Big Law opinion actually says (vs. what we hope).** The opinion
   shapes future packs.

5. **Which adjacent verticals show up in inbound.** Probably lending and
   hiring. Maybe legal-tech. The roadmap should follow inbound, not our prior
   plan.

The full architecture in [policy-engine-north-star.md](policy-engine-north-star.md)
is the destination. The MVP is how we earn the right to build it. Every
primitive in v1 is a strict subset of the north-star design — no throwaway
code, no rewrites, just additive growth.
