# Vera: Strategy & Direction

**Last updated:** April 26, 2026
**Authors:** Advik, Priyansh
**Status:** Active. Replaces all prior planning docs.

---

## TL;DR

We are not pivoting away from the AI trust/compliance + insurance space. We are **sharpening the wedge** within it.

Vanta sells **paperwork** to GRC buyers. We sell **runtime evidence** to platform engineering buyers. Different product, different buyer, often complementary inside the same customer.

Our long-term thesis is unchanged: build the trust layer for AI agents, capture the runtime decision data, become the data backbone of the AI insurance market.

What changes is how we **frame, sell, and sequence** the work.

---

## What we are now (one-liner)

**Vera** — the runtime trust layer for AI agents in regulated industries. A Python SDK that enforces policy, routes high-risk actions to human approval, and produces cryptographically-signed, court-admissible logs of every consequential agent decision.

Internal codename can stay Vera v2. External name to land on this week (working name: Vera).

---

## Why this, why now

### The forced-buyer deadline stack

| Date | Event | Forces buying |
|---|---|---|
| Jan 1, 2026 | CA AB 316 effective | Removes "the AI did it autonomously" defense |
| Jan 1, 2026 | Verisk CG 40 47 / CG 40 48 endorsements live | General liability policies now exclude AI claims |
| 2026 | FINRA 2026 GenAI supervision rules | Broker-dealers must "track and log AI agent actions" |
| Jun 30, 2026 | Colorado AI Act effective | High-risk AI systems require documented oversight |
| Aug 2, 2026 | EU AI Act Article 14 (human oversight) + Article 72 (post-market monitoring) | Up to €15M / 3% global turnover |

Four of these land inside the YC S26 batch window.

### The competitive map after Vanta's announcement

| Layer | Product | Buyer | Examples |
|---|---|---|---|
| Paperwork | Policies, ISO 42001 docs, audit prep | GRC / compliance team | **Vanta**, Drata, Secureframe |
| Certification | Point-in-time third-party audits | Security / procurement | **AIUC** (AIUC-1), Trustible |
| Insurance | Affirmative AI liability coverage | Risk / legal | **Armilla**, **AIUC**, **Testudo**, Munich Re, Beazley, Chubb |
| **Runtime (us)** | **SDK that enforces policy and signs every action** | **Platform engineering** | **Vera** |

We are not competing with Vanta. We sit one layer below.

---

## Founder-market fit (why us)

- We have shipped Vera (cryptographic hash chain + KMS signing + policy engine + HITL + Python SDK). ~80% of Vera reuses this code.
- We did the EU AI Act regulatory research already — months of work most teams will not redo in time.
- LeapYear interviewed us and it went well in this exact space.
- Wondr's defensibility rejection was the lesson: build moats out of regulation and data, not engineering. We've done that here.
- Network access in fintech/healthtech for first 5–10 paying pilots.

---

## The two-act story (this is the pitch)

### Act 1 — Compliance SDK (Year 1, $1M ARR target)

Sell Vera to AI agent vendors and enterprises deploying agents in regulated workflows. Year-1 ACV $50K–$150K, evolving to per-action pricing ($0.001–$0.01) at scale.

**ICP**: AI agent vendors in fintech and healthtech, plus mid-market enterprises deploying third-party agents in regulated workflows.

**Wedge**: "You need this to ship under FINRA 2026 / CA AB 316 / EU Article 14. Vanta proves you have a policy. We prove you followed it on this exact decision."

### Act 2 — Insurance data network (Series A and beyond, $1B+ ceiling)

Sitting in the runtime path of every signed agent decision across hundreds of customers gives us the single most valuable underwriting dataset in AI insurance.

The carriers we researched are openly admitting the data gap:
- Armilla raised $25M (Jan 2026) underwriting from governance signals + their own audits
- AIUC certifies against AIUC-1 with annual + quarterly retests
- Testudo underwrites from external proxy data because integration is too hard

None of them have continuous behavioral telemetry. We do.

**Three monetization paths from there:**

1. **Data licensing** — sell anonymized behavioral feeds to Armilla, AIUC, Testudo, Munich Re, Beazley, Chubb at $200K–$2M/year per carrier
2. **Become an MGA** — underwrite directly off our own data (Bitsight → cyber insurance arc)
3. **Strategic acquisition** — major reinsurer wants the data exclusively

**This is the vision section of the pitch, not the wedge.** We do not pitch insurance as the Year-1 product.

---

## Positioning and language

### Words to use
- "Trust infrastructure for the agent economy"
- "Runtime evidence layer"
- "Cryptographically-signed agent action logs"
- "Court-admissible audit trail"
- "Insurance data substrate" (only in long-term context)

### Words to avoid
- "AI compliance" — pattern-matches to Vanta, sounds tired
- "AI governance" — too horizontal, no urgency
- "Audit trail SaaS" — undersells

### One-line pitch (memorize)
> "Vanta proves you had a policy. Vera proves you followed it on this exact decision. We're the runtime trust layer the agent economy needs to be allowed to act in regulated industries — and every signed log we collect becomes the underwriting dataset for the AI insurance market."

### How we answer "Isn't this just Vanta?"
> "Vanta sells policy documents to compliance teams. We sell runtime enforcement to platform engineering teams. Different buyer, different PO, often bought together. Vanta is our friend, not our competitor — and Erik Goldman is a Neo mentor."

### How we answer "Won't foundation models subsume this?"
> "Foundation models cannot subsume cryptographic non-repudiation, regulatory compliance under FRE 901/902, or insurance data network effects. This is a regulatory and data moat, not an engineering moat."

---

## What changed vs. our prior plan

| Topic | Old plan | New plan |
|---|---|---|
| Product framing | "Vera — AI compliance SDK targeting EU AI Act" | "Vera — runtime trust layer for AI agents" |
| Lead pitch | EU AI Act compliance | Forced-buyer regulatory deadline stack (FINRA, CA, CO, EU) + insurance data flywheel |
| Buyer | GRC / compliance | Platform engineering at AI agent vendors and regulated deployers |
| Vertical first | Fintech | Fintech (kept), with healthtech as fast second |
| Vanta | "Threat" | Complementary layer; we sit below them |
| Insurance angle | "Eventually" | Explicit Act 2 in every pitch as the long-term moat |
| Code reuse | Full | Full — same hash chain + KMS + policy + HITL stack |
| Accelerator | LeapYear + YC | LeapYear + YC + **Neo (added)** |

---

## Plan: short / medium / long term

### Short term — this week (Apr 26 – May 4)

**Goal: ship Neo and YC applications with 3 LOIs in hand.**

- [ ] **Today–Mon**: Lock the rename. Decide Vera or alternative. Update all collateral.
- [ ] **Mon–Tue**: 8–10 outreach emails to fintech/healthtech contacts in our network. Single ask: "Would you put a signed pre-action approval SDK in production this quarter?" Target: 3 LOIs by Friday.
- [ ] **Wed**: 1 call with an underwriter at Armilla/AIUC/Testudo. Frame: "We have a thesis on runtime evidence as underwriting input — would love your signal." Goal is to be able to say "we've spoken with N carriers" in the application.
- [ ] **Wed**: Draft Neo Residency application. Lead with technical depth + Act 2 insurance flywheel. Mention Erik Goldman / Vanta complement explicitly.
- [ ] **Thu Apr 30 by 11:59pm PT**: Submit Neo.
- [ ] **Fri**: Draft YC S26 application. Lead with deadline urgency + LOIs + two-act narrative. Answer the defensibility question head-on.
- [ ] **Sat**: Founder video. Same script for both, re-shot for tone if needed.
- [ ] **Sun May 4 by 8pm PT**: Submit YC.

### Medium term — May–August 2026 (batch + Aug 2 EU deadline)

**Goal: 5–10 paying pilots, $250K–$500K ARR, ready for Series Seed at end of batch.**

- Convert 3 LOIs into paid pilots ($25K–$50K each, 90-day deployment)
- Ship on-prem / VPC-isolated deployment by July (table stakes for fintech)
- Get one legal opinion from a Big Law tech practice on FRE 901/902 admissibility of hash-chain logs (use this in sales)
- Run interview week, hopefully accept Neo or YC, ideally both stage if possible
- Aug 2 EU AI Act deadline becomes a forcing function for European pilots
- Begin one carrier conversation about a data-sharing pilot (Armilla most likely first)
- Hire #1: senior backend engineer with a security or fintech background

### Long term — Sept 2026 – end of 2027

**Goal: $3M–$5M ARR, Series A on the back of the insurance data flywheel narrative.**

- 20–40 paying customers across fintech, healthtech, legal-tech
- First data-licensing deal with a carrier (target: Armilla or AIUC)
- Begin MGA exploration with Lloyd's syndicate or US carrier
- Self-host product offering for top-100 banks and insurers
- Hire #2–5: founding GTM, additional backend, security engineer, head of regulatory affairs
- Series A pitch led on Act 2 — "we are the data layer for the AI insurance market and we have N carriers paying for the feed"

---

## Risks and how we manage them

| Risk | Mitigation |
|---|---|
| YC partners pattern-match us as "yet another AI compliance" | Lead with the runtime / insurance framing, not the compliance framing. Drop "compliance" from headline copy. |
| AIUC pivots from certification to runtime telemetry | Speed advantage — we already ship. Build a moat through customer count and signed log volume in the next 12 months. |
| Carriers build their own SDKs | They have not, will not — they are insurers, not SaaS builders. They want feeds, not products. Our role as a vendor-neutral data layer is structurally aligned with all carriers, not just one. |
| Insurance flywheel is 24–36 months out, not Year-1 | Frame it as vision, not wedge. Year-1 revenue is SaaS ACV from the SDK. |
| Fintech requires self-host / VPC | Plan for it from Day 1. Add a month to the engineering roadmap. |
| Court-admissibility claim is legally untested | Get a Big Law opinion in writing in the first 6 months. Until then, say "designed for FRE 901/902 admissibility." |

---

---

## Decisions made

- ✅ Stay in the AI trust / compliance + insurance space
- ✅ Reframe as runtime evidence layer, not compliance
- ✅ Vanta is complementary, not competitive
- ✅ Insurance data network is the Act 2 vision, the SDK is the Act 1 wedge
- ✅ Apply to both Neo (Apr 30) and YC (May 4)
- ✅ ~80% of Vera code is reused; no greenfield rebuild
- ✅ Fintech first, healthtech fast-second
