# Vera

Tamper-proof audit trail for AI agents. Cryptographic hash chain with tamper-proof verification, built for teams that need to prove what their AI agents did, when, and why.

**Live:** [usevera.xyz](https://usevera.xyz) (password-protected testing environment)

**The problem:** AI agents are taking consequential actions — approving loans, flagging transactions, making hiring recommendations — with no verifiable record. Regulators (EU AI Act Art. 12, GDPR, Colorado AI Act, SEC Rule 17a-4) are requiring tamper-proof logs. When something goes wrong, teams cannot answer: what did the agent do, did a human approve it, and has the log been touched since? AWS QLDB (the only comparable managed service) was deprecated July 2025. Vera fills that gap.

**The solution:** A four-layer immutability stack: database triggers prevent edits, a SHA-256 hash chain detects tampering, KMS-signed checkpoints prevent chain recomputation, and S3 WORM external proofs survive full database compromise. Drop-in Python SDK with integrations for LangChain, OpenAI, and CrewAI.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
- [How It Works](#how-it-works)
- [SDK Usage](#sdk-usage)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [Regulatory Compliance](#regulatory-compliance)
- [Known Issues & Limitations](#known-issues--limitations)
- [Changelog](#changelog)

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.10+ | `python --version` |
| pip | any | `pip --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Docker (optional) | 20+ | `docker --version` |

---

## Quickstart

### Option A: Local development (SQLite, no Docker)

**Terminal 1 — Backend:**

```bash
cd backend
pip install -r requirements.txt
python setup_local.py
```

Expected output:
```
[OK] Database tables created
[OK] Organization created: Vera Org (id: xxxxxxxx-xxxx-...)
[OK] Admin API key created

============================================================
  YOUR API KEY (save this — it won't be shown again):
  al_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
============================================================
```

**Copy the API key.** It is shown once and cannot be retrieved.

Then start the server:
```bash
uvicorn app.main:app --reload
# API running at http://localhost:8000
# Docs at http://localhost:8000/docs (Swagger UI)
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:3000
```

Open http://localhost:3000 — you'll see the landing page. Click "Get started", paste your API key, and you're in the dashboard at `/dashboard`.

### Option B: Docker with PostgreSQL

```bash
# From project root
docker compose up -d
# API at http://localhost:8000, PostgreSQL at localhost:5432

# Then run setup to get your API key:
docker compose exec api python setup_local.py
```

### Option C: Install just the SDK

```bash
cd sdk
pip install -e .

# With framework integrations:
pip install -e ".[langchain,openai,crewai]"
```

---

## How It Works

```
Agent Action --> SDK --> API --> Hash Chain --> Checkpoint --> External Proof (S3 WORM)
                                    |
                         DB Triggers block UPDATE/DELETE
```

### Four layers of immutability

| Layer | Mechanism | What It Prevents | Status |
|-------|-----------|------------------|--------|
| 1. Database triggers | PL/pgSQL `BEFORE UPDATE/DELETE` | Application bugs, accidental edits | Tested |
| 2. SHA-256 hash chain | `hash(N) = SHA-256(hash(N-1) + canonical_json(record_N))` | Silent data corruption, single-record tampering | Tested |
| 3. KMS-signed checkpoints | Periodic snapshots signed with HMAC-SHA256 or AWS KMS | Attacker recomputing the entire chain after tampering | Tested (local KMS) |
| 4. S3 WORM external proofs | Checkpoint proofs published to S3 Object Lock (COMPLIANCE mode) | Full database compromise — proofs survive independently | Code complete, untested with real S3 |

**What "immutable" actually means here:**
- **Layer 1** stops accidents. A DBA with superuser access can still disable triggers.
- **Layer 2** detects tampering. Modifying one record breaks every hash after it.
- **Layer 3** prevents chain recomputation. Checkpoints are signed with a key the attacker doesn't have (with AWS KMS, the key never leaves hardware).
- **Layer 4** is the final guarantee. Even with root access AND the KMS key, proofs in S3 WORM physically cannot be deleted for the retention period.

### How the hash chain works

Every action record contains 27 fields. **All** of them are included in the hash:

```
record_hash = SHA-256(previous_hash + canonical_json(all_fields))
```

- `canonical_json`: sorted keys, no whitespace, no null values, UTC-normalized datetimes truncated to milliseconds
- First record in each org's chain uses `previous_hash = "GENESIS"`
- Each organization has an independent chain (multi-tenant isolation)
- The field list is defined in `backend/app/services/hashing.py:HASHABLE_FIELDS` (single source of truth)

---

## SDK Usage

### Record an action (direct)

```python
from actionledger import ActionLedgerClient

client = ActionLedgerClient(
    api_url="http://localhost:8000",
    api_key="al_live_...",        # from setup_local.py
    agent_name="my-agent",
    model_id="gpt-4o",
)

client.record_action(
    action_name="approve_invoice",
    action_type="decision",
    result="success",
    input_data={"invoice_id": "INV-001", "amount": 5000},
    outcome={"approved": True},
    reasoning={"confidence": 0.95, "rule": "auto-approve under $10k"},
)
```

### Use the decorator (zero-code auditing)

```python
from actionledger import audit, set_default_client

set_default_client(client)

@audit(action_name="process_payment", action_type="api_call")
def process_payment(invoice_id: str):
    return {"status": "paid"}
    # Automatically recorded on success or failure
```

### Verify the chain

```python
result = client.verify_chain()
# {"is_valid": true, "records_checked": 1, "message": "All 1 records verified successfully"}
```

### LangChain integration

```python
from actionledger.integrations.langchain import ActionLedgerCallbackHandler

handler = ActionLedgerCallbackHandler(client=client)
chain.invoke(inputs, config={"callbacks": [handler]})
# Records: LLM calls (with tokens), chain executions, tool uses, agent decisions
```

Hooks: `on_llm_start/end/error`, `on_chain_start/end/error`, `on_tool_start/end/error`, `on_agent_action/finish`.

### OpenAI integration

```python
from actionledger.integrations.openai import AuditedOpenAI
import openai

audited = AuditedOpenAI(openai.OpenAI(), ledger_client=client)
response = audited.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

**Limitation:** `stream=True` is NOT supported. Streaming calls pass through unaudited with a warning.

### CrewAI integration

```python
from actionledger.integrations.crewai import enable_crewai_auditing

enable_crewai_auditing(client=client)
# All CrewAI tool executions are automatically recorded
```

Thread-safe (`threading.local()`). Idempotent — safe to call multiple times.

### Async SDK

```python
from actionledger import AsyncActionLedgerClient, async_audit, set_default_async_client

async with AsyncActionLedgerClient(
    api_url="http://localhost:8000",
    api_key="al_live_...",
    agent_name="fast-agent",
) as client:
    client.start_background_flush()  # Batches sent every 5s
    set_default_async_client(client)

    @async_audit(action_name="process")
    async def process(item):
        ...  # Zero latency added — auditing happens in background
```

---

## API Reference

All endpoints require `Authorization: Bearer <api_key>` header (except `/health`).

### Actions

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `POST` | `/v1/actions` | write | Record a single action |
| `POST` | `/v1/actions/batch` | write | Record up to 100 actions atomically |
| `GET` | `/v1/actions` | read | Query actions (filters: `agent_name`, `action_type`, `result`, `start_date`, `end_date`, `authorized_by`, `data_subject_id`, `search`) |
| `GET` | `/v1/actions/{id}` | read | Get a single action by ID |

### Verification

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `GET` | `/v1/verify` | read | Verify entire hash chain integrity (streaming, 500 records/chunk) |
| `GET` | `/v1/verify/{id}` | read | Verify a single record's hash + chain link |
| `POST` | `/v1/verify/checkpoints` | admin | Create signed checkpoint (Merkle root + external proof) |
| `GET` | `/v1/verify/checkpoints` | read | List all checkpoints |
| `POST` | `/v1/verify/checkpoints/verify` | read | Verify all checkpoint signatures |

### Agents & Organization

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `POST` | `/v1/agents` | write | Register an agent |
| `GET` | `/v1/agents` | read | List agents |
| `POST` | `/v1/organizations` | admin | Create organization |
| `GET` | `/v1/organizations/me` | read | Get current organization |

### API Keys

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `POST` | `/v1/api-keys` | admin | Create API key (raw key returned **once**; optional `expires_at` datetime) |
| `GET` | `/v1/api-keys` | admin | List API keys (prefix only) |
| `DELETE` | `/v1/api-keys/{id}` | admin | Revoke API key (permanent, irreversible) |

### Export

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `GET` | `/v1/export/csv` | read | Stream CSV of action records (filters: `agent_name`, `action_type`, `result`, `start_date`, `end_date`; `limit` default 5000, max 10000; 27 columns) |
| `GET` | `/v1/export/pdf` | read | Generate PDF audit report (chain integrity + checkpoints + action records; max 5000 records) |

### System

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `GET` | `/health` | none | Health check (DB connectivity) |

**Rate limits:** 120 requests/minute per API key, 20 burst/second (configurable via `RATE_LIMIT_RPM` and `RATE_LIMIT_BURST`).

**Permission model:** Each API key has one or more permissions: `read`, `write`, `admin`. Keys are SHA-256 hashed before storage. Authentication uses constant-time comparison to prevent timing attacks.

---

## Configuration

All config is via environment variables. Set in `.env` file or export directly.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./vera.db` | Database connection string. Use `postgresql+asyncpg://user:pass@host:5432/dbname` for production |
| `SECRET_KEY` | `dev_secret_change_in_production` | App secret for general use. **App refuses to start in production with the default** |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins for the frontend |
| `RATE_LIMIT_RPM` | `120` | Requests per minute per API key |
| `RATE_LIMIT_BURST` | `20` | Max burst requests per second |
| `ACTIONLEDGER_KMS_PROVIDER` | `local` | `local` (HMAC-SHA256) or `aws` (AWS KMS hardware-backed) |
| `ACTIONLEDGER_SIGNING_KEY` | falls back to `SECRET_KEY` in dev | Dedicated signing key for checkpoint signatures. **Required in production** — app refuses to start without it |
| `AWS_KMS_KEY_ID` | — | AWS KMS key ARN (required when `KMS_PROVIDER=aws`) |
| `AWS_REGION` | `us-east-1` | AWS region for KMS and S3 |
| `ACTIONLEDGER_EXTERNAL_STORE` | `local` | `local` (JSON Lines file) or `s3` (S3 Object Lock WORM) |
| `ACTIONLEDGER_S3_BUCKET` | — | S3 bucket name (required when `EXTERNAL_STORE=s3`; must have Object Lock enabled) |
| `ACTIONLEDGER_S3_RETENTION_DAYS` | `365` | S3 Object Lock retention period in days (COMPLIANCE mode) |
| `MAX_BATCH_SIZE` | `100` | Max records per batch request |
| `MAX_JSON_FIELD_SIZE` | `1000000` | Max bytes per JSON field (1 MB) |
| `API_KEY_PREFIX` | `al_live_` | Prefix for generated API keys |

Copy the table above into a `.env` file in the `backend/` directory and set at minimum `SECRET_KEY` and `DATABASE_URL` before running in production.

---

## Deployment

### Local development (SQLite)

```bash
cd backend
pip install -r requirements.txt
python setup_local.py          # Creates DB + org + API key
uvicorn app.main:app --reload  # http://localhost:8000
```

Data stored in `backend/vera.db` (single file, auto-created).

> **After pulling new model changes:** delete `vera.db` and re-run `python setup_local.py` — `create_all` picks up new columns automatically. For PostgreSQL, run `alembic upgrade head` instead (handled automatically in production via `start.sh`).

### Railway + Vercel (current production deployment)

The live instance at [usevera.xyz](https://usevera.xyz) runs on:
- **Backend:** Railway (FastAPI + PostgreSQL). Custom start command: `sh start.sh` which runs `python setup_local.py && alembic upgrade head` then starts uvicorn.
- **Frontend:** Vercel (Next.js). Environment variable `NEXT_PUBLIC_API_URL` points to the Railway backend URL.

**Required Railway environment variables:**

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway internal reference) |
| `SECRET_KEY` | Random hex string |
| `ENVIRONMENT` | `production` |
| `CORS_ORIGINS` | `https://usevera.xyz,https://www.usevera.xyz` |

**Required Vercel environment variables:**

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | Railway backend URL (no trailing slash) |
| `SITE_PASSWORD` | Site-wide basic auth password (optional — omit for public access) |

On every deploy, Railway runs `start.sh`:
```sh
#!/bin/sh
python setup_local.py     # Creates org + admin key if first boot (idempotent)
alembic upgrade head      # Applies any pending DB migrations
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The admin API key is printed once in the Railway deploy logs on first boot. Save it.

### Docker with PostgreSQL (recommended for development)

```bash
# Development (hot-reload, DB port 5432 exposed)
docker compose up -d

# Production (Gunicorn, 4 workers, DB port closed)
# Create a .env file with SECRET_KEY, POSTGRES_PASSWORD, and other required vars (see Configuration)
docker compose -f docker-compose.prod.yml up -d
```

### Production on AWS

**Minimum viable deployment:**
1. **RDS PostgreSQL** — encrypted at rest, automated backups, Multi-AZ
2. **ECS Fargate** (or EC2) — running the backend Docker container
3. **ALB** — TLS termination, health checks on `/health`
4. **S3 + CloudFront** (or Vercel) — frontend static hosting

**Full immutability stack** (add to `.env`):
```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
ACTIONLEDGER_SIGNING_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
POSTGRES_PASSWORD=<strong-random-password>
ENVIRONMENT=production

# AWS KMS — checkpoint signing (key never leaves hardware)
ACTIONLEDGER_KMS_PROVIDER=aws
AWS_KMS_KEY_ID=arn:aws:kms:us-east-1:123456789:key/your-key-id
AWS_REGION=us-east-1

# S3 WORM — checkpoint proofs in undeletable storage
ACTIONLEDGER_EXTERNAL_STORE=s3
ACTIONLEDGER_S3_BUCKET=your-actionledger-proofs
```

<details>
<summary><strong>Setting up S3 WORM bucket</strong></summary>

```bash
aws s3api create-bucket \
  --bucket your-actionledger-proofs \
  --region us-east-1

aws s3api put-object-lock-configuration \
  --bucket your-actionledger-proofs \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 365
      }
    }
  }'
```
</details>

<details>
<summary><strong>Setting up AWS KMS signing key</strong></summary>

```bash
aws kms create-key \
  --key-spec HMAC_256 \
  --key-usage GENERATE_VERIFY_MAC \
  --description "Vera checkpoint signing key"

# Use the KeyId from the output as AWS_KMS_KEY_ID
```
</details>

### Database migrations

```bash
cd backend

# Apply all migrations (SQLite)
alembic upgrade head

# Apply against PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/dbname alembic upgrade head

# Generate a new migration after changing a model
alembic revision --autogenerate -m "add risk_score column"
```

### Production checklist

Before deploying to real users:

- [ ] Set `SECRET_KEY` to a unique random value (not the default)
- [ ] Set `ACTIONLEDGER_SIGNING_KEY` to a unique value (separate from `SECRET_KEY`)
- [ ] Set `ENVIRONMENT=production`
- [ ] Switch to PostgreSQL (`DATABASE_URL=postgresql+asyncpg://...`)
- [ ] Run `alembic upgrade head` against PostgreSQL
- [ ] Set `CORS_ORIGINS` to your actual frontend domain
- [ ] Enable HTTPS at load balancer level
- [ ] Set rate limits for your traffic (`RATE_LIMIT_RPM`, `RATE_LIMIT_BURST`)
- [ ] If using AWS KMS: set `AWS_KMS_KEY_ID`, verify IAM permissions for `kms:GenerateMac` and `kms:VerifyMac`
- [ ] If using S3 WORM: verify bucket has Object Lock enabled (`aws s3api get-object-lock-configuration`)
- [ ] Test `POST /v1/verify/checkpoints` with your KMS/S3 config before going live
- [ ] Set up database backups (RDS automated backups or `pg_dump` cron)
- [ ] Set up monitoring on `/health` endpoint

---

## Testing

```bash
# Backend — 63 tests
cd backend && python -m pytest tests/ -v

# SDK — 6 tests
cd sdk && python -m pytest tests/ -v

# Frontend — build check (no test suite yet)
cd frontend && npm run build
```

**69 total tests, all passing.** Tests use an in-memory SQLite database, no external services required.

### What's tested

| Area | Tests | What's Covered |
|------|-------|----------------|
| API endpoints | 22 | CRUD for actions, agents, orgs, API keys, verification, checkpoints, auth errors |
| Authentication | 5 | Key generation, correct/wrong key, revocation, permission checking |
| Hash chain | 4 | Single insert, sequential chaining, batch insert, full chain verification |
| Hardening | 21 | Immutability triggers (UPDATE/DELETE blocked), tamper detection, concurrent inserts, cross-org isolation, checkpoint tampering, permission matrix, input validation, batch atomicity |
| Hashing | 11 | Canonical JSON (sorting, null filtering, determinism), hash computation, record verification |
| SDK decorators | 6 | Success/failure recording, no-client fallback, input capture, default client |

### What's NOT tested

| Gap | Impact |
|-----|--------|
| AWS KMS (`AWSKMS` class) | Requires real AWS credentials |
| S3 WORM store (`S3WORMStore`) | WORM guarantee unverified |
| OpenAI / CrewAI / LangChain integrations | No mocked or integration tests |
| Rate limiting middleware | Tested manually only |
| Alembic migrations on PostgreSQL | Migration verified on SQLite only |
| Frontend | No unit, integration, or E2E tests |

---

## Project Structure

```
.
├── .gitignore                       Ignores __pycache__, *.db, node_modules, .next, .env files
├── docker-compose.yml               Dev: PostgreSQL 16 + API with hot-reload
├── docker-compose.prod.yml          Prod: Gunicorn, 4 workers, DB port closed
├── README.md                        This file
│
├── backend/
│   ├── requirements.txt             Python dependencies
│   ├── setup_local.py               Bootstrap: creates DB, org, API key
│   ├── Dockerfile                   Python 3.12-slim container
│   ├── alembic.ini                  Migration configuration
│   ├── alembic/
│   │   ├── env.py                   Migration env (async URL conversion)
│   │   └── versions/               Generated migrations (incl. a1b2c3d4e5f6: data_subject_id + expires_at)
│   ├── migrations/
│   │   └── init.sql                 PostgreSQL schema (tables + triggers)
│   ├── app/
│   │   ├── main.py                  FastAPI app, lifespan, CORS, middleware
│   │   ├── config.py                Pydantic Settings (all env vars)
│   │   ├── database.py              Async SQLAlchemy engine + session factory
│   │   ├── models/
│   │   │   ├── organization.py      Multi-tenant org
│   │   │   ├── api_key.py           SHA-256 hashed API keys with RBAC
│   │   │   ├── agent.py             Registered AI agents
│   │   │   ├── chain_state.py       Per-org chain head (sequence + hash)
│   │   │   ├── action_record.py     30+ field audit record (the core entity)
│   │   │   └── checkpoint.py        Signed snapshots with Merkle root
│   │   ├── schemas/                 Pydantic request/response models
│   │   ├── routes/
│   │   │   ├── actions.py           CRUD + query with filters
│   │   │   ├── agents.py            Agent registration
│   │   │   ├── verification.py      Chain + record verification
│   │   │   ├── checkpoints.py       Checkpoint create/list/verify
│   │   │   ├── organizations.py     Org CRUD
│   │   │   ├── api_keys.py          Key create/list/revoke
│   │   │   └── export.py            CSV stream + PDF generation endpoints
│   │   ├── services/
│   │   │   ├── hashing.py           *** HASHABLE_FIELDS, canonical JSON, SHA-256
│   │   │   ├── chain.py             Chain building with per-org locks
│   │   │   ├── verification.py      Streaming verification (500 records/chunk)
│   │   │   ├── checkpoint.py        Signed checkpoints + Merkle + external proof
│   │   │   ├── kms.py               LocalKMS (HMAC-SHA256) + AWSKMS
│   │   │   ├── external_store.py    LocalFileStore + S3WORMStore
│   │   │   ├── merkle.py            Binary Merkle tree (proof gen/verify)
│   │   │   ├── immutability.py      SQLite trigger installation
│   │   │   ├── export.py            CSV streaming generator + PDF builder (fpdf2)
│   │   │   └── auth.py              API key generation, auth, permissions
│   │   └── middleware/
│   │       └── rate_limit.py        Sliding-window per API key
│   └── tests/                       63 tests
│
├── sdk/
│   ├── setup.py                     Package definition (pip install -e .)
│   └── actionledger/
│       ├── __init__.py              Public API exports
│       ├── client.py                Sync client (retry + exponential backoff)
│       ├── async_client.py          Async client (background queue, batch flush)
│       ├── decorator.py             @audit (sync functions)
│       ├── async_decorator.py       @async_audit (async functions)
│       └── integrations/
│           ├── langchain.py         BaseCallbackHandler (LLM, chain, tool, agent)
│           ├── openai.py            AuditedOpenAI wrapper (non-streaming only)
│           └── crewai.py            BaseTool monkey-patch
│
└── frontend/
    ├── package.json                 Dependencies (Next.js 16, React 19, Radix, TanStack)
    ├── components.json              shadcn/ui configuration
    ├── lib/
    │   ├── api-client.ts            Typed fetch wrapper (Bearer auth, 401 redirect)
    │   ├── api-types.ts             TypeScript interfaces matching backend schemas
    │   ├── auth.ts                  localStorage helpers (API key, admin flag)
    │   ├── constants.ts             UI constants (colors, labels)
    │   └── utils.ts                 cn(), formatDate(), truncateHash()
    ├── hooks/
    │   ├── use-auth.tsx             AuthContext + AuthProvider + useAuth hook
    │   ├── use-actions.ts           TanStack Query for actions
    │   ├── use-agents.ts            TanStack Query for agents
    │   ├── use-checkpoints.ts       TanStack Query for checkpoints
    │   ├── use-verification.ts      TanStack Query for chain verification
    │   ├── use-organization.ts      TanStack Query for org info
    │   └── use-api-keys.ts          TanStack Query for API key management
    ├── components/
    │   ├── ui/                      shadcn/ui primitives (17 components)
    │   ├── layout/                  Sidebar, Topbar, ProtectedRoute
    │   ├── shared/                  StatusBadge, JsonViewer, Pagination
    │   └── dashboard/              ChainStatusCard, StatsRow, ActionChart
    └── app/
        ├── layout.tsx               Root layout (dark theme, Geist fonts)
        ├── providers.tsx            QueryClient + Auth + Tooltip providers
        ├── globals.css              Tailwind + dark theme variables
        ├── login/page.tsx           API key login
        └── (dashboard)/             Protected route group
            ├── layout.tsx           Sidebar + topbar + auth guard
            ├── page.tsx             Dashboard (status, stats, chart, recent)
            ├── actions/
            │   ├── page.tsx         Filterable list with pagination + Export CSV button
            │   └── [id]/page.tsx    Detail view with JSON viewer
            ├── verification/
            │   └── page.tsx         Chain integrity + checkpoint management + Download Report button
            ├── agents/
            │   ├── page.tsx         Agent list
            │   └── [id]/page.tsx    Agent detail + filtered actions
            └── settings/
                └── page.tsx         Org info + API key CRUD (admin only)
```

---

## Architecture

```
Frontend (Next.js 16)                SDK (Python)
  8 pages: Dashboard, Actions,        @audit / @async_audit decorators
  Verification, Agents, Settings       LangChain | OpenAI | CrewAI integrations
       |                                    |
       | HTTP (Bearer token)                v
       |                              ActionLedgerClient / AsyncClient
       |                              - Retry with exponential backoff
       |                              - Background queue + batch flush
       |                                    |
       +----------+  HTTP(S)  +-------------+
                  |            |
                  v            v
           API (FastAPI)
             Rate Limiter (sliding window, per API key)
                  |
             Auth (API Key + RBAC: read/write/admin)
                  |
             Routes: /v1/actions, /v1/verify, /v1/agents,
                     /v1/organizations, /v1/api-keys, /v1/export
                  |
                  v
           Services
             Chain Builder          Hashing (SHA-256)       Verification
             - Per-org asyncio      - Canonical JSON        - 500-record chunks
               locks                - HASHABLE_FIELDS       - Detects hash +
             - SELECT FOR UPDATE      (single source          chain link breaks
               (cross-process)        of truth)
                                    - Timezone normalized

             KMS (Local/AWS)        Checkpoint + Merkle     Immutability
             - HMAC-SHA256          - Signed snapshots      - PL/pgSQL triggers
             - AWS generate_mac     - Merkle root             (PostgreSQL)
                                    - External proof        - BEFORE UPDATE/DELETE
                                      publish                 (SQLite)
                  |                        |
                  v                        v
           PostgreSQL               External Store
           + Append-only triggers   S3 WORM (Object Lock)
           + Chain state locking    or Local JSON Lines file
```

### Key design decisions

| Decision | Why |
|----------|-----|
| All data pages are client components (`"use client"`) | API key is in localStorage — can't use Next.js server components for data fetching |
| No BFF / no Next.js API routes | Frontend calls backend directly. CORS is configured for `localhost:3000` |
| Per-org asyncio locks + PostgreSQL `SELECT FOR UPDATE` | In-process lock handles async concurrency; DB lock handles multi-process |
| SQLite for dev, PostgreSQL for prod | SQLite has no row-level locking (single-instance only). PostgreSQL is required for production |
| `HASHABLE_FIELDS` tuple as single source of truth | Both chain building and verification use the same field list — can't drift |
| Streaming verification (500-record chunks) | Prevents OOM on large chains. Uses `session.expire_all()` between chunks |

---

## Roadmap

**Step 2 of 6 complete. Pre-deploy fixes shipped. Next: Deploy to AWS.**

| Step | What | Status | Effort |
|------|------|--------|--------|
| 1 | Frontend Dashboard | **Done** | -- |
| 2 | PDF/CSV Export | **Done** | -- |
| 3 | Deploy to AWS | **Next** | Large |
| 4 | Webhook/Alerting | Planned | Medium |
| 5 | Enterprise Hardening | Planned | Large |
| 6 | Scale & Multi-tenant | Future | XL |

<details>
<summary><strong>Step 2 — PDF/CSV Export (Done)</strong></summary>

Regulators cannot accept "call our API" as evidence. Downloadable audit reports are required by EU AI Act Art. 11, SEC Rule 17a-4, and Colorado AI Act.

**What was built:**
- `GET /v1/export/csv` — streams a CSV of action records (27 columns, 500-record chunks, up to 10,000 records), requires `read` permission
- `GET /v1/export/pdf` — generates a PDF compliance report (chain integrity status, checkpoints table, action records table, max 5,000 records), requires `read` permission
- "Export CSV" button on the Actions page (respects current filters)
- "Download Report" button on the Verification page (PDF)

Both endpoints accept the same filters: `start_date`, `end_date`, `agent_name`, `action_type`, `result`.

**Regulatory driver:** EU AI Act Art. 11/Annex IV (technical documentation), SEC Rule 17a-4 (accessible records), Colorado (impact assessments).
</details>

<details>
<summary><strong>Step 3 — Deploy to AWS</strong></summary>

**What to build:**
- RDS PostgreSQL (replaces SQLite)
- ECS Fargate or EC2 with ALB + TLS (ACM)
- Frontend on S3 + CloudFront (or Vercel)
- Real env vars: `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`

**Optional (adds immutability guarantees):**
- AWS KMS HMAC key (`ACTIONLEDGER_KMS_PROVIDER=aws`)
- S3 bucket with Object Lock (`ACTIONLEDGER_EXTERNAL_STORE=s3`)
- Both are already coded but need a real AWS account to test

**Regulatory driver:** EU AI Act Art. 19 requires 6-month log retention with proper infrastructure.
</details>

<details>
<summary><strong>Step 4 — Webhook/Alerting on Chain Break</strong></summary>

**What to build:**
- `POST /v1/webhooks` — register URLs for alerts
- On chain verification failure → POST to registered webhooks
- Optional Slack/email integration

**Regulatory driver:** EU AI Act Art. 26 (deployers must "immediately inform" on risk), FINRA supervision rules.
</details>

<details>
<summary><strong>Step 5 — Enterprise Hardening</strong></summary>

- API key expiration + rotation ✅ shipped (keys now support `expires_at`)
- Structured logging with correlation IDs (needed for SOC 2)
- Redis rate limiter (current in-memory doesn't work across instances)
- Configurable per-org retention policies (balance EU AI Act Art. 19 with GDPR deletion)
- OpenAI streaming support (buffer chunks, record complete response)
- Anthropic/Claude SDK integration
</details>

<details>
<summary><strong>Step 6 — Scale</strong></summary>

- Multi-tenant admin panel
- Terraform/CDK deployment templates
- SOC 2 compliance documentation
- Impact assessment templates (Colorado AI Act, ISO 42001)
- Bias/fairness metrics dashboard (NYC LL 144, Colorado)
</details>

---

## Regulatory Compliance

Vera targets the emerging AI compliance landscape. This section maps exactly what we cover and what we don't.

<details>
<summary><strong>Regulations tracked</strong></summary>

| Regulation | Status | Binding? | Key Deadline |
|---|---|---|---|
| **EU AI Act** (Regulation 2024/1689) | Phased enforcement (Feb 2025 -- Aug 2027) | Yes | Art. 12 logging: **Aug 2, 2026** |
| **Colorado AI Act** (SB 24-205) | Signed into law | Yes | **June 30, 2026** |
| **NYC Local Law 144** (AEDTs) | In force since July 2023 | Yes | Active now |
| **FINRA 2026 Oversight Report** | Published Dec 2025 | Yes (broker-dealers) | Ongoing |
| **SEC Rule 17a-4** | In force | Yes (financial services) | Ongoing |
| **NIST AI RMF 1.0** (AI 100-1) | Published Jan 2023 | No (voluntary) | Provides safe harbor in TX/CA |
| **ISO/IEC 42001:2023** | Published Dec 2023 | No (certification) | Provides safe harbor in TX/CA |
</details>

<details>
<summary><strong>What we cover</strong></summary>

| Requirement | Regulation | How Vera Satisfies It |
|---|---|---|
| **Automatic event logging** | EU AI Act Art. 12 | Core product. Every action cryptographically chained with full context |
| **Log retention (min 6 months)** | EU AI Act Art. 19/26 | Append-only with triggers blocking DELETE. S3 WORM configurable retention |
| **Tamper detection** | EU AI Act Art. 12, ISO 42001 A.6.2.8 | Four independent immutability layers |
| **Model version tracking** | FINRA 2026 Report | `model_id`, `model_version`, `framework`, `framework_version` per record |
| **Prompt and output logging** | FINRA 2026 Report | `input_data` and `outcome` fields capture full I/O |
| **Record retention 3-6 years** | SEC Rule 17a-4 | Records physically cannot be deleted |
| **Monitoring of AI operation** | EU AI Act Art. 26(5) | Chain verification API enables continuous monitoring |
| **Per-action accountability** | Colorado AI Act, NIST AI RMF | `agent_name`, `authorized_by`, `delegation_chain`, `reasoning` per record |
| **Bias audit data availability** | NYC LL 144, Colorado | Historical data queryable by date range, agent, type |
| **Data subject access / right to explanation** | EU AI Act Art. 86, GDPR, Colorado AI Act | `data_subject_id` field enables querying all decisions for a specific individual |
</details>

<details>
<summary><strong>What we don't cover (gaps)</strong></summary>

| Requirement | Regulation | Gap | Priority |
|---|---|---|---|
| Alerting on tampering | EU AI Act Art. 26, FINRA | No webhooks/notifications | P0 (Step 4) |
| Impact assessment templates | Colorado AI Act, ISO 42001 | Not generated or stored | P1 |
| Training data provenance | ISO 42001 A.8.5, EU AI Act Annex IV | Logs actions, not training data lineage | P2 |
| Bias/fairness metrics | NYC LL 144, Colorado | Data exists, analysis layer doesn't | P2 |
| Configurable retention | GDPR vs EU AI Act | Data stays forever, may conflict with GDPR | P2 |
</details>

<details>
<summary><strong>Penalties for non-compliance</strong></summary>

| Regulation | Maximum Fine |
|---|---|
| **EU AI Act** — prohibited practices | EUR 35M or **7% global turnover** |
| **EU AI Act** — other violations (incl. Art. 12 logging) | EUR 15M or **3% global turnover** |
| **Colorado AI Act** | **$20,000 per violation per consumer** |
| **NYC LL 144** | $500 first; $500-$1,500/day subsequent |
| **SEC/FINRA** | Fines, suspensions, disgorgement |
| **GDPR** (if logs contain personal data) | EUR 20M or **4% global turnover** |
</details>

---

## Known Issues & Limitations

### Open issues (3)

| # | Severity | Issue |
|---|----------|-------|
| 1 | MEDIUM | `init.sql` and `alembic/` define the PostgreSQL schema separately — they can drift |
| 2 | MEDIUM | No tests for S3 external store verification logic |
| 3 | MEDIUM | Checkpoint creation doesn't acquire org lock — small race condition window with concurrent inserts |

### Limitations (by design)

| Limitation | Why | Workaround |
|------------|-----|------------|
| SQLite not safe for multiple instances | No row-level locking; in-process asyncio locks don't cross processes | Use PostgreSQL for production |
| `@audit` is sync-only | Separate decorator for async functions | Use `@async_audit` for async |
| Framework integration versions loosely pinned | `langchain-core>=0.1.0`, `crewai>=0.1.0` may break with newer versions | Pin to tested versions |
| Rate limiter is in-memory | Doesn't work across multiple instances | Swap to Redis-backed store |
| `repr()` used for function inputs | Could expose PII in audit logs | Override with custom serializer |
| AWS KMS not tested in CI | Requires real AWS credentials | Mock-based tests needed |

---

## Changelog

**21 bugs + 3 pre-deploy fixes across 5 rounds. 3 open issues remain.**

<details>
<summary><strong>Audit 1 — 7 bugs fixed</strong> (SDK, validation, S3 config)</summary>

| Bug | Fix | File |
|-----|-----|------|
| OpenAI streaming silently ignored | Logs warning, passes through unaudited | `sdk/integrations/openai.py` |
| S3 WORM didn't validate bucket config | Init calls `get_object_lock_configuration`, raises on missing | `services/external_store.py` |
| Async queue unbounded growth | `max_queue_size=10000`, drops oldest with warning | `sdk/async_client.py` |
| No async queue shutdown guarantee | `atexit` handler warns if unflushed items remain | `sdk/async_client.py` |
| S3 retention hardcoded to 365 days | Configurable via `ACTIONLEDGER_S3_RETENTION_DAYS` | `services/external_store.py` |
| Timestamps not validated | Rejects before 2020 and >24h future | `schemas/action.py` |
| Organization name unlimited | `min_length=1, max_length=500` | `schemas/organization.py` |
</details>

<details>
<summary><strong>Audit 2 — 9 bugs fixed</strong> (security, schema mismatches, error handling)</summary>

| # | Severity | Fix | File |
|---|----------|-----|------|
| 1 | HIGH | Null check + 404 on `GET /organizations/me` | `routes/organizations.py` |
| 2 | HIGH | `scalar_one_or_none()` + 404 guard for missing ChainState | `services/chain.py`, `services/checkpoint.py` |
| 3 | MEDIUM | Added 8 missing fields to `ActionRecordResponse` | `schemas/action.py` |
| 4 | MEDIUM | Added `merkle_root` to checkpoint schemas | `schemas/checkpoint.py` |
| 5 | MEDIUM | CORS whitelists specific methods/headers only | `main.py` |
| 6 | MEDIUM | LocalKMS raises in production without dedicated signing key | `services/kms.py` |
| 7 | MEDIUM | External store failures log exception + context | `services/checkpoint.py` |
| 8 | LOW | Frontend types match all backend response fields | `frontend/lib/api-types.ts` |
| 9 | LOW | JSON parse catch returns meaningful error | `frontend/lib/api-client.ts` |
</details>

<details>
<summary><strong>Audit 3 — 4 bugs fixed</strong> (response mapping, schema completeness, validation)</summary>

| # | Severity | Fix | File |
|---|----------|-----|------|
| 1 | HIGH | `_record_to_response()` now maps all 30 fields (was missing 7) | `routes/actions.py` |
| 2 | MEDIUM | Added `key_id` to `CheckpointResponse` | `schemas/checkpoint.py` |
| 3 | MEDIUM | Added `authorized_by` to frontend `ActionQueryParams` | `frontend/lib/api-types.ts` |
| 4 | LOW | Added `offset >= 0` validation | `routes/actions.py` |
</details>

<details>
<summary><strong>Audit 4 — 1 critical fix</strong> (hash chain integrity)</summary>

| # | Severity | Fix | File |
|---|----------|-----|------|
| 1 | CRITICAL | `HASHABLE_FIELDS` was missing 7 fields (model_version, framework, framework_version, delegation_chain, policies_applied, environment, metadata_) — these could be tampered without breaking chain verification. All record fields now included in hash. | `services/hashing.py`, `tests/test_hashing.py` |
</details>

<details>
<summary><strong>Pre-deploy fixes — 3 product gaps closed</strong> (agents, data subject, key expiry)</summary>

| # | Severity | Fix | Files |
|---|----------|-----|-------|
| 1 | HIGH | **Agent auto-registration** — agents were only created via explicit `POST /v1/agents`, so the Agents page showed 0 even while actions were being recorded. Now `_get_or_create_agent()` runs inside the per-org lock on every action write; agent + record land in the same transaction. IntegrityError catch handles PostgreSQL multi-process races. | `services/chain.py` |
| 2 | HIGH | **`data_subject_id` field** — EU AI Act Art. 86, Colorado AI Act, and GDPR all require finding every decision made about a specific person. Added to model, schema, HASHABLE_FIELDS (safe: null excluded from canonical JSON so existing hashes stay valid), query filter, CSV export column, and frontend filter bar. Alembic migration included. | `models/action_record.py`, `schemas/action.py`, `services/hashing.py`, `routes/actions.py`, `services/export.py`, `frontend/lib/api-types.ts`, `frontend/app/(dashboard)/actions/page.tsx` |
| 3 | MEDIUM | **API key expiration** — keys lived forever, blocking SOC 2 and ISO 27001 reviews. `expires_at` field added to `ApiKey` model; `is_active` property now returns `False` for expired keys; create endpoint accepts optional `expires_at` datetime; Settings page shows Expires column and date picker on key creation. Alembic migration included. | `models/api_key.py`, `schemas/api_key.py`, `services/auth.py`, `routes/api_keys.py`, `frontend/app/(dashboard)/settings/page.tsx` |
</details>

---

## Current State

**Everything runs locally. Nothing is deployed. No AWS account connected.**

| Component | Current | Production Target |
|-----------|---------|-------------------|
| Backend | `localhost:8000` (uvicorn) | ECS Fargate behind ALB with TLS |
| Database | SQLite file | RDS PostgreSQL (encrypted, Multi-AZ) |
| KMS | Local HMAC-SHA256 | AWS KMS hardware-backed |
| External store | Local JSON Lines file | S3 with Object Lock (WORM) |
| Frontend | `localhost:3000` (Next.js dev) | S3 + CloudFront or Vercel |
| CI/CD | None | GitHub Actions |
| Domain/TLS | None | ACM + Route 53 |

---

## License

Proprietary. All rights reserved.
