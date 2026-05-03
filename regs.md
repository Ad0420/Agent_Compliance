# Vera — Regulations Page (Final Tab Structure)

**For usevera.xyz/regulations**
**Last fact-checked: April 29, 2026 against primary sources**

---

## Page header

# Regulations that govern AI agents

Concise reference for the laws shaping AI deployment.

(add the below as a disclaimer btw)
*This page is informational and not legal advice. Vera is an open-source research project — the SDK is published on PyPI under the MIT license. We track AI regulation openly because we're interested in the space and believe accurate references help everyone. Talk to qualified counsel for opinions on your specific situation.*

---

## Tab structure

Seven tabs across the top:

`EU AI Act` | `Colorado` | `Texas` | `California` | `FINRA` | `HIPAA` | `FDA`

Each tab uses the same structure: **What it is → When it hits → Who it affects → Penalties → What it requires.**

---

## Tab 1: EU AI Act

### What it is
Regulation (EU) 2024/1689. The world's first comprehensive AI law. Risk-tiered: prohibited, high-risk, limited-risk, minimal-risk.

### When it hits

| Date | What applies |
|---|---|
| Feb 2, 2025 | Prohibited practices (Article 5), AI literacy obligations |
| Aug 2, 2025 | GPAI model obligations, governance bodies operational |
| **Aug 2, 2026** | **High-risk system obligations (Annex III), transparency rules (Article 50)** |
| Aug 2, 2027 | High-risk AI embedded in regulated products (Annex II) |

A November 19, 2025 Digital Omnibus proposal could link the high-risk application date to the readiness of harmonized standards. As of April 2026, August 2, 2026 remains the binding deadline.

### Who it affects
Any provider or deployer of AI systems used in the EU, including non-EU companies whose AI output reaches EU users. Extra-territorial reach mirrors GDPR.

### Penalties (Article 99)

| Tier | Maximum fine |
|---|---|
| Prohibited practices (Article 5) | €35M or 7% of worldwide annual turnover, whichever is higher |
| High-risk obligations | €15M or 3% of worldwide annual turnover, whichever is higher |
| Incorrect or misleading information | €7.5M or 1% of worldwide annual turnover, whichever is higher |

For SMEs and startups, the fine is capped at the lower of the two amounts.

### What it requires (high-risk systems, applicable Aug 2, 2026)

- Risk management system (Article 9)
- Data governance (Article 10)
- Technical documentation per Annex IV (Article 11)
- Automatic logging of operation (Article 12)
- Transparency to users (Article 13)
- Human oversight (Article 14)
- Accuracy, robustness, cybersecurity (Article 15)
- Post-market monitoring (Article 72)
- Serious incident reporting in 2 / 10 / 15-day windows (Article 73)
- CE marking and EU database registration (Article 71)

---

## Tab 2: Colorado AI Act (SB 24-205)

### What it is
The first comprehensive US state AI law. Targets algorithmic discrimination in consequential decisions. Sometimes called the Anti-Discrimination in AI Law (ADAI).

### When it hits
**June 30, 2026.** Originally February 1, 2026; delayed by SB 25B-004 (signed August 28, 2025).

### Who it affects
**Developers** and **deployers** of high-risk AI systems making or substantially influencing consequential decisions in:
- Education, employment, financial services
- Government services, healthcare, housing
- Insurance, legal services

### Penalties
Violations are unfair trade practices under the Colorado Consumer Protection Act. Enforced exclusively by the Colorado Attorney General. 60-day cure period before enforcement. No private right of action.

### What it requires

**Deployers must:**
- Use reasonable care to prevent algorithmic discrimination
- Maintain a risk management policy (NIST AI RMF or ISO/IEC 42001 satisfy)
- Complete impact assessments annually and within 90 days of substantial modifications
- Notify consumers when AI is used in consequential decisions
- Provide a right to appeal with human review where technically feasible
- Disclose discovered algorithmic discrimination to the AG within 90 days

**Developers must:**
- Provide deployers with documentation, intended-use statements, and impact-assessment artifacts
- Maintain a public statement summarizing high-risk systems offered

---

## Tab 3: Texas Responsible AI Governance Act (HB 149)

### What it is
A targeted AI law focused on prohibited uses. Significantly scaled back during the legislative process from the original proposed framework.

### When it hits
**January 1, 2026** — already in force.

### Who it affects
Entities developing or deploying AI in Texas, advertising or providing products to Texas residents. Most operational obligations apply to **government agencies and healthcare providers**, not private employers.

### Penalties
- Civil penalties up to **$200,000 per violation**
- Texas Attorney General has exclusive enforcement
- 60-day cure period
- No private right of action

### What it requires

**Prohibited uses** (apply broadly, including private sector):
- AI intended to incite self-harm, violence, or criminal activity
- AI producing or distributing child sexual abuse material
- AI used to create unlawful deepfakes or impersonate minors in sexual contexts
- AI deployed with intent to discriminate against protected classes (intent-based; disparate impact alone is not sufficient)

**Disclosure obligations:**
- Government agencies: must disclose AI use in consumer interactions
- Healthcare providers: must disclose AI use in patient treatment

**Affirmative defense**: compliance with NIST AI Risk Management Framework provides a defense against enforcement.

Important note: private-sector employers are not required to conduct impact assessments or implement risk-management policies under TRAIGA.

---

## Tab 4: California AI Laws

California has enacted multiple AI laws with staggered effective dates.

### AB 316 — Artificial Intelligence: Defenses

**Effective January 1, 2026** — already in force.

Adds Civil Code §1714.46. Prohibits defendants who developed, modified, or used AI from asserting that the AI "autonomously caused the harm" as a defense in civil actions. Does not create strict liability — plaintiffs must still prove causation and foreseeability — but removes one specific defense argument.

### AB 2013 — Generative AI Training Data Transparency Act

**Effective January 1, 2026** — already in force.

Developers of generative AI systems publicly available to Californians must publish a high-level summary of training datasets, including IP status, personal information presence, and synthetic data usage. Applies retroactively to systems released or substantially modified on or after January 1, 2022.

### SB 942 — California AI Transparency Act (CAITA)

**Effective August 2, 2026** (delayed from January 1, 2026 by AB 853 signed October 13, 2025 to align with EU AI Act).

Applies to generative AI providers with **over one million monthly users in California**. Requires:
- Free, publicly accessible AI detection tool
- Manifest disclosures (visible AI labels)
- Latent disclosures (embedded metadata, technically permanent or extraordinarily difficult to remove)

**Penalty: $5,000 per violation per day.**

### Other California AI laws in 2026

- **AB 489** — Healthcare Professions: prohibits AI from claiming healthcare licenses; requires patient disclosure
- **SB 243** — Companion Chatbots Act: chatbot disclosures, suicide/self-harm safety, minor protections
- **SB 53** — Transparency in Frontier AI Act: frontier-model developer obligations, effective January 1, 2026

### Future California obligations

- **Jan 1, 2027** — Large online platforms (>2M monthly users) must provide content provenance disclosure under AB 853
- **Jan 1, 2028** — Capture device manufacturers must include latent disclosures

---

## Tab 5: FINRA

### What it is
Securities self-regulatory organization for US broker-dealers. FINRA has not issued AI-specific rules. Existing technology-neutral rules apply when member firms use AI.

### Key guidance documents

- **Regulatory Notice 24-09** (June 27, 2024) — confirms existing FINRA rules apply to AI use; does not create new requirements
- **2026 Annual Regulatory Oversight Report** (December 2025) — flags agentic AI as an emerging supervisory concern
- **FINRA Blog: Observations on AI Agents** (March 6, 2026) — discusses oversight expectations for autonomous AI agents

### Who it affects
All FINRA member firms (broker-dealers).

### What it requires

Existing rules apply, including:
- **Rule 3110 (Supervision)** — supervisory system must address AI use, model risk management, data integrity
- **Rule 2210 (Communications)** — AI-generated communications must meet content standards
- **Rule 4511 (Books and Records)** — AI-related records must be retained

The 2026 oversight report identifies as baseline expectations for firms using AI agents:
- Robust supervision
- Clear limits on agent scope and authority
- Strong logging and audit capabilities
- Human-in-the-loop review for consequential outputs

### Penalties
Existing FINRA disciplinary framework (fines, suspensions, sanctions). Specific amounts depend on violation type and severity.

### Important nuance
Notice 24-09 explicitly states it does not create new legal or regulatory requirements. FINRA enforces existing rules in the AI context.

---

## Tab 6: HIPAA Security Rule

### What it is
Federal regulation under 45 CFR Parts 160, 162, 164. Sets standards for protecting electronic Protected Health Information (ePHI).

### When it hits
**Currently in force.** Major proposed update pending.

- **HIPAA Security Rule** — in force since 2003 (last major update)
- **OCR December 2023 guidance on HIPAA and AI** — in force
- **2026 Security Rule update** — Notice of Proposed Rulemaking published January 6, 2025; final rule expected from HHS approximately May 2026, with ~60 days to effective date and 180-day compliance grace period after publication

### Who it affects
Covered entities (healthcare providers, health plans, healthcare clearinghouses) and business associates handling PHI.

### Penalties
Tiered civil penalties up to approximately $2.1M per violation category per year (adjusted annually for inflation). Criminal penalties available for willful violations.

### What it requires (currently)

**Audit obligations** (45 CFR §164.312(b)):
- Record and examine activity in systems containing or using ePHI
- Information system activity review under §164.308(a)(1)(ii)(D)
- Retain audit logs for at least 6 years

**OCR December 2023 AI guidance:**
- Risk analysis before deploying AI that touches PHI
- Business Associate Agreements for AI vendors handling PHI
- Workforce training on AI-specific risks
- PHI used in AI training is still PHI

### What the 2026 update would add (if finalized as proposed)
- Eliminate the "addressable" vs "required" distinction (everything mandatory)
- Mandatory encryption of ePHI at rest and in transit
- Mandatory multi-factor authentication for systems accessing PHI
- Annual compliance audits with formal testing
- Network segmentation requirements
- Expanded incident response obligations

### Important nuance
There is no "HIPAA-certified AI." HIPAA compliance is operational, not a product attribute.

---

## Tab 7: FDA — AI/ML Medical Devices

### What it is
US regulation of AI-enabled Software as a Medical Device (SaMD) under FDA authority.

### When it hits

| Item | Status |
|---|---|
| FDA QMSR (replaces 21 CFR Part 820, ISO 13485-aligned) | **Effective February 2, 2026** |
| PCCP Final Guidance | Issued December 2024 |
| AI-Enabled Device Software Functions: Lifecycle Management Draft Guidance | Issued January 7, 2025; comment period ended April 7, 2025; finalization expected late 2025 / early 2026 |
| Joint PCCP Guiding Principles (FDA + Health Canada + UK MHRA) | Issued August 2025 |

### Who it affects
Manufacturers of AI-enabled medical devices that meet the FDA's SaMD definition. As of early 2026, FDA has authorized over 1,350 AI-enabled medical devices.

### Penalties
- Warning letters and Form 483 observations
- Product recalls
- Import bans
- Civil money penalties
- Criminal prosecution for willful violations

### What it requires

**Predetermined Change Control Plan (PCCP)** — allows manufacturers to pre-authorize specified AI model modifications without filing a new submission for each change. Three required components:
- Description of Modifications
- Modification Protocol
- Impact Assessment

**Lifecycle Management approach** (Total Product Life Cycle):
- Model description, data lineage, performance tied to claims
- Bias analysis and mitigation
- Human-AI workflow documentation
- Post-market performance monitoring
- PCCP for post-market updates

**QMSR (effective Feb 2, 2026):** ISO 13485-aligned quality management system requirements for all medical device manufacturers, including AI-enabled devices.

---

## Footer

### Quick reference timeline

| Date | What's new |
|---|---|
| Already in force | EU AI Act prohibited practices, EU AI Act GPAI obligations, Texas TRAIGA, California AB 316, California AB 2013, California SB 53, FDA QMSR, FDA PCCP guidance |
| ~May 2026 | HIPAA Security Rule update expected (final) |
| **June 30, 2026** | **Colorado AI Act** |
| **August 2, 2026** | **EU AI Act high-risk obligations**, **California SB 942 (CAITA)** |
| August 2, 2027 | EU AI Act for AI in regulated products |
| January 1, 2027 | California large-platform provenance disclosure (AB 853) |


---

---

BTW, on the main page change the below things

remove mention of FINRA Rule 3110.18
More accurate is "FINRA's existing Rule 3110 supervision applies to AI use; the 2026 Annual Regulatory Oversight Report flags agentic AI as a supervisory concern."

Also wuick things

Summary — prioritized fix list:

Change "court-admissible" → "audit-ready" or "regulator-ready"
Change "tamper-proof" → "tamper-evident"
Drop "FRE 901/902" everywhere. its not accurate
Drop "Verisk" from timeline
Fix "SEC 17a-4 + FINRA Q4 2026" rephrase to "Ongoing · FINRA Notice 24-09 + 2026 oversight report"


FUTURE/MOAT IDEA

Vera's equivalent moat insight: every AI regulation is asking variations of the same three questions above. Build the runtime substrate once — capture every agent decision with cryptographic integrity, enforce policy with full justification trails, prove human oversight where required — then translate that substrate into whatever evidentiary format each regulation demands. EU AI Act conformity package, HIPAA audit log export, FINRA Rule 17a-4 WORM archive, ISO 42001 management evidence, all from the same underlying data.
That's the architecture. Capture once, translate many. The translation layer is where the moat lives because it has to be built regulation by regulation, validated by attorneys, accepted by auditors, and updated continuously as guidance evolves. The substrate is replicable. The translation library is the thing that takes years.