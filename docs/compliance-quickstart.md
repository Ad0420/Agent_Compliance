# Compliance Quickstart

**For: compliance officers, legal counsel, audit leads.**
**Time to read: 10 minutes.**

---

## 1. What this dashboard is

Vera records every decision your AI agents make. The compliance dashboard at
`/compliance` lets you see those decisions, export evidence, and answer
questions from auditors and regulators.

Each record is cryptographically signed and chained to the previous one, so
tampering with a record is detectable — the chain breaks and a downstream
verification flags it. Per-record verification is available on each action's
detail page.

You did not have to build any of this. Your dev team integrated Vera into
your AI agents and the records started flowing. Your job is to read them,
export them when asked, and escalate when something looks wrong.

---

## 2. First five minutes

A literal checklist for your first session:

1. **Sign in.** Use SSO if your org configured it, otherwise sign in with the
   email your IT admin invited. If you can't sign in, ask IT to add you to
   the org and assign you the `compliance_reviewer` role. (Sample email: *"Hi
   IT, please add me to the Vera org with the `compliance_reviewer` role."*)
2. **Go to `/compliance`.** This is the reviewer-focused page. The header
   shows your email, the active org, and a small role badge so you can
   confirm what permissions you have. If the page says **"You don't have
   permission for this view,"** ask your IT admin to grant the
   `compliance_reviewer` role.
3. **Look at the four stat cards** at the top: High-risk decisions, HITL
   approvals taken, Policy violations, and Window. If everything is **0**
   and the tables below say "no records," your dev team has not yet
   deployed Vera into production. Ping them — Vera is only useful once
   it's wired into a live agent.
4. **Open one record** from the Recent records table and click **"Verify
   This Record"** on the Chain Integrity card. You should see "Verified."
   If it says "Verification Failed," **stop and escalate** (see Section 8).

If all four pass, you're ready to use the dashboard.

---

## 3. What's on the compliance dashboard

The `/compliance` page is laid out top-to-bottom as you'll use it. Every
filter is encoded into the URL, so copying the URL is how you share a
saved view with a coworker or auditor.

**Header.** Your email, the active organization, your role badge ("Admin,"
"Compliance reviewer," etc.), and the time range. The range selector (7 /
30 / 90 / 180 days) and the **Copy link** and **Export PDF** buttons live
here.

**Stat cards (four).** Counts for the chosen window:

- **High-risk decisions** — actions tagged tier `high` or `critical`.
  Regulators look here first. Roughly matches EU AI Act Annex III.
- **HITL approvals taken** — high-risk actions where a human approved or
  rejected in the window. EU AI Act Article 14 requires human oversight on
  high-risk AI; this card shows it's actually happening.
- **Policy violations** — guardrail checks that triggered in the window.
  Each has a severity (see Section 5).
- **Window** — the current range. Use the selector to change it.

**Recent records table.** The 20 most recent actions, with sequence
number, timestamp, agent, action, result, data-subject ID, and record
hash. Click a row to open the action detail page.

**Pending HITL approvals.** Actions currently waiting on a reviewer. The
panel links out to the Approvals page where reviewers actually approve or
reject.

**Recent policy violations.** The most recent guardrail violations, with
policy, severity, status (open or resolved), and an "Investigate" link to
the action detail. This panel is the violations view — there is no
separate Violations tab.

**Reviewer audit trail (audit-of-audit).** Collapsed by default. Visible
only to `admin` and `compliance_reviewer` roles. Shows the compliance
team's own activity — every reviewer hit on this dashboard is logged by
backend middleware, so you can demonstrate "yes, we actually review" to a
regulator.

**Footer hint.** A reminder that the current URL captures the time range
and filters. Click **Copy link** to share — the recipient still needs
Clerk access to your organization to open it.

---

## 4. The three workflows you'll do most often

### Workflow A: "A customer asked what we did with their data"

The GDPR Article 15 / HIPAA right-of-access flow. Customer files a Data
Subject Access Request; you have ~30 days to respond.

1. Open the **Actions** page from the dashboard nav.
2. In the filters, paste the customer's identifier into the
   **Data subject ID** filter — their `account_id`, MRN, case number, or
   whatever stable ID your dev team configured. (Ask devs if you're
   unsure which field to use.)
3. The table shows every AI decision involving that subject. Adjust the
   date range as needed; backend export supports filtering on the same
   `data_subject_id`.
4. Click **Export** to download CSV or JSON of the filtered set. The
   export includes the record hashes so the data subject (or their
   counsel) can independently verify the records weren't altered.
5. Attach the export to your response. The CSV is the "machine-readable"
   format most privacy policies promise.

### Workflow B: "A regulator asked for proof of compliance"

The audit-export flow. EU AI Act audit, SOC 2 evidence, HIPAA audit,
state AG inquiry — same process.

1. On `/compliance`, set the date range with the selector (7 / 30 / 90 /
   180 days). For wider ranges, use the Actions page with explicit date
   filters.
2. Review the stat cards and the recent records, pending approvals, and
   violations panels for the window.
3. Click **Export PDF** in the top right of `/compliance`. The PDF
   captures the dashboard for the chosen window: high-risk decisions,
   HITL approvals, policy violations, and record hashes.
4. For deeper evidence, use the Actions page export (CSV/JSON) for the
   raw records — each row includes the record hash and previous hash,
   which is what an auditor needs to independently verify the chain.
5. If an auditor wants to verify the chain themselves, your dev team can
   share the verification output from the authenticated dashboard's
   **Verification** page, or run the per-record verify from the action
   detail. Vera does not ship a public unauthenticated verifier — chain
   verification is gated behind your Clerk org.

### Workflow C: "Our AI did something weird — what happened?"

The incident triage flow. Customer complaint, internal escalation, news
story — you need to find out what the AI actually did.

1. Find the action in the **Recent records** table on `/compliance` or in
   the **Recent policy violations** panel. For older incidents, jump to
   the Actions page and filter by date, agent, or subject.
2. Click into the record (or click **Investigate →** from the violations
   panel) to open the action detail page.
3. The detail view shows:
   - **Identity** — agent name, action name, timestamp, data subject ID
   - **Result** — success, failure, or blocked
   - **Chain Integrity** — sequence number, record hash, previous hash,
     and a **Verify This Record** button
   - **Input Data**, **Outcome**, **Reasoning**, **Metadata** — the full
     JSON payload your agent emitted, including the guardrail's reasoning
     when a check fired
4. If you need more context (underlying tool calls, full LLM trace,
   upstream data), ask the dev team — give them the **record ID** at the
   top of the detail page. They can pull the matching trace from their
   observability tool.

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

When you click "Investigate →" on a violation, you'll see the policy that
fired, the agent's output, and the guardrail's reasoning. If the
violation looks like a false positive (the rule fired but the agent did
the right thing), tell your dev team — they tune the rules.

---

## 6. What to ask your dev team

Bring these questions to your next sync. Most have one-sentence answers;
if a dev hesitates on more than two, that's your finding.

1. **Which AI agents are integrated with Vera?** Get a list with names,
   owners, and what each agent does. (If they say "all of them," ask for
   the inventory.)
2. **What's logged, and what's redacted before logging?** Vera's SDK
   ships a schema-driven `Redactor.medtech()` mode that denies by default
   for PHI fields not in the allowlist (see `sdk/vera/redaction.py`). Ask
   which redaction profile is in use on each agent.
3. **What's our retention policy?** Defaults are configurable per-org;
   ask your dev team for the current value and cross-reference your data
   processing agreement.
4. **If Vera is down, what happens?** Do agent decisions get queued,
   logged locally, dropped? You want "queued and replayed" or "agent
   refuses to act." You don't want "decisions proceed unlogged."
5. **Who has which role?** Vera uses Clerk roles: `admin`, `developer`,
   `compliance_reviewer`. The compliance dashboard is gated behind
   `admin` / `developer` / `compliance_reviewer`; the audit-of-audit
   panel is gated to `admin` / `compliance_reviewer` only. Get the list
   of who holds which role and compare against your access-control
   policy.
6. **Show me a record where Vera blocked an action.** Pick a real one
   from the violations panel. Have them walk through what the agent was
   trying to do and what rule caught it. If they can't, the team isn't
   actually using Vera operationally.
7. **What risk tier are we on?** Pilot, production, or regulated-
   production. See `usevera.xyz/maturity`. The tier should match the
   regulatory exposure of what your agents actually do.
8. **When was the last audit-of-audit?** That is — when did our
   compliance team last review a sample of records to confirm Vera is
   capturing what it should? If never, schedule one. (The reviewer audit
   trail panel on `/compliance` shows the activity that backs this.)
9. **Do we have a BAA / DPA on file with Vera?** Required if any PHI,
   PII, or personal data flows through. If "I don't know," ask
   `hello@usevera.xyz` directly.

---

## 7. Vocabulary you'll see

**Audit record.** A single AI decision. Cryptographically signed,
timestamped, and chained so tampering is detectable.

**Chain.** The verifiable sequence of all records. Each record's hash
includes the previous record's hash, so modifying any record breaks every
record after it. Verification surfaces that break.

**Hash.** A fingerprint of the record content. If anything in the record
changes, the hash changes, and the chain breaks at that point.

**HITL.** Human In The Loop. A required human approval before the AI
agent takes a high-risk action. EU AI Act Article 14 mandates this for
many use cases.

**Guardrail (a.k.a. rule / policy).** A check Vera runs against every AI
decision — "no action without reasoning," "PHI must be redacted in
outputs," "agent X cannot access database Y." Your dev team defines
these.

**Risk tier.** How regulated this category of decision is. High-risk
roughly maps to EU AI Act Annex III: employment, education, essential
services, law enforcement, migration, justice, democratic process.

**Data subject.** The person an AI decision affects — loan applicant,
patient, candidate, customer.

**Chain verification.** Checks that recompute record hashes and confirm
each links correctly to the previous. Surfaced per-record on the action
detail page, and across the chain on the authenticated **Verification**
page in the dashboard.

---

## 8. When to escalate

Most of what you see, you can handle yourself. Escalate when:

- **Records aren't appearing for an agent you know is in production.**
  Ping your dev team. The agent may not be wired in, or the integration
  broke.
- **A rule is firing on every decision.** Almost certainly a
  false-positive — ping your dev team to tune it. Don't ignore it; tuned-
  out alerts go stale.
- **You see a record marked "blocked" but no one told you the AI was
  blocked.** Ping your dev team AND your management. Your incident
  process may not be working.
- **Chain verification fails on a record.** **Stop. Escalate immediately**
  to your dev team's security lead and email `hello@usevera.xyz`. A
  failed verification means either a system bug or tampering. Either way
  it's an incident.

---

## 9. Links

- **Vera compliance dashboard:** `https://app.usevera.xyz/compliance`
- **Risk tier / maturity model:** `https://usevera.xyz/maturity`
- **BAA / DPA requests:** `hello@usevera.xyz`
- **This doc's source:**
  `https://github.com/Ad0420/Agent_Compliance/blob/main/docs/compliance-quickstart.md`

---

*Last updated: 2026-05. Questions or corrections: open a GitHub issue or
email `hello@usevera.xyz`.*
