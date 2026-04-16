# Vera — Product Guide & Beta Onboarding
*For co-founders, beta testers, and internal reference.*

---

# Part 1 — What Vera Is (Read This First)

## The core problem

Companies are building AI agents that make real decisions — approving loans,
flagging fraud, screening job applicants, triaging medical cases. When something
goes wrong, they have no reliable record of:

- What the AI actually did
- Why it made that decision
- Whether the logs were tampered with afterwards
- Which users were affected

Regulators are now requiring this. The EU AI Act (enforced August 2026) legally
mandates that companies deploying AI in high-risk contexts must maintain
continuous audit logs, monitor for failures, and be able to prove all of this
to an authority. The fine for non-compliance is up to 7% of global annual revenue.

Most companies building AI agents today have none of this infrastructure.

## What Vera does

Vera is a compliance logging service for AI agents.

You add one API call to your agent code. Every time the agent does something,
it sends a record to Vera. Vera stores it in a tamper-proof chain and gives you
a dashboard to search, monitor, and audit everything your agent has ever done.

Think of it like Stripe for AI compliance — you add a few lines of code and
the entire compliance infrastructure is handled.

## Why the tamper-proof chain matters

A normal database can be edited silently. Someone could go into the database
and change a record — "the AI approved this loan" becomes "the AI rejected this
loan" — and nobody would know.

Vera uses a hash chain (similar in principle to a blockchain but simpler and
faster). Every record is cryptographically linked to the one before it. If
anyone — including us — edits a record, every record after it breaks. The
customer's dashboard immediately shows "Chain Broken." You cannot silently
modify the audit trail. This is what makes Vera's logs valid as legal evidence,
not just a dashboard for developers.

## The six features

### 1. Actions — the audit trail
Every single thing your AI agent does, stored permanently with a cryptographic
proof of integrity. Searchable by agent, date, result, or the specific person
the decision was about.

### 2. Chain Verification
A live check showing whether the audit log has been tampered with. Green dot
= intact. If it ever turns red, the exact record that was modified is
identifiable. The customer can verify this themselves at any time.

### 3. Agents
A registry of every AI agent that has sent actions to Vera. Lets you track
multiple agents separately, see when they were first seen, and detect agents
that shouldn't be running.

### 4. Policies — automated monitoring
Rules you define once that Vera checks against every incoming action in real
time. Examples: "alert me if failure rate exceeds 30% over 50 actions",
"flag if the agent acts on a person without providing reasoning", "email me
if 10 failures happen within 60 seconds." When a rule triggers, Vera creates
a violation record and optionally sends an email immediately.

### 5. Violations
A log of every policy breach. Each violation links to the exact action that
caused it. The developer can review it, write a resolution note, and mark it
resolved. This resolution trail is itself compliance evidence — it proves you
didn't just detect a problem, you responded to it.

### 6. Compliance
A summary of which regulations apply and how your current Vera data maps to
each legal requirement. Gives you something concrete to show a lawyer,
investor, or regulator.

## The long-term vision

Vera starts as a compliance tool. The deeper asset is the dataset it generates.

Every company using Vera contributes (anonymised) failure pattern data — what
types of AI agents fail, in what contexts, at what rates, in which industries.
No one else in the world is collecting this data at the infrastructure level.

That dataset is the underwriting data for AI liability insurance. AI liability
insurance is a nascent but fast-growing market — insurers need to price the
risk of AI decisions causing harm (a bad loan, a missed fraud case, a wrong
medical triage). Right now they are guessing because they have no data.

Vera becomes the company that knows more about how AI agents fail in production
than anyone on earth. That is the long-term moat.

---

# Part 2 — Q&A for Co-Founders

These are the questions anyone new to Vera will ask. Read these before any
meeting, investor call, or customer conversation.

---

**Q: What exactly does a developer have to do to use Vera?**

Register at usevera.xyz, copy their API key, and add this to their agent code:

```python
import requests

requests.post(
    "https://agentcompliance-production.up.railway.app/v1/actions",
    headers={"Authorization": "Bearer THEIR_API_KEY"},
    json={
        "agent_name": "my-agent",
        "action_type": "decision",
        "action_name": "approve_loan",
        "result": "success",
    }
)
```

That is the entire integration. One HTTP call. Takes about 10 minutes to add
to an existing agent. Everything else — storage, hashing, chain verification,
policy evaluation, violation recording, email alerts — happens automatically.

---

**Q: Does Vera automatically detect if the AI made a wrong decision?**

No. Vera records what the developer tells it. The developer decides what
"success" and "failure" mean for their use case and sets the result field
accordingly.

For example, if a loan approval agent has a confidence threshold, the developer
writes: if confidence > 0.8, log success. If below, log failure. Vera records
that, detects patterns in those outcomes over time, and alerts when something
looks wrong. Vera is the record-keeper and pattern detector — the developer
defines what counts as a problem.

This is intentional. Vera works across all types of AI agents regardless of
what they do. It does not need to understand the domain. It just needs to know
what happened.

---

**Q: What does "failure" actually mean? AI is probabilistic — how can
something be definitively a success or failure?**

In practice, "failure" almost never means "the AI gave a wrong answer." It
means the developer's business logic determined something went wrong. Examples:

- The agent threw an exception (API timeout, unparseable response)
- The model's confidence score was below the acceptable threshold
- A business rule was violated (loan amount exceeds maximum)
- A downstream system rejected the action (Stripe returned an error)
- A human reviewer overrode the AI's decision

The developer wraps their agent call in a try/except. If it succeeds by their
definition, they log "success." If not, they log "failure." Vera watches the
rate of those failures and alerts when patterns emerge.

---

**Q: Does Vera stop an AI agent from doing something dangerous?**

Not currently. Vera is currently reactive — it records what happened and alerts
on patterns. It does not intercept or block agent actions.

The next major feature is a checkpoint system: the agent can call Vera before
taking a risky action and wait for a human to approve or reject it in the
dashboard. Until that is built, Vera monitors and alerts but does not control.

---

**Q: How is one company's data separated from another's?**

Every organisation has a unique ID. Every single database query filters by that
ID at the infrastructure level — not just the application code. There is no
query in the codebase that returns data across multiple organisations. Org A
cannot access Org B's data.

---

**Q: Can Vera (the company) see a customer's data?**

Yes, in the sense that we have database access. But we cannot silently modify
it — the hash chain would immediately show "Chain Broken" on the customer's
dashboard. We have access but not undetectable access.

In practice we do not look at customer data. And structurally, the
cryptography means any modification we made would be visible to the customer.

---

**Q: Is this GDPR compliant?**

The architecture is designed for GDPR compliance:

- Personal data (action records containing user IDs) is isolated per org
- Customers control their own data
- We do not use personal data for any purpose other than serving it back
- The `data_subject_id` field enables GDPR Article 15 (right of access) — a
  company can search all AI decisions made about a specific person in seconds

We do not yet have a formal Data Processing Agreement (DPA) template or a
published Privacy Policy. These need to be in place before any EU enterprise
customer. Estimated cost: £500-800 with a startup lawyer. On the near-term
roadmap.

---

**Q: What regulations does Vera help with?**

| Regulation | Requirement Vera helps satisfy |
|---|---|
| EU AI Act Art. 9 | Continuous risk management system — policies are the rules, violations are the documentation |
| EU AI Act Art. 26 | Deployers must monitor AI operation and detect anomalies — Vera does this in real time |
| EU AI Act Art. 86 | Right to explanation — `reasoning` field logs why the AI made each decision |
| GDPR Art. 15 | Right of access — search all decisions about a specific person instantly |
| NIST AI RMF | Measure + Manage functions — monitoring, incident tracking, response documentation |
| Colorado AI Act | Similar to EU AI Act for US — disclosure and impact assessment requirements |

---

**Q: Who are the target customers?**

Any company deploying AI agents that make decisions affecting real people in
high-stakes contexts. The highest-value segments:

- **Fintech** — loan approval, fraud detection, credit scoring
- **Healthcare** — triage, diagnosis assistance, prior authorisation
- **Legal** — document review, contract analysis, risk assessment
- **HR** — resume screening, candidate assessment
- **Insurance** — claims processing, underwriting

These sectors have the highest regulatory exposure and the most to lose from
an AI incident. They are also the sectors where the failure pattern data is
most valuable for the long-term insurance underwriting play.

---

**Q: What is the insurance angle?**

AI liability insurance is becoming a real product — insurers covering companies
against financial losses caused by AI decisions (a wrongful loan denial, a
missed fraud case, a bad medical recommendation). The market is projected to
exceed $30 billion by 2030.

To price that insurance, insurers need data on how AI agents fail — what types,
in what contexts, at what rates. That data does not exist anywhere today.

Vera, at scale, generates exactly that dataset. Every company logging to Vera
contributes anonymised failure patterns. Vera becomes the entity that
understands AI risk better than any insurer, because it sits at the
infrastructure layer across thousands of deployments.

The path: compliance tool → failure pattern dataset → AI risk scores →
insurance underwriting data. This is structurally identical to how Coalition
built a $5 billion cyber insurance company — starting as a security tool,
becoming the best source of cyber risk data, then underwriting the insurance
themselves.

---

**Q: What is not built yet?**

| Feature | Status |
|---|---|
| Human-in-the-loop checkpoints | Not built — next major feature |
| Python/Node SDK (pip install vera) | Not built — currently raw HTTP |
| SOC 2 certification | Not yet — needed for enterprise |
| Data Processing Agreement | Not yet — needed for EU enterprise |
| EU data residency | Not yet — needed for some EU customers |
| Anonymised aggregate analytics | Not yet — needed for insurance play |

---

**Q: Is the product ready for beta users?**

Yes for developers building AI agents who want an audit trail now. The core
infrastructure — chain, policies, violations, email alerts — is built and
deployed. The gaps above are real but none of them block a developer from
integrating and getting value today.

Not ready for a regulated enterprise with SOC 2 requirements or a formal
legal procurement process. That comes with time and paying customers.

---

# Part 3 — Beta Integration Guide

## Step 1 — Register

Go to: **https://www.usevera.xyz/register**

Enter your organisation name. You will immediately receive an API key.
Copy it — this is your only credential.

## Step 2 — Send your first action

```python
import requests

requests.post(
    "https://agentcompliance-production.up.railway.app/v1/actions",
    headers={"Authorization": "Bearer YOUR_API_KEY"},
    json={
        "agent_name": "my-agent",
        "action_type": "decision",
        "action_name": "approve_loan",
        "result": "success",
    }
)
```

Refresh your dashboard at usevera.xyz/dashboard. You will see the action.

## Step 3 — Add it properly to your agent

```python
import requests
import threading

VERA_URL = "https://agentcompliance-production.up.railway.app/v1/actions"
VERA_KEY = "YOUR_API_KEY"

def log_to_vera(action_name, result, **kwargs):
    """Fire-and-forget — never blocks your agent."""
    def _send():
        try:
            requests.post(
                VERA_URL,
                headers={"Authorization": f"Bearer {VERA_KEY}"},
                json={
                    "agent_name": "your-agent-name",
                    "action_type": "decision",
                    "action_name": action_name,
                    "result": result,
                    **kwargs
                },
                timeout=5
            )
        except Exception:
            pass  # Vera logging must never crash your agent

    threading.Thread(target=_send, daemon=True).start()


# Then in your agent:
def approve_loan(applicant_id, amount):
    try:
        decision = ai_model.evaluate(applicant_id, amount)

        log_to_vera(
            action_name="approve_loan",
            result="success",
            data_subject_id=applicant_id,        # person this affects
            reasoning={"score": decision.score},  # why the AI decided this
            outcome={"approved": decision.approved, "amount": amount},
            authorized_by="policy-engine-v1",
        )
        return decision

    except Exception as e:
        log_to_vera(
            action_name="approve_loan",
            result="failure",
            data_subject_id=applicant_id,
            error_message=str(e),
        )
        raise
```

## API field reference

### Required fields

| Field | What to put |
|---|---|
| `agent_name` | Stable name for your agent e.g. `"loan-screener-v2"` |
| `action_type` | `decision` `llm_call` `function_call` `api_call` `tool_use` |
| `action_name` | Specific action e.g. `"approve_loan"` `"generate_email"` |
| `result` | `"success"` `"failure"` `"partial"` `"pending"` |

### Recommended fields (these are what make Vera valuable for compliance)

| Field | What to put |
|---|---|
| `reasoning` | JSON dict of why the AI made this decision |
| `data_subject_id` | ID of the person this decision affects — enables GDPR lookup |
| `authorized_by` | What approved this action e.g. `"human-review"` `"policy-engine"` |
| `error_message` | Error details if result is `"failure"` |

### Optional extras

| Field | What to put |
|---|---|
| `agent_version` | `"1.0.3"` |
| `model_id` | `"gpt-4o"` `"claude-3-5-sonnet"` |
| `input_data` | What went into the agent |
| `outcome` | What came out |
| `duration_ms` | How long it took in milliseconds |

## Step 4 — Set up policies

Go to usevera.xyz/policies and create these to start:

| Policy | Recommended settings |
|---|---|
| Failure rate | Alert if >30% of last 50 actions fail |
| Consecutive failures | Alert if same agent fails 5 times in a row |
| Missing reasoning | Alert if action has data_subject_id but no reasoning |
| Unknown agent | Alert if an unregistered agent sends an action |

Set action to "Flag + Email" and add your email in Settings → Alert Email.

## What to send us as feedback

1. How long did integration take? Where did you get stuck?
2. Are the fields flexible enough for your agent?
3. Is the dashboard showing you what you need?
4. What policies do you wish existed?
5. Would you pay for this? What would make it a must-have?
