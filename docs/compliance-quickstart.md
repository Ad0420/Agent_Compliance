# Compliance Quickstart

**For: compliance officers, legal counsel, audit leads.**
**Time to read: 10 minutes.**

---

## 1. What this dashboard is

Vera records every decision your AI agents make. This page lets you see those
decisions, export evidence, and prove compliance to your auditors and
regulators.

Each record is cryptographically signed and chained to the previous one, so
nothing can be deleted or rewritten without breaking the chain. You'll see the
chain verification badge at the top of the page.

You did not have to build any of this. Your dev team integrated Vera into
your AI agents and the records started flowing. Your job is to read them,
export them when asked, and escalate when something looks wrong.

---

## 2. First five minutes

A literal checklist for your first session:

1. **Sign in via SSO.** Your IT admin set this up. If the SSO button gives you
   an error, contact your IT admin — they need to add you to the Vera
   group. (Sample email: *"Hi IT, please add me to the Vera SSO group. My role
   is Compliance reviewer."*)
2. **Confirm your role badge.** Top right of the page. It should say
   "Compliance reviewer" or "Admin." If it says "Viewer," you can read but
   not export — ask your IT admin to upgrade you.
3. **Look at the four stat cards** at the top of the dashboard. If all four
   show **0** and the page says "No records yet," your dev team has not yet
   deployed Vera into production. Ping them — Vera is only useful once it's
   wired into a live agent.
4. **Look at the chain verification badge.** It should say "Chain verified ✓"
   with a recent timestamp. If it says "Chain broken" or "Verification
   failed," **stop and escalate** (see Section 8).

If all four pass, you're ready to use the dashboard.

---

## 3. The four stat cards

Each card counts events in the **last 30 days**. Change the window with the
date picker.

**High-risk decisions.** Actions your AI took that affect a person's outcome
— loan approvals, hiring decisions, medical triage, content moderation
affecting access. Regulators look here first. Under the EU AI Act, these are
the "Annex III" categories.

**HITL approvals.** High-risk actions that required a human to approve
before the AI proceeded. The EU AI Act Article 14 requires human oversight
on high-risk AI; this card shows you it's actually happening. A healthy
ratio is "most high-risk decisions had a HITL." If this number is near zero
while high-risk decisions are non-zero, that's a finding — talk to your dev
team.

**Policy violations.** Times Vera flagged the AI agent doing something
against your org's rules — for example, an action with no reasoning trace,
an agent operating outside its declared scope, or output that failed a
content policy. Each violation has a severity (see Section 5).

**Total records.** Every audit-logged decision in the window. Use this to
spot quiet periods: if your AI agent was busy last week and total records
suddenly drops to zero, something broke in your dev team's deploy. Ping
them.

---

## 4. The three workflows you'll do most often

### Workflow A: "A customer asked what we did with their data"

The GDPR Article 15 / HIPAA right-of-access flow. Customer files a Data
Subject Access Request; you have ~30 days to respond.

1. Click **"Data subject lookup"** in the top nav.
2. Paste the customer's identifier — their `account_id`, MRN, case number,
   or whatever stable ID your dev team configured. (Ask devs if you're
   unsure which field to use.)
3. The dashboard shows every AI decision involving that subject in the
   last 12 months. You'll see the timestamp, the agent name, what the AI
   did, and the outcome.
4. Click **"Export evidence (PDF)"**. The PDF contains every record for
   that subject plus a cryptographic verification page proving the records
   weren't altered.
5. Attach the PDF to your response. If your privacy policy promises
   "machine-readable export," also click the CSV button — same data,
   tabular.

### Workflow B: "A regulator asked for proof of compliance"

The audit-export flow. EU AI Act audit, SOC 2 evidence, HIPAA audit,
state AG inquiry — same process.

1. Set the date range with the picker. (For a SOC 2 audit, typically the
   last quarter. For a regulator inquiry, the specific window they asked
   about.)
2. Filter the Recent table if you want a specific agent or severity.
3. Click **"Export evidence (PDF)"** in the top right.
4. The PDF contains:
   - Hash-chain proof (mathematical evidence that no records were
     deleted or modified)
   - Every high-risk decision in the window
   - Every HITL approval, with the approver's name
   - Every policy violation and how it was resolved
   - AWS KMS signature verification proof
5. Bring the PDF to the audit meeting. Auditors can verify the hash chain
   themselves with `usevera.xyz/verify` — direct them there if they ask.

### Workflow C: "Our AI did something weird — what happened?"

The incident triage flow. Customer complaint, internal escalation, news
story — you need to find out what the AI actually did.

1. Find the action in the **Recent** table or the **Violations** tab.
   Filter by date, by agent name, or by subject.
2. Click into the record.
3. The detail view shows:
   - **Input** — what the agent was asked
   - **Reasoning** — the agent's chain of thought (if your agent emits it)
   - **Output** — what the agent decided
   - **Policy evaluation** — which policies fired, with reasoning
   - **HITL** — who approved (or that no approval was required)
   - **Timing** — when the request came in, how long the agent took
4. If you need more context (the underlying tool calls, the full LLM
   trace, the upstream data), ask the dev team — give them the **record
   ID** at the top of the detail page. They can pull the full trace from
   their observability tool.

---

## 5. How to read a policy violation

Violations have a severity. Use this rough guide:

**Low.** The agent did something slightly off-policy that doesn't affect
the outcome — for example, a missing optional reasoning field. Log it,
trend it, but don't escalate every one.

**Medium.** The agent did something the policy explicitly disallows but
the outcome was caught (e.g., output was redacted, action was deferred to
HITL). Worth a weekly review.

**High.** The agent did something material against policy — operated
outside its declared scope, took a high-risk action with no reasoning
trace, leaked data that policy says should have been redacted. Review
within the week. Ask your dev team to explain how the agent got into that
state.

**Critical.** The agent did something policy was supposed to block and
the blocking failed. Treat as an incident. Convene your dev team and
your management same day.

When you click into a violation, you'll see the policy text that fired,
the agent's output, and the policy engine's reasoning. If the violation
looks like a false positive (the policy fired but the agent did the
right thing), tell your dev team — they tune the policies.

---

## 6. What to ask your dev team

Bring these questions to your next sync. Most have one-sentence answers;
if a dev hesitates on more than two, that's your finding.

1. **Which AI agents are integrated with Vera?** Get a list with names,
   owners, and what each agent does. (If they say "all of them," ask for
   the inventory.)
2. **What's our retention policy?** How long do these records last in
   Vera before they're archived or deleted? Match this against your own
   data retention policy.
3. **If Vera is down, what happens?** Do agent decisions get queued,
   logged locally, dropped? You want "queued and replayed" or "agent
   refuses to act." You don't want "decisions proceed unlogged."
4. **Who has admin access?** Admins can change policies, redact records,
   or rotate signing keys. Get the list. Compare against your access-
   control policy.
5. **Show me a record where Vera blocked an action.** Pick a real one
   from the Violations tab. Have them walk through what the agent was
   trying to do and what policy caught it. If they can't, the team isn't
   actually using Vera operationally.
6. **What risk tier are we on?** Pilot, production, or regulated-
   production. See `usevera.xyz/maturity`. The tier should match the
   regulatory exposure of what your agents actually do.
7. **When was the last audit-of-audit?** That is — when did our
   compliance team last review a sample of records to confirm Vera is
   capturing what it should? If never, we should schedule one.
8. **Do we have a BAA / DPA on file with Vera?** Required if any PHI,
   PII, or personal data flows through. If "I don't know," ask
   `hello@usevera.xyz` directly.

---

## 7. Vocabulary you'll see

**Audit record.** A single AI decision. Cryptographically signed,
timestamped, immutable.

**Chain.** The verifiable sequence of all records. Each record's hash
includes the previous record's hash, so deleting or modifying any record
breaks every record after it. Auditors can prove no records were
removed.

**Hash.** A fingerprint of the record content. If anything in the record
changes, the hash changes, and the chain breaks.

**HITL.** Human In The Loop. A required human approval before the AI
agent takes a high-risk action. EU AI Act Article 14 mandates this for
many use cases.

**Policy.** A rule Vera checks every AI decision against — "no action
without reasoning," "PHI must be redacted in outputs," "agent X cannot
access database Y." Your dev team defines these.

**Risk tier.** How regulated this category of decision is. High-risk
roughly maps to EU AI Act Annex III: employment, education, essential
services, law enforcement, migration, justice, democratic process.

**Data subject.** The person an AI decision affects — loan applicant,
patient, candidate, customer.

**Hash-chain verification.** A mathematical check that proves no records
were deleted or modified. Run it yourself any time at
`usevera.xyz/verify`.

---

## 8. When to escalate

Most of what you see, you can handle yourself. Escalate when:

- **Records aren't appearing for an agent you know is in production.**
  Ping your dev team. The agent may not be wired in, or the integration
  broke.
- **A policy is firing on every decision.** Almost certainly a
  false-positive — ping your dev team to tune it. Don't ignore it; tuned-
  out alerts go stale.
- **You see a record marked "blocked" but no one told you the AI was
  blocked.** Ping your dev team AND your management. Your incident
  process may not be working.
- **Hash-chain verification fails.** **Stop. Escalate immediately** to
  your dev team's security lead and email `hello@usevera.xyz`. A broken
  chain means either a system bug or tampering. Either way it's an
  incident.

---

## 9. Links

- **Vera dashboard:** `https://app.usevera.xyz/compliance`
- **Verify a hash chain (for auditors):** `https://usevera.xyz/verify`
- **Risk tier / maturity model:** `https://usevera.xyz/maturity`
- **BAA / DPA requests:** `hello@usevera.xyz`
- **This doc's source:**
  `https://github.com/Ad0420/Agent_Compliance/blob/main/docs/compliance-quickstart.md`

---

*Last updated: 2026-05. Questions or corrections: open a GitHub issue or
email `hello@usevera.xyz`.*
