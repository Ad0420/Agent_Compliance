# vera-sdk

Python SDK for **Vera**, a runtime trust layer for AI agents. Vera gives every
agent action an immutable, cryptographically verifiable audit trail; supports
human-in-the-loop (HITL) approvals for high-risk actions; and enforces policies
in real time. Built for teams shipping AI into regulated contexts (EU AI Act,
GDPR, NIST AI RMF, HIPAA).

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
client. Use `vera.init_async(...)` (or `vera.init_async_awaitable(...)`) for
async codepaths.

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

vera.init(
    api_key=os.environ["VERA_API_KEY"],
    agent_name="medical-scribe",
    framework="openai",
    model_id="gpt-4o",
    redactor=Redactor.medtech(
        extra_block_keys={"insurance_member_id"},
    ),
)

client = AuditedOpenAI(openai.OpenAI(), ledger_client=vera.get_client())

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
every nested call inherits it):

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
| Fax numbers | block_keys: same as phone; declare a `fax` field via custom schema |
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

Opaque, randomly-generated `patient_id` values (e.g. `pat_a8f3b2c1`) are
HIPAA-safe. The starter schema marks `patient_id` as `PASSTHROUGH` so audit
records stay searchable.

If your `patient_id` is an MRN or otherwise contains real PHI, force
redaction:

```python
redactor = Redactor.medtech(extra_block_keys={"patient_id"})
```

Same pattern for any field your domain models as ID-shaped but populates
with real-world identifiers.

### Free-text PHI

Regex cannot reliably scrub names, dates, and identifiers from prose. The
starter schema redacts `notes`, `description`, `summary`, `comment`,
`comments`, `message`, `transcript`, `audio_transcript`, `email_body`,
`body`, and `text` wholesale.

If you have a free-text field with PHI that uses a non-default name, declare
it explicitly:

```python
from vera.redaction import Redactor
from vera.redaction import Schema, FieldRule, FieldPolicy

schema = Redactor.medtech_starter_schema()
schema.fields["physician_notes"] = FieldRule(
    FieldPolicy.REDACT,
    description="Free-text physician notes.",
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
| `VERA_SPOOL_PATH` | (none) | Path to the durable encrypted SQLite spool. Requires `VERA_SPOOL_KEY`. |
| `VERA_SPOOL_KEY` | (none) | AES-256-GCM passphrase for the durable spool. Mandatory when `VERA_SPOOL_PATH` is set. |

Verify resolution at runtime:

```bash
vera config show
```

## Command-line interface

The `vera` CLI ships with the SDK as a runtime entry point. No extra install
step required.

### `vera config show`

Print the effective configuration: env vars and computed defaults.

```bash
vera config show
# api_url:         https://api.usevera.xyz
# api_key:         ...x9f2
# agent_name:      loan-screener
# agent_version:   (unset)
# model_id:        gpt-4o
# framework:       openai
# spool_path:      (unset)
# dev_mode:        false
# sdk_version:     0.5.0
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

Your `record_action(...)` call has an invalid field. Usually a missing
`action_name`, a `risk_tier` outside `{low, medium, high, critical}`, or a
`data_subject_id` longer than 255 chars. The exception message names the
field.

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
