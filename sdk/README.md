# vera-sdk

Python SDK for **Vera** — a runtime trust layer for AI agents. Vera gives every
agent action an immutable, cryptographically verifiable audit trail; supports
human-in-the-loop (HITL) approvals for high-risk actions; and enforces policies
in real time. Built for teams shipping AI into regulated contexts (EU AI Act,
GDPR, NIST AI RMF).

## Install

```bash
pip install vera-sdk

# With framework integrations:
pip install "vera-sdk[langchain,openai,anthropic,crewai]"
```

## Quickstart

### 1. Sync client — record actions directly

```python
from vera import VeraClient

client = VeraClient(
    api_url="https://your-vera-instance",
    api_key="al_live_...",
    agent_name="loan-screener",
    model_id="gpt-4o",
)

client.record_action(
    action_name="approve_loan",
    action_type="decision",
    result="success",
    input_data={"applicant_id": "user_42", "amount": 25_000},
    outcome={"approved": True},
    reasoning={"score": 0.93, "rule": "auto-approve under $50k"},
    data_subject_id="user_42",
)
```

### 2. `@audit` decorator — zero-boilerplate logging

```python
from vera import audit, set_default_client

set_default_client(client)

@audit(action_name="process_payment", action_type="api_call")
def process_payment(invoice_id: str):
    return {"status": "paid"}
    # Recorded automatically on success or failure (with traceback).
```

### 3. Async client — non-blocking, batched

```python
from vera import AsyncVeraClient, async_audit, set_default_async_client

async with AsyncVeraClient(
    api_url="https://your-vera-instance",
    api_key="al_live_...",
    agent_name="fast-agent",
) as client:
    client.start_background_flush()  # Batches sent every 5s
    set_default_async_client(client)

    @async_audit(action_name="process")
    async def process(item):
        ...  # Zero added latency — auditing runs in the background queue.
```

### 4. Human-in-the-loop approval (EU AI Act Article 14)

```python
from vera import VeraClient, ApprovalRejectedError

client = VeraClient(api_url="...", api_key="...", agent_name="dpo-agent")

approval = client.request_approval(
    action_name="delete_user_account",
    risk_tier="critical",
    action_summary="Hard-delete PII for user_42",
    data_subject_id="user_42",
    approvers_required=2,       # dual-verification
    expires_in_seconds=3600,
)

try:
    client.wait_for_approval(approval["id"], timeout=600)
    # ... actually perform the deletion
except ApprovalRejectedError as e:
    print("Blocked:", e.approval["status"])
```

Every approval vote is KMS-signed and appended to the same audit chain as the
underlying action — giving you a tamper-evident proof that a specific human
approved a specific action at a specific time.

### Timeouts and retry semantics

`VeraClient` and `AsyncVeraClient` default to a 5-second HTTP timeout. Audit
operations are designed to fail fast — your customer-facing code should never
block on Vera availability. The decorator layer (`@audit`, `@async_audit`)
catches transport failures internally so they never propagate to your
application code. If you need longer timeouts for specific deployments, pass
`timeout=...` explicitly to the constructor.

## Documentation

Full docs, dashboard, and API reference: <https://usevera.xyz>.

### Versioning policy

`vera-sdk` follows [Semantic Versioning](https://semver.org/). Breaking
behavioral changes ship behind a `DeprecationWarning` for at least one minor
release before the default flips. See [`CHANGELOG.md`](./CHANGELOG.md) and
[`MIGRATION.md`](./MIGRATION.md).

## License

MIT.
