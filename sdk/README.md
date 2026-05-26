# vera-sdk

Python SDK for **Vera**, a runtime trust layer for AI agents. Vera gives every
agent action an immutable, cryptographically verifiable audit trail; supports
human-in-the-loop (HITL) approvals for high-risk actions; and captures policy
violations so they're queryable after the fact. Built for teams shipping AI
into regulated contexts (EU AI Act, GDPR, NIST AI RMF, HIPAA).

If your agent makes decisions a regulator, auditor, or DPO might one day need
to inspect, Vera turns "what did the model do?" from an after-the-fact
forensics project into a single SQL query.

## Contents

- [5-minute quickstart](#5-minute-quickstart)
- [Concepts](#concepts)
- [Framework cookbooks](#framework-cookbooks)
  - [OpenAI](#openai)
  - [Anthropic](#anthropic)
  - [LangChain](#langchain)
  - [CrewAI](#crewai)
- [HIPAA and medtech](#hipaa-and-medtech)
- [Environment variables](#environment-variables)
- [Command-line interface](#command-line-interface)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)
- [HTTP API reference](#http-api-reference)
- [Versioning policy](#versioning-policy)
- [Links](#links)

## 5-minute quickstart

The fastest path from `pip install` to a record visible in the dashboard.

### 1. Sign up and create an API key

Visit <https://usevera.xyz/register>, create an org, and copy the API key from
the **API Keys** tab in the dashboard. Keys are prefixed `al_live_` for prod
and `al_test_` for sandbox.

### 2. Install

```bash
pip install vera-sdk
```

Add framework extras if you want auto-audit integrations (see
[Framework cookbooks](#framework-cookbooks)):

```bash
pip install "vera-sdk[openai,anthropic,langchain,crewai]"
```

### 3. Initialize and audit your first action

```python
import vera

vera.init(api_key="al_live_...", agent_name="loan-screener")

@vera.audit(action_name="approve_loan")
def approve_loan(applicant_id: str, amount: int) -> dict:
    return {"approved": True, "score": 0.93}

approve_loan("user_42", 25_000)
```

That's it. The decorator captures inputs, outcome, timing, and any exception
traceback, then ships the record to Vera in the background.

### 4. Verify from the command line

```bash
vera ping
# Connecting to https://api.usevera.xyz...
# OK Authenticated to https://api.usevera.xyz in 142.0ms
#   status: ok
#   chain_length: 1

vera tail --limit 5
# [    42] 2026-05-13T07:00:00Z  loan-screener  approve_loan  success
```

### 5. See it in the dashboard

Open <https://app.usevera.xyz/actions>. Your record appears within a few
seconds of the call returning. Click into it for the redacted input, outcome,
duration, and the signed hash that anchors it to the audit chain.

If you want to try the SDK before signing up, set `VERA_DEV=1` and skip the
API key entirely. See [Dev mode](#dev-mode).

## Concepts

A short tour of the abstractions you will actually touch.

### `vera.init()`

One-call setup. Reads explicit kwargs first, falls back to `VERA_*` env vars,
falls back to defaults. Returns the client and registers it as the default
for every `@audit` decorator in the process.

```python
vera.init(
    api_key="al_live_...",
    agent_name="loan-screener",
    agent_version="2026.05.13",
    framework="openai",
    model_id="gpt-4o",
)
```

Calling `init()` twice replaces the previous default and closes the old
client. For async codepaths use `vera.init_async(...)` (synchronous entry
point — drops in-flight records on re-init) at startup, or
`vera.init_async_awaitable(...)` (async; awaits the previous client's drain
on re-init) inside long-running uvicorn workers where mid-process re-init is
possible and losing queued records is unacceptable.

### `@vera.audit` decorator

Drop-in wrapper for any function. Captures args, kwargs, return value,
duration, and exceptions. Failures inside Vera (network, auth, redactor) never
mask your function's own exceptions and never add blocking latency to customer
code: every record goes through the async background queue.

```python
@vera.audit(action_name="approve_loan", action_type="decision")
def approve_loan(applicant_id: str, amount: int) -> dict:
    ...
```

For async functions, use `@vera.async_audit(...)` and `vera.init_async(...)`.

### `Redactor`

Scrubs PII and secrets out of inputs and outputs before they hit the audit
DB. Three layers compose, in order of precedence:

1. **`block_keys`**: case-insensitive kwarg names that are always replaced
   wholesale. Defaults cover `password`, `api_key`, `ssn`, `credit_card`, and
   similar.
2. **`Schema`** (optional, recommended for regulated data): per-field policy
   `PASSTHROUGH`, `REDACT`, or `PATTERN` with a named regex. Unmapped fields
   fall through to `unmapped_policy` (deny-by-default).
3. **Regex pass**: runs every named pattern over string leaves. Defaults
   cover SSN, Luhn-checked credit cards, emails, phones, AWS access keys,
   bearer tokens, JWTs.

Schema mode is what makes Vera safe for regulated workloads. See
[HIPAA and medtech](#hipaa-and-medtech) for the medtech variant.

### Dev mode

Run without an API key. Records print to stderr as `[vera-dev] {...}`.

```bash
export VERA_DEV=1
python my_agent.py
```

Or programmatically:

```python
vera.init(dev=True, agent_name="my-agent")
```

Useful for tutorials, local iteration, and CI smoke tests where you don't
want to provision a real key.

### Durable spool

Encrypted, on-disk SQLite buffer that catches records when the in-memory
queue is full or the network is down. Survives crashes and process restarts.

```python
import os
os.environ["VERA_SPOOL_PATH"] = "/var/vera/spool.db"
os.environ["VERA_SPOOL_KEY"] = os.environ["VAULT_VERA_SPOOL_KEY"]

vera.init(api_key="al_live_...", agent_name="my-agent")
```

The spool file is created with mode `0600`. Payloads are encrypted at rest
with AES-256-GCM; the key is derived from `VERA_SPOOL_KEY` via PBKDF2-HMAC-SHA256
(200,000 iterations). If `VERA_SPOOL_KEY` is unset, the spool refuses to
start: a deliberate guard against accidentally writing plaintext PHI to disk.
See [`docs/spool-key-rotation.md`](./docs/spool-key-rotation.md) for the
rotation flow.

Install the optional extra to enable: `pip install "vera-sdk[spool]"`.

### Branded errors

Every transport, auth, validation, and rate-limit failure raises a typed
subclass of `vera.VeraError` so customer code can match on the specific case
instead of parsing exception messages.

```python
from vera import VeraAuthError, VeraRateLimitError, VeraTimeoutError

try:
    client.record_action(...)
except VeraAuthError:
    # Bad API key, expired key, or revoked.
    ...
except VeraRateLimitError:
    # Backoff and retry.
    ...
except VeraTimeoutError:
    # Network slow, or API key fine but server slow.
    ...
```

Full hierarchy: `VeraError` is the base; subclasses are `VeraAuthError`,
`VeraRateLimitError`, `VeraServerError`, `VeraTimeoutError`,
`VeraNetworkError`, and `VeraValidationError`.

## Framework cookbooks

Copy-paste-runnable patterns for the four most common agent frameworks. Each
cookbook has a minimal version (just the integration) and a realistic version
(integration plus redaction plus durable spool).

### OpenAI

Auto-audits every `chat.completions.create` call: prompts, response, model,
token usage, duration.

**Minimal:**

```python
import openai
import vera
from vera.integrations.openai import AuditedOpenAI

vera.init(api_key="al_live_...", agent_name="support-bot")

client = AuditedOpenAI(openai.OpenAI(), ledger_client=vera.get_client())

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a customer support agent."},
        {"role": "user", "content": "When does my order arrive?"},
    ],
)
print(response.choices[0].message.content)
```

**Realistic** (PHI redaction, durable spool, custom block keys):

```python
import os
import openai
import vera
from vera.integrations.openai import AuditedOpenAI
from vera.redaction import Redactor

# Spool config: encrypted on-disk buffer for outages.
os.environ.setdefault("VERA_SPOOL_PATH", "/var/lib/vera/spool.db")
# VERA_SPOOL_KEY must be set in the environment from your secret manager.

# Build the redactor once. AuditedOpenAI does NOT inherit the redactor
# passed to vera.init() — it must be passed explicitly to the wrapper.
redactor = Redactor.medtech(
    extra_block_keys={"insurance_member_id"},
)

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="medical-scribe",
    framework="openai",
    model_id="gpt-4o",
    redactor=redactor,
)

client = AuditedOpenAI(
    openai.OpenAI(),
    ledger_client=vera.get_client(),
    redactor=redactor,
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Summarise this clinical note."},
        {"role": "user", "content": "Patient John Doe, MRN-12345678..."},
    ],
)
```

**What the audit record looks like:**

```json
{
  "id": 4271,
  "action_name": "openai.chat.completions.create",
  "action_type": "llm_call",
  "agent_name": "medical-scribe",
  "model_id": "gpt-4o",
  "result": "success",
  "duration_ms": 1842,
  "input_data": {
    "messages": [
      {"role": "system", "content": "Summarise this clinical note."},
      {"role": "user", "content": "Patient [REDACTED], [REDACTED]..."}
    ]
  },
  "outcome": {
    "response": "Patient presents with...",
    "usage": {"prompt_tokens": 142, "completion_tokens": 218}
  },
  "created_at": "2026-05-13T07:00:00Z"
}
```

Streaming is supported out of the box. The wrapper forwards every chunk to
your caller as it arrives, accumulates content in a 1MB-capped buffer, and
emits one audit record on stream close.

```python
with client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "..."}],
    stream=True,
) as stream:
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="")
```

### Anthropic

Wraps `anthropic.Anthropic.messages.create` and `.messages.stream`. Same
audit shape as the OpenAI integration.

**Minimal:**

```python
import anthropic
import vera
from vera.integrations.anthropic import AuditedAnthropic

vera.init(api_key="al_live_...", agent_name="research-assistant")

client = AuditedAnthropic(anthropic.Anthropic(), ledger_client=vera.get_client())

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Summarise the attached policy document."},
    ],
)
print(response.content[0].text)
```

**Realistic** (PHI redaction, spool, explicit redactor):

```python
import os
import anthropic
import vera
from vera.integrations.anthropic import AuditedAnthropic
from vera.redaction import Redactor

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="clinical-summariser",
    framework="anthropic",
    model_id="claude-sonnet-4-6",
    persistent_buffer_path="/var/lib/vera/spool.db",
)

redactor = Redactor.medtech()
client = AuditedAnthropic(
    anthropic.Anthropic(),
    ledger_client=vera.get_client(),
    redactor=redactor,
)

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[
        {"role": "user", "content": "Generate a discharge summary for MRN-72839102..."},
    ],
)
```

Both `messages.create(stream=True)` and `messages.stream(...)` paths are
audited as a single record on stream close.

### LangChain

Drop the callback handler into any LangChain runnable. Every LLM call, chain
step, tool call, and agent action becomes its own audit record, linked by
`run_id` so you can reconstruct the full trace in the dashboard.

**Minimal:**

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import vera
from vera.integrations.langchain import VeraCallbackHandler

vera.init(api_key="al_live_...", agent_name="rag-pipeline")
handler = VeraCallbackHandler(client=vera.get_client())

llm = ChatOpenAI(model="gpt-4o")
prompt = ChatPromptTemplate.from_template("Answer concisely: {question}")
chain = prompt | llm

result = chain.invoke(
    {"question": "What is the GDPR right to erasure?"},
    config={"callbacks": [handler]},
)
print(result.content)
```

**Realistic** (agent with tools, PHI redactor, attached at the agent level so
every nested call inherits it). The agent constructor (`create_tool_calling_agent`)
requires `langchain>=0.1.17`; the SDK extras only install
`langchain-core`. Install both:

```bash
pip install "vera-sdk[langchain]" "langchain>=0.1.17"
```

```python
import os
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

import vera
from vera.integrations.langchain import VeraCallbackHandler
from vera.redaction import Redactor

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="patient-intake",
    framework="langchain",
)

@tool
def lookup_patient(patient_id: str) -> dict:
    """Fetch a patient record from the EHR."""
    return {"patient_id": patient_id, "status": "active"}

handler = VeraCallbackHandler(
    client=vera.get_client(),
    redactor=Redactor.medtech(),
)

llm = ChatOpenAI(model="gpt-4o")
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a clinical intake agent."),
    ("user", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
agent = create_tool_calling_agent(llm, [lookup_patient], prompt)
executor = AgentExecutor(agent=agent, tools=[lookup_patient])

executor.invoke(
    {"input": "Look up patient_id pat_abc123 and summarise."},
    config={"callbacks": [handler]},
)
```

**What gets recorded:** one record per LLM call (`action_type="llm_call"`),
one per chain (`action_type="chain"`), one per tool invocation
(`action_type="tool_call"`), one per agent action. Each carries the same
`run_id` so the dashboard can render the trace as a tree.

### CrewAI

Patches `crewai.tools.BaseTool._run` so every tool call by every agent is
audited automatically. No code changes inside your crew definition.

**Minimal:**

```python
from crewai import Agent, Crew, Task
from crewai.tools import BaseTool

import vera
from vera.integrations.crewai import enable_crewai_auditing

vera.init(api_key="al_live_...", agent_name="research-crew")
enable_crewai_auditing(client=vera.get_client())

class SearchTool(BaseTool):
    name: str = "search"
    description: str = "Search the web for a query."

    def _run(self, query: str) -> str:
        return f"Top result for '{query}'"

researcher = Agent(
    role="Researcher",
    goal="Find authoritative sources",
    backstory="...",
    tools=[SearchTool()],
)
task = Task(description="Research the EU AI Act", agent=researcher)
Crew(agents=[researcher], tasks=[task]).kickoff()
```

**Realistic** (multi-agent crew with PHI redaction):

```python
import os
from crewai import Agent, Crew, Task
from crewai.tools import BaseTool

import vera
from vera.integrations.crewai import enable_crewai_auditing
from vera.redaction import Redactor

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="medical-research-crew",
    framework="crewai",
    persistent_buffer_path="/var/lib/vera/spool.db",
)
enable_crewai_auditing(
    client=vera.get_client(),
    redactor=Redactor.medtech(),
)

# ... rest of your crew, unmodified
```

Disable with `from vera.integrations.crewai import disable_crewai_auditing;
disable_crewai_auditing()`. Useful for tests.

## HIPAA and medtech

> ⚠️ **Using `Redactor.medtech()` is one piece of HIPAA-grade handling. It
> does not make your deployment HIPAA-compliant on its own.** You still need
> a signed BAA with Vera and your other vendors, encryption at rest, access
> controls, audit-log integrity monitoring, and BCP/DR — none of which are
> SDK concerns.

Vera ships first-class support for HIPAA-aware workloads. The path:

1. Sign a Business Associate Agreement (BAA) with Vera. Required before
   sending any PHI through the SDK. <https://usevera.xyz/baa>
2. Configure the medtech redactor and durable spool (next section).
3. Review your function signatures against the 18 PHI Safe Harbor
   identifiers and the starter schema.

### The medtech redactor

`Redactor.medtech()` returns a Redactor preconfigured for HIPAA Safe Harbor:

- **Starter schema** with deny-by-default for unmapped fields. Covers
  `patient_name`, `dob`, `mrn`, `ssn`, address fields, phone, email,
  free-text fields (`notes`, `description`, `summary`, `transcript`, and
  related), and common FHIR Bundle/Resource container keys.
- **Medtech regex pass**: MRN (`MRN-12345678`), DOB (multiple formats),
  IPv4/IPv6, plus URL-with-PHI replacement, on top of the standard SSN,
  Luhn-checked CC, email, phone, AWS key, JWT, bearer-token patterns.
- **Extra block_keys** covering Safe Harbor categories where a flat-key
  lookup is sufficient (names, address parts, phone, email, insurance IDs,
  biometric identifiers, photo URLs, and related).
- **BAA reminder log** on first use (one INFO log per process, ID
  `vera-baa-001`).

```python
from vera.redaction import Redactor

redactor = Redactor.medtech()
vera.init(api_key="al_live_...", agent_name="my-agent", redactor=redactor)
```

### The 18 PHI Safe Harbor identifiers

| Category | Default coverage |
|---|---|
| Names | block_keys: `patient_name`, `first_name`, `last_name`, `full_name`; schema REDACT |
| Geographic subdivisions | block_keys: `address`, `street`, `city`, `state`, `zip`, `postal_code`; schema REDACT |
| Dates (DOB, admission, discharge, death) | regex: `dob` pattern (MM/DD/YYYY, ISO, DD-Mon-YYYY); schema PATTERN on `dob` and `date_of_birth` |
| Phone numbers | regex: `phone` pattern; block_keys: `phone`, `phone_number`, `mobile`, `cell` |
| Fax numbers | block_keys: `fax`, `fax_number` |
| Email addresses | regex: `email` pattern; block_keys: `email`, `email_address` |
| Social Security numbers | regex: `ssn` pattern; block_keys: `ssn`, `social_security` |
| Medical record numbers | regex: `mrn` pattern; block_keys: `mrn`, `medical_record_number`; schema PATTERN |
| Health plan beneficiary numbers | block_keys: `insurance_id`, `policy_number`, `member_id`, `subscriber_id` |
| Account numbers | customer declares via schema |
| Certificate or license numbers | customer declares via schema |
| Vehicle identifiers (VIN, plate) | customer declares via schema |
| Device identifiers and serial numbers | block_keys: `device_id`, `serial` |
| Web URLs containing PHI | regex: `url_phi` pattern (URLs with embedded MRN, SSN, DOB, or `patient_id=`) |
| IP addresses | regex: `ipv4`, `ipv6`; block_keys: `ip`, `ip_address` |
| Biometric identifiers | block_keys: `biometric`, `fingerprint`, `face_photo` |
| Full-face photographs | block_keys: `photo`, `image_url`, `face_photo` |
| Other unique identifiers | covered by deny-by-default schema for unmapped fields |

"Customer declares" means: pass `extra_block_keys={"account_number"}` to
`Redactor.medtech()` or add the field to a custom schema. The deny-by-default
unmapped policy means unknown fields are redacted wholesale anyway; declaring
them is for clarity, not safety.

### Opaque patient IDs vs MRN-shaped IDs

**Use opaque, randomly-generated `patient_id` values (e.g. `pat_a8f3b2c1`).**
Opaque IDs are HIPAA-safe and the starter schema marks `patient_id` as
`PASSTHROUGH` so audit records stay searchable.

If your `patient_id` is an MRN or otherwise contains real PHI, force
redaction:

```python
redactor = Redactor.medtech(extra_block_keys={"patient_id"})
```

Same pattern for any field your domain models as ID-shaped but populates
with real-world identifiers.

### Free-text PHI

> ⚠️ **Use opaque, randomly-generated identifiers for patients, encounters,
> and clinicians.** Free-text fields (notes, descriptions, prose) cannot be
> reliably scrubbed by regex — names, dates, and identifiers slip through any
> pattern pass. Declare every prose field that may contain PHI in your
> `Redactor` schema, or omit it from audit payloads entirely.

The starter schema redacts `notes`, `description`, `summary`, `comment`,
`comments`, `message`, `transcript`, `audio_transcript`, `email_body`,
`body`, and `text` wholesale.

If you have a free-text field with PHI that uses a non-default name, declare
it explicitly. Note that `Schema` builds its case-insensitive lookup table at
construction time, so mutating `schema.fields` AFTER construction does not
take effect. Build the merged schema up front and pass it to
`Redactor.medtech(schema=...)`:

```python
from vera.redaction import Redactor, Schema, FieldRule, FieldPolicy

base = Redactor.medtech_starter_schema()
schema = Schema(
    fields={
        **base.fields,
        "physician_notes": FieldRule(
            FieldPolicy.REDACT,
            description="Free-text physician notes.",
        ),
    },
    unmapped_policy=base.unmapped_policy,
)
redactor = Redactor.medtech(schema=schema)
```

### Custom block keys and patterns

```python
import re
from vera.redaction import Redactor

redactor = Redactor.medtech(
    extra_block_keys={"member_id", "external_account_ref"},
    extra_patterns=[
        ("internal_case_id", re.compile(r"\bCASE-\d{6}\b")),
    ],
)
```

`extra_patterns` are added to the default regex pass and can be referenced
by name from schema `PATTERN` rules.

### Durable spool with encryption at rest

Required for HIPAA. Never write plaintext PHI to disk.

```bash
export VERA_SPOOL_PATH=/var/lib/vera/spool.db
export VERA_SPOOL_KEY="$(vault read -field=key secret/vera/spool)"
```

The spool refuses to start without `VERA_SPOOL_KEY`. AES-256-GCM,
PBKDF2-HMAC-SHA256 with 200,000 iterations, file mode `0600`. Rotation: see
[`docs/spool-key-rotation.md`](./docs/spool-key-rotation.md).

## Environment variables

Every `VERA_*` variable the SDK reads. Explicit `vera.init(...)` kwargs
always win; env vars are the fallback.

| Variable | Default | Description |
|---|---|---|
| `VERA_API_KEY` | (none) | API key from the dashboard. Prefixed `al_live_` (prod) or `al_test_` (sandbox). |
| `VERA_API_URL` | `https://api.usevera.xyz` | Backend URL. Override for self-hosted deployments or sandbox. |
| `VERA_AGENT_NAME` | `default-agent` | Identifies this agent in records. |
| `VERA_AGENT_VERSION` | (none) | Optional agent version string (e.g. `2026.05.13` or a git SHA). |
| `VERA_MODEL_ID` | (none) | Optional LLM model identifier (e.g. `gpt-4o`, `claude-sonnet-4-6`). |
| `VERA_FRAMEWORK` | (none) | Optional framework name: `openai`, `anthropic`, `langchain`, `crewai`. |
| `VERA_DEV` | (unset) | Set to `1` to enable dev mode. Records print to stderr; no API key required. |
| `VERA_DEV_CONFIRM` | (unset) | Bypass the production-key guard when running in dev mode. Set to `1` only if you really need `VERA_DEV=1` with a production-shaped API key (`al_live_*`). Without this, dev mode refuses to start with such keys to prevent accidentally silencing real audit logging in production. |
| `VERA_SPOOL_PATH` | (none) | Path to the durable encrypted SQLite spool. Requires `VERA_SPOOL_KEY`. |
| `VERA_SPOOL_KEY` | (none) | AES-256-GCM passphrase for the durable spool. Mandatory when `VERA_SPOOL_PATH` is set. |

Verify resolution at runtime:

```bash
vera config show
```

## Command-line interface

The `vera` CLI ships with the SDK as a runtime entry point. No extra install
step required.

### `vera init`

Scaffold a local `.env` and walk through API-key creation. Opens the
dashboard's API Keys page in your default browser, then asks you to paste
the new key back into the terminal (key input does not echo). Existing
config (`.env` in the target path **or** a `VERA_API_KEY` env var) is
detected — without `--force`, `init` exits 0 with a friendly summary
rather than clobbering.

```bash
vera init                          # interactive — opens browser
vera init --key al_test_xxxxxxxx   # script-friendly — skips browser
vera init --force                  # overwrite existing .env
vera init --env-file path/to/.env  # custom path
vera init --dashboard-url https://staging.app.usevera.xyz
```

Headless detection (`SSH_CONNECTION`, `CI`, no `DISPLAY` on Linux) falls
back to printing the URL instead of opening a browser. The file is
written `mode 0600` so the API key isn't world-readable.

### `vera quickstart`

The 5-minute zero-to-record path. Generates a small demo file with two
`@vera.gate`-decorated actions, runs it against the configured backend so
the auto-discovery pipeline registers the agent, and opens the dashboard
at `/customers/<tenant>` so you can see your first records.

```bash
vera quickstart                       # default demo file + random tenant
vera quickstart --tenant my_demo      # explicit tenant
vera quickstart --no-open             # don't auto-open the dashboard (CI)
vera quickstart --non-interactive     # fail if no config (don't drop into init)
vera quickstart --skip-run            # generate the file but don't execute
```

If no config is found and the run is interactive, `quickstart` invokes
`vera init` first so the whole flow is one command.

### `vera doctor`

Diagnostic checks against your environment. Independent checks for config,
connectivity, auth, tenant resolver, spool, SDK version, and codemod
availability. Exit code 1 if any check FAILs; WARN / INFO are non-fatal.

```bash
vera doctor
#   [PASS] config        API key present (test), API URL configured
#   [PASS] connectivity  200 from https://api.usevera.xyz/health (87ms)
#   [PASS] auth          authenticated as org org_1234…cdef
#   [INFO] tenant        no tenant configured — set VERA_TENANT_ID...
#   [INFO] spool         spool not configured (VERA_SPOOL_PATH unset)
#   [PASS] sdk_version   vera-sdk 1.0.0
#   [PASS] codemod       libcst available (codemod feature ready)
#
#   summary: 5 pass, 0 fail, 0 warn, 2 info

vera doctor --json     # structured output for CI:
# {"checks": [{"name": "config", "status": "PASS", ...}], "summary": {...}}
```

Out of scope for the current `doctor`: middleware-wiring detection (needs
a running app context) and customer-webhook URL reachability (the SDK
doesn't know what the customer's webhook URL is). Both are deferred to a
v2 `doctor`.

### `vera review-status <review_id>`

Fetch the status of a single approval. Three modes: one-shot lookup,
machine-readable JSON, and `--watch` polling.

```bash
# One-shot human-readable summary.
vera review-status app_01H7XKCRJF8
# Review app_01H7XKCRJF8                              [… PENDING]     risk: high
#
#   agent           dpo-bot
#   action          delete_customer_record
#   summary         Hard-delete user record per GDPR Art. 17
#   subject         user_42
#   requested       2026-05-24 14:27:00 UTC  (3m ago)
#   expires         2026-05-24 14:37:00 UTC  (in 7m)
#   approvers       2 required
#
# Context:
#   rows        1
#   table       customers

# Raw ApprovalResponse JSON (pretty-printed) — pipe to jq.
vera review-status app_01H7XKCRJF8 --json | jq .status

# Watch until the approval resolves (or you Ctrl-C).
vera review-status app_01H7XKCRJF8 --watch --interval 3

# Watch with a 5-minute deadline; exit code 3 if it never resolves.
vera review-status app_01H7XKCRJF8 --watch --timeout 300

# NDJSON for streaming pipelines (one object per poll).
vera review-status app_01H7XKCRJF8 --watch --json \
  | jq -c 'select(.status != "pending")'
```

Times are always rendered in UTC; relative phrases ("3m ago", "in 7m")
are computed from your local clock. Colors auto-disable when stdout is
not a TTY, when `NO_COLOR` is set, or with `--no-color`.

Exit codes:

- `0`: approval fetched (or reached a terminal state under `--watch`).
- `1`: approval not found (404).
- `2`: auth failure, wrong-tier key, network error, rate limit, or
  server error (specific reason printed to stderr).
- `3`: `--watch --timeout` reached before the approval resolved.
- `130`: user pressed Ctrl-C.

Compliance-pipeline pattern:

```bash
vera review-status "$ID" --watch --timeout 600
case $? in
  0) echo "approved or rejected — proceed" ;;
  3) echo "still pending after 10m — escalate" ;;
  *) echo "transport or auth failure — abort" ;;
esac
```

### `vera config show`

Print the effective configuration: env vars and computed defaults.

```bash
vera config show
#   api_url                 https://api.usevera.xyz
#   api_key                 ...x9f2
#   agent_name              loan-screener
#   agent_version           (unset)
#   model_id                gpt-4o
#   framework               openai
#   persistent_buffer_path  (off)
#   dev_mode                off
```

The API key is masked by default (`...<last4>` for keys at least 12 chars,
`***` otherwise). Pass `--reveal-secrets` to print it in full. Useful when
debugging a wrapper script:

```bash
vera config show --reveal-secrets
```

### `vera ping`

Verify the API key authenticates against `/v1/verify`. Reports latency.

```bash
vera ping
# Connecting to https://api.usevera.xyz...
# OK Authenticated to https://api.usevera.xyz in 142.0ms
#   status: ok
#   chain_length: 14271
```

Exit codes:

- `0`: authenticated successfully.
- `1`: auth failed, timeout, network error, or server error (specific reason
  printed to stderr).
- `2`: unexpected exception (please file an issue).

CI smoke-test pattern:

```bash
vera ping && echo "Vera reachable" || exit 1
```

### `vera tail`

Tail recent records for the org.

```bash
vera tail --limit 20

# Filter by agent.
vera tail --agent loan-screener

# Filter by result.
vera tail --result failure

# Follow new records as they arrive.
vera tail --follow --interval 2

# Emit JSON Lines for pipelines.
vera tail --json --limit 100 | jq 'select(.duration_ms > 5000)'

# Quick check: count failed actions in the last batch.
vera tail --result failure --json --limit 500 | jq -s 'length'
```

All commands respect every `VERA_*` env var. Run `vera <command> --help` for
the full option set.

## Verification

Vera's value to a regulator or auditor depends on three guarantees being
verifiable independently of Vera itself:

1. The record you're shown was the record we captured (Merkle inclusion).
2. The checkpoint that sealed it has not been altered (KMS signature).
3. The chain of records leading up to it is intact (previous-hash continuity).

Three CLI commands cover the verification flow end-to-end. They share a
common bundle format so an auditor can verify a customer's entire
evidence trail with only the bundle file and (for HMAC-signed bundles)
a shared secret.

A runnable, no-credentials walkthrough lives in
[`examples/verify_offline_walkthrough/`](./examples/verify_offline_walkthrough/).
Run it once before reading the rest of this section — the shape lands
faster from the bundle than from prose.

### `vera verify --merkle-proof <record_id>`

Online verification. Hits Vera, downloads the Merkle proof for one
record, then validates it locally against the customer's KMS public-key
history. Use this for spot checks during incident review or before
filing a regulator response.

```bash
vera verify --merkle-proof act_01H7XKCRJF8
# OK action_record act_01H7XKCRJF8 verified against checkpoint cp_2026-05-12
#   merkle_root:    93276b21b8623b35...
#   kms_key_id:     vera-prod-2026q2
#   signed_at:      2026-05-12T23:59:59+00:00
```

Exit codes:

- `0`: proof valid against the live KMS key history.
- `1`: proof invalid (tampered leaf, tampered sibling, root mismatch,
  or signature invalid). The specific reason prints to stderr.
- `2`: network / auth / 404 / 409 (record found but its checkpoint
  hasn't sealed yet — retry after `Retry-After: 60` per Wave 3B.2).

### `vera evidence-export --customer <tenant_id> --since <date> --out <path>`

Build a self-contained tar.gz bundle of one customer's records over a
date range. The bundle contains the Merkle proofs, signed checkpoints,
and KMS key history needed to verify every record without further
network calls.

```bash
vera evidence-export --customer cleveland_clinic \
                     --since 2026-02-25 --until 2026-05-25 \
                     --out ./evidence-cleveland-2026q2.tar.gz
```

Selective disclosure is structural: the bundle includes only Cleveland
Clinic's records and only the sibling hashes their Merkle proofs
require. An auditor inspecting the bundle cannot count or reconstruct
records belonging to any other customer.

For HMAC-signed bundles, hand the shared secret over an out-of-band
channel (BAA-covered email, signed envelope, in-person handoff). For
asymmetric bundles, the public keys travel inside the bundle and the
auditor needs nothing else.

### `vera verify --offline <bundle_path>`

Verify a bundle with no network access. The auditor runs this; you
don't need to.

```bash
vera verify --offline ./evidence-cleveland-2026q2.tar.gz
# OK 1,247 record(s) verified across 90 checkpoint(s)
# OK Chain integrity: all sibling links validate
# OK KMS signatures: all valid (vera-prod-2026q2)
```

Exit codes:

- `0`: every record verifies, every checkpoint signature validates.
- `1`: verification failed. The first failure prints to stderr with a
  structured reason: `merkle_proof_invalid`, `signature_invalid`,
  `root_mismatch`, `kms_key_not_in_history`, `record_count_mismatch`,
  `manifest_missing`, or `hmac_secret_missing`.
- `2`: bundle malformed or unreadable (bad tar, missing files).

### End-to-end session

Copy-paste-runnable. Substitute your real `tenant_id` and date range.

```bash
# 1. Export evidence for a specific customer over the last 90 days.
vera evidence-export --customer cleveland_clinic \
                     --since 2026-02-25 --until 2026-05-25 \
                     --out ./evidence-cleveland-2026q2.tar.gz

# 2. Hand the bundle to your compliance team or auditor.
scp ./evidence-cleveland-2026q2.tar.gz auditor@example.com:~

# 3. The auditor verifies offline — no Vera credentials needed.
vera verify --offline ./evidence-cleveland-2026q2.tar.gz
# OK 1,247 record(s) verified across 90 checkpoint(s)
# OK Chain integrity: all sibling links validate
# OK KMS signatures: all valid (vera-prod-2026q2)
```

For HMAC-signed bundles, the auditor needs the secret in their
environment before step 3:

```bash
export VERA_HMAC_SECRET="$(vault read -field=secret secret/vera/hmac/2026q2)"
vera verify --offline ./evidence-cleveland-2026q2.tar.gz
```

### Bundle shape

What `vera evidence-export` writes and what `vera verify --offline`
reads. Field names match the live API exactly so an auditor familiar
with one is immediately at home with the other.

```
bundle.tar.gz
  manifest.json                   bundle metadata + record + checkpoint counts
  checkpoints/<checkpoint_id>.json   one per sealed checkpoint
  records/<record_id>.json           one Merkle proof payload per record
  kms_keys.json                   KMS key history (algorithm + PEM per key_id)
```

**`manifest.json`** — top-level summary. Fields:

| Field | Type | Description |
|---|---|---|
| `schema_version` | int | Bundle schema version. Currently `1`. |
| `tenant_id` | string | The customer this bundle is scoped to. |
| `org_id` | string | The Vera organization that produced the bundle. |
| `since` / `until` | ISO date | The window covered. |
| `generated_at` | ISO timestamp | When the bundle was produced. |
| `record_count` | int | Total records included. |
| `checkpoints` | array | One summary entry per sealed checkpoint (`id`, `date`, `record_count`, `merkle_root`). |
| `kms_algorithm` | string | Dominant signing algorithm. `hmac-sha256`, `rsa-pss-sha256`, or `ecdsa-p256-sha256`. |
| `hmac_secret_required` | bool | `true` if any checkpoint in the bundle is HMAC-signed. |

**`checkpoints/<id>.json`** — one per sealed checkpoint. Mirrors the
`GET /v1/checkpoints/{date}` response body verbatim (Wave 3B.1):

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable checkpoint identifier. |
| `org_id` | string | Owning organization. |
| `date` | ISO date | The day this checkpoint sealed. |
| `sequence_at_checkpoint` | int | Last record sequence number sealed under this checkpoint. |
| `hash_at_checkpoint` | hex | Chain head hash at seal time. |
| `merkle_root` | hex | Merkle root over the records in this checkpoint window. |
| `signed_at` | ISO timestamp | KMS signing timestamp. |
| `key_id` | string | KMS key that signed this checkpoint. Look up in `kms_keys.json`. |
| `algorithm` | string | One of `hmac-sha256`, `rsa-pss-sha256`, `ecdsa-p256-sha256`. |
| `signature` | hex | KMS signature over the canonical message bytes. |
| `record_count` | int | Records sealed under this checkpoint. |

**`records/<record_id>.json`** — one Merkle proof per record. Mirrors
the `GET /v1/records/{id}/merkle-proof` response body verbatim
(Wave 3B.2):

| Field | Type | Description |
|---|---|---|
| `action_record_id` | string | The record this proof is for. |
| `action_record_canonical` | string | Canonical JSON bytes that hashed into the chain at insert time. |
| `leaf_hash` | hex | SHA-256(`previous_hash` + `action_record_canonical`). |
| `merkle_path` | array | Sibling hashes from leaf to root: `[{sibling_hash, direction}, ...]`. `direction` is `"left"` or `"right"`. |
| `merkle_root` | hex | The root of the Merkle tree for this checkpoint window. |
| `checkpoint_id` | string | The checkpoint that sealed this record. |
| `checkpoint_signed_at` | ISO timestamp | When that checkpoint was signed. |
| `kms_key_id` | string | KMS key used. Look up in `kms_keys.json`. |
| `kms_signature` | hex | The checkpoint signature. |
| `kms_algorithm` | string | The signing algorithm. |
| `kms_public_key_pem` | string \| null | The PEM for asymmetric keys; `null` for HMAC. |

**`kms_keys.json`** — array of every KMS key referenced by any
checkpoint in the bundle. The verifier walks this when a checkpoint's
`key_id` doesn't match the current production key (i.e., a rotation
happened during the bundle's window):

| Field | Type | Description |
|---|---|---|
| `key_id` | string | Unique identifier. |
| `algorithm` | string | `hmac-sha256`, `rsa-pss-sha256`, or `ecdsa-p256-sha256`. |
| `public_key_pem` | string \| null | PEM-encoded public key for asymmetric algorithms; `null` for HMAC. |
| `first_seen_at` | ISO timestamp | When this key first signed a checkpoint. |
| `retired_at` | ISO timestamp \| null | When this key was rotated out, if at all. |

### HMAC vs asymmetric KMS

The signing material is the load-bearing distinction between a
self-contained bundle and one that needs out-of-band coordination.

| Mode | Bundle self-contained? | What the auditor needs |
|---|---|---|
| `hmac-sha256` | No | The bundle + `VERA_HMAC_SECRET` shared out-of-band |
| `rsa-pss-sha256` | Yes | Just the bundle |
| `ecdsa-p256-sha256` | Yes | Just the bundle |

HMAC is fine for internal review and dev workflows. For external
auditors, regulator submissions, and any context where you'd rather not
hand a customer's compliance team your signing secret, move the org to
asymmetric KMS. Contact <support@usevera.xyz> to coordinate the
migration; the KMS history table (Wave 3A.a) means past checkpoints
keep verifying against their original signing keys without re-signing.

### Verification-specific environment variables

| Variable | Used by | Description |
|---|---|---|
| `VERA_HMAC_SECRET` | `vera verify --offline` | Shared HMAC secret for HMAC-signed bundles. Required when `manifest.json` has `hmac_secret_required: true`. Mirrors the backend's `ACTIONLEDGER_SIGNING_KEY` value. |
| `VERA_TARGET_ORG_ID` | `vera verify --offline`, `vera evidence-export` | Pin an org context when your API key is multi-org or when bundle metadata needs explicit scoping. Optional for single-org accounts. |

The standard `VERA_API_KEY` / `VERA_API_URL` apply only to
`evidence-export` and `verify --merkle-proof` (both hit Vera).
`verify --offline` never reads them — it has no network surface.

## Troubleshooting

### `VeraAuthError: Authentication failed`

- Verify your key with `vera config show`: is it set, is it the right one?
- Confirm with the live API: `vera ping`.
- Prod keys are prefixed `al_live_`; sandbox keys `al_test_`. Make sure you
  aren't pointing prod traffic at the test environment or vice versa.

### My records aren't appearing in the dashboard

- Run `vera ping` to confirm the network can reach `api.usevera.xyz` and the
  key authenticates.
- Check for `[vera-dev]` lines on stderr. That means `VERA_DEV=1` is set
  somewhere and records are going to the dev sink, not to Vera.
- Check stderr for `[vera] WARNING: no default client configured`. That
  means `@vera.audit` is running but `vera.init()` was never called.
- Confirm `agent_name` matches what you're filtering on in the dashboard.
- The async queue flushes on a timer. Records can take a few seconds to
  arrive. For tests, use the `vera_sdk_recording` pytest fixture or
  `client.close()` to drain synchronously.

### `VeraRateLimitError`

You're sending records faster than your plan allows. Options:

- Reduce per-call traffic. Make sure you aren't double-wrapping the same
  function with `@audit` and a framework integration.
- Contact <support@usevera.xyz> to raise your plan limits.

### `VeraTimeoutError` on every call

- `VeraClient`'s default HTTP timeout is 5 seconds. If you're on a slow
  network, raise it: `vera.init(..., timeout=15)`.
- The `@audit` decorator pipeline is async. It never blocks on Vera and
  never raises `VeraTimeoutError` to your code. Timeouts surface inside the
  worker thread and end up as `result="failure"` records.

### `VeraValidationError: ...`

A call has an invalid field. The exception message names the offending
field. Common cases:

- `record_action(...)`: missing `action_name`, or `action_name` longer than
  the server limit. The exception message names the field.
- `request_approval(...)`: `risk_tier` outside `{low, medium, high,
  critical}`, or a `data_subject_id` longer than 255 chars.

### Spool refuses to start: "Spool requires a non-empty passphrase"

`VERA_SPOOL_PATH` is set but `VERA_SPOOL_KEY` is not. The spool refuses to
write plaintext to disk. Either set `VERA_SPOOL_KEY` from your secret
manager or unset `VERA_SPOOL_PATH`.

### "Check VERA_SPOOL_KEY: the key supplied does not match..."

The spool file on disk was encrypted with a different `VERA_SPOOL_KEY`.
Either restore the original key or rotate per the
[`docs/spool-key-rotation.md`](./docs/spool-key-rotation.md) flow.

### `ImportError: openai is required for OpenAI integration`

You imported `vera.integrations.openai` without installing the extra. Fix:

```bash
pip install "vera-sdk[openai]"
```

Same pattern for `anthropic`, `langchain`, `crewai`, and `spool`.

### `DeprecationWarning: max_input_length is deprecated`

The LangChain callback's `max_input_length` and `max_output_length` kwargs
are ignored. Pass `redactor=Redactor(max_length=...)` instead.

### Records are being redacted that shouldn't be

The redactor's `block_keys` are aggressive by design. Better to over-redact
than leak. If a kwarg is blocked but should pass through, build a custom
Redactor with a narrower `block_keys` set or declare the field
`PASSTHROUGH` in a schema. See [Concepts](#concepts) above.

### Tests are seeing records from another test

Use the `vera_sdk_recording` pytest fixture. It auto-loads when the SDK is
installed, clears records between tests, and avoids the network entirely.

```python
def test_loan_decision(vera_sdk_recording):
    approve_loan(applicant_id="user_42", amount=10000)
    assert len(vera_sdk_recording.records) == 1
    assert vera_sdk_recording.records[0]["action_name"] == "approve_loan"
```

## HTTP API reference

Full HTTP API docs: <https://docs.usevera.xyz/api>. The same backend exposes
auto-generated OpenAPI at <https://api.usevera.xyz/docs> (Swagger UI) and
<https://api.usevera.xyz/openapi.json> (machine-readable schema).

Most teams should not need to call the HTTP API directly. The SDK covers
every endpoint. Use the raw API when:

- You are integrating from a language other than Python (Go, TypeScript,
  Ruby). Generate a client from the OpenAPI schema.
- You are integrating from a no-code platform (Zapier, n8n).
- You need an endpoint the SDK does not yet wrap (the SDK trails the API by
  a release or two for niche endpoints).

Authentication is `Authorization: Bearer <api_key>` on every request.

## Versioning policy

`vera-sdk` follows [Semantic Versioning](https://semver.org/). Breaking
behavioral changes ship behind a `DeprecationWarning` for at least one minor
release before the default flips. See [`CHANGELOG.md`](./CHANGELOG.md) for
the release history and [`MIGRATION.md`](./MIGRATION.md) for upgrade notes.

## Links

- Dashboard: <https://app.usevera.xyz>
- HTTP API docs: <https://docs.usevera.xyz/api>
- BAA request: <https://usevera.xyz/baa>
- Changelog: [`CHANGELOG.md`](./CHANGELOG.md)
- Migration notes: [`MIGRATION.md`](./MIGRATION.md)
- Spool key rotation: [`docs/spool-key-rotation.md`](./docs/spool-key-rotation.md)
- Support: <support@usevera.xyz>

## License

MIT.
