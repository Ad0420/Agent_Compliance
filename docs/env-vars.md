# Environment Variable Registry

This document lists every environment variable the Vera system depends on,
which service consumes it, where it gets set, and whether it's required.

**Whenever you add or change a required env var, update this file as part of
the PR that introduces the change.** The `Deploy considerations` checklist
in our PR template references this doc.

---

## Backend (FastAPI, deployed to Railway)

Env vars are set in Railway's project environment settings. Local development
uses `backend/.env` (gitignored) seeded from `backend/.env.example`.

The pydantic `Settings` class in `backend/app/config.py` is the source of
truth for backend env vars. Fields without a default raise at startup if
unset; fields with a default are optional. Additional env vars are read
directly via `os.environ` inside `backend/app/services/{kms,external_store}.py`
for the tamper-evident archive subsystem.

### Core

| Variable | Required | Description | Set in |
|---|---|---|---|
| `DATABASE_URL` | yes in prod | Postgres connection string. Defaults to local SQLite for dev. Bare `postgresql://` URLs are auto-rewritten to `postgresql+asyncpg://`. | Railway |
| `SECRET_KEY` | yes in prod | Random secret. App refuses to start in non-`development` environments if left at the default. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. | Railway |
| `ENVIRONMENT` | yes in prod | Set to `production` on Railway. Any value other than `development` enforces `SECRET_KEY`. | Railway |
| `CORS_ORIGINS` | yes in prod | Comma-separated list of allowed frontend origins (e.g. `https://usevera.xyz,https://www.usevera.xyz`). Defaults to `http://localhost:3000`. | Railway |

### Tunables (all optional, defaults shown)

| Variable | Default | Description | Set in |
|---|---|---|---|
| `API_KEY_PREFIX` | `al_live_` | Prefix for generated API keys | Railway |
| `MAX_BATCH_SIZE` | `100` | Max records per batch ingest | Railway |
| `MAX_JSON_FIELD_SIZE` | `1000000` | Max bytes for serialized JSON blob fields | Railway |
| `MAX_SEARCH_LENGTH` | `200` | Max search query length | Railway |
| `RATE_LIMIT_RPM` | `120` | Per-key requests per minute | Railway |
| `RATE_LIMIT_BURST` | `20` | Per-key max burst per second | Railway |
| `RATE_LIMIT_ENABLED` | `true` | Enables the in-process limiter. Set `false` when AWS WAF rate rules are authoritative. | Railway/AWS |
| `RATE_LIMIT_TRUST_PROXY_HEADERS` | `false` | Trusts `X-Forwarded-For` for IP buckets. Use only behind a trusted ALB/proxy. | AWS |
| `DB_POOL_SIZE` | `5` | SQLAlchemy pool size per process/worker. Use small values for small RDS instances. | Railway/AWS |
| `DB_MAX_OVERFLOW` | `5` | Extra transient DB connections per process/worker. | Railway/AWS |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a DB connection before failing. | Railway/AWS |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Recycle pooled DB connections after this many seconds. | Railway/AWS |
| `ALERT_FROM_EMAIL` | `alerts@usevera.xyz` | `From` address for alert emails | Railway |

### Durable jobs (SQS + ECS worker)

| Variable | Required | Description | Set in |
|---|---|---|---|
| `ACTIONLEDGER_JOB_QUEUE_PROVIDER` | no (defaults to `local`) | `local` schedules in-process asyncio tasks; `sqs` writes jobs to SQS for `python -m app.worker`. Use `sqs` in AWS production. | AWS |
| `ACTIONLEDGER_SQS_QUEUE_URL` | yes if provider is `sqs` | SQS queue URL used for webhook delivery, email alerts, checkpoint jobs, and async PDF exports. | AWS |

### S3 documents and exports

| Variable | Required | Description | Set in |
|---|---|---|---|
| `ACTIONLEDGER_BAA_BUCKET` | yes for BAA file upload | Private S3 bucket for signed BAA PDFs. Use SSE-KMS and block public access. | AWS |
| `ACTIONLEDGER_BAA_PREFIX` | no (defaults to `baa/`) | Prefix for signed BAA PDFs. | AWS |
| `ACTIONLEDGER_BAA_KMS_KEY_ID` | no | Optional KMS key id/ARN for explicit per-object SSE-KMS headers. | AWS |
| `ACTIONLEDGER_BAA_UPLOAD_MAX_BYTES` | no (defaults to `10000000`) | Max accepted PDF size for the BAA upload endpoint. | AWS |
| `ACTIONLEDGER_EXPORT_BUCKET` | yes for async PDF exports | Private S3 bucket for generated export artifacts. Use SSE-KMS and block public access. | AWS |
| `ACTIONLEDGER_EXPORT_PREFIX` | no (defaults to `exports/`) | Prefix for generated export artifacts. | AWS |
| `ACTIONLEDGER_EXPORT_KMS_KEY_ID` | no | Optional KMS key id/ARN for explicit per-object SSE-KMS headers. | AWS |

### Email alerts (Resend)

| Variable | Required | Description | Set in |
|---|---|---|---|
| `RESEND_API_KEY` | yes if alerting is on | Resend API key. Defaults to empty string; email alerts no-op when unset. | Railway |

### Clerk auth (dashboard routes only — SDK uses API keys)

| Variable | Required | Description | Set in |
|---|---|---|---|
| `CLERK_JWKS_URL` | yes for dashboard auth | Clerk JWKS endpoint, e.g. `https://<instance>.clerk.accounts.dev/.well-known/jwks.json`. Without it, `/v1/dashboard/*` returns 503. | Railway |
| `CLERK_ISSUER` | yes if `CLERK_JWKS_URL` set | Expected JWT `iss` claim. App refuses to start if `CLERK_JWKS_URL` is set without `CLERK_ISSUER` (prevents accepting JWTs signed by any Clerk instance with a matching `kid`). | Railway |
| `CLERK_AUDIENCE` | no | Optional `aud` claim check. Only set if a custom JWT template is configured. | Railway |
| `CLERK_AUTHORIZED_PARTIES` | no | Comma-separated allowlist of `azp` claim values (frontend origins). Rejects tokens issued to a different Clerk app on the same instance. | Railway |

### Tamper-evident archive (KMS + external WORM store)

These are read directly via `os.environ` in `backend/app/services/kms.py`
and `backend/app/services/external_store.py`, not via the pydantic Settings
class. They're only required if the corresponding subsystem is enabled.

| Variable | Required | Description | Set in |
|---|---|---|---|
| `AWS_KMS_KEY_ID` | yes if KMS signer is used | KMS key alias or ARN for checkpoint signing. | Railway |
| `AWS_REGION` | no (defaults to `us-east-1`) | AWS region for KMS and S3. | Railway |
| `AWS_ACCESS_KEY_ID` | yes if KMS / S3 used outside AWS | Standard AWS credential. In ECS, prefer the task role instead of static keys. | Railway |
| `AWS_SECRET_ACCESS_KEY` | yes if KMS / S3 used outside AWS | Paired with above. In ECS, prefer the task role instead of static keys. | Railway |
| `ACTIONLEDGER_EXTERNAL_STORE` | no (defaults to `local`) | Selects external WORM store provider. Set to `s3` to enable the S3 backend. | Railway |
| `ACTIONLEDGER_S3_BUCKET` | yes if `ACTIONLEDGER_EXTERNAL_STORE=s3` | S3 bucket name. Must have Object Lock enabled. | Railway |
| `ACTIONLEDGER_S3_PREFIX` | no (defaults to `checkpoints/`) | Key prefix within the bucket. | Railway |
| `ACTIONLEDGER_S3_RETENTION_DAYS` | no (defaults to `365`) | Object Lock retention window in days. | Railway |

## Frontend (Next.js, deployed to Vercel)

Env vars are set in Vercel's project environment settings (Production +
Preview + Development tabs). Local development uses `frontend/.env.local`
(gitignored) seeded from `frontend/.env.example`.

CI guard: `frontend/scripts/check-env.mjs` (exposed as `npm run check:env`)
fails fast if any `REQUIRED_KEYS` entry is missing or contains a placeholder
marker (`placeholder`, `pk_test_...`, `sk_test_...`, `replace_before_deploy`).
Wire this into the Vercel `buildCommand` (`node scripts/check-env.mjs && next
build`) so missing or stub Clerk keys block the deploy.

| Variable | Required | Description | Set in |
|---|---|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | yes | Clerk publishable key (client-safe). Enforced by `check-env.mjs`. | Vercel |
| `CLERK_SECRET_KEY` | yes | Clerk secret key (server-only). Enforced by `check-env.mjs`. | Vercel |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | no | Custom sign-in route. Defaults to `/login`. | Vercel |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | no | Custom sign-up route. Defaults to `/register`. | Vercel |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | no | Post-sign-in redirect. Defaults to `/home` (a stub that forwards to `/compliance` until PR 12 ships the real Home page). | Vercel |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` | no | Post-sign-up redirect. Defaults to `/home` (a stub that forwards to `/compliance` until PR 12 ships the real Home page). | Vercel |
| `NEXT_PUBLIC_API_URL` | yes in prod | Backend API base URL (e.g. `https://api.usevera.xyz`). Falls back to `http://localhost:8000` if unset, which is wrong for any deployed environment. | Vercel |

## SDK (`vera-sdk` on PyPI)

The SDK is a library, not a service. `VeraClient` and `AsyncVeraClient`
accept `api_url`, `api_key`, and `agent_name` as constructor arguments; the
SDK does not currently read env vars on its own. The variable names below
are the documented convention customers use in their own deploys to pass
those values into the constructor — for example:

```python
import os
from vera import VeraClient

client = VeraClient(
    api_url=os.environ.get("VERA_API_URL", "https://api.usevera.xyz"),
    api_key=os.environ["VERA_API_KEY"],
    agent_name=os.environ.get("VERA_AGENT_NAME", "default-agent"),
)
```

| Variable | Required | Description | Set in |
|---|---|---|---|
| `VERA_API_KEY` | yes | API key from the Vera dashboard. Passed to `VeraClient(api_key=...)`. | customer's runtime |
| `VERA_API_URL` | no | Backend URL. Defaults to `https://api.usevera.xyz`. | customer's runtime |
| `VERA_AGENT_NAME` | no | Agent identifier. Defaults to `default-agent`. | customer's runtime |

(If the SDK ever grows a built-in env-var fallback, update this section and
the docstring in `sdk/vera/client.py`.)

## Adding a new env var

1. Add the variable to the relevant `.env.example` file with a comment
   explaining what it's for.
2. Update this registry table.
3. If the new var is **required**, add it to the relevant CI guard:
   - Frontend → `frontend/scripts/check-env.mjs`'s `REQUIRED_KEYS`
   - Backend → `backend/app/config.py` (pydantic `Settings` — fields without
     a default raise at startup if unset, which is the desired behavior).
     For env vars read directly via `os.environ` outside `Settings` (e.g.
     the KMS / S3 archive), prefer adding them to `Settings` so the
     fail-fast behavior is uniform.
4. In the PR introducing the change, tick the "New required environment
   variables" box in the PR template and confirm the var is set in the
   production deploy environment **before merge**.

## When this doc is wrong

If you find a discrepancy between this doc and reality (an env var in code
that's not listed, a listed var that's no longer used), open a PR to fix
it. This doc is the source of truth that the PR template references.

Last reviewed: 2026-05-11
