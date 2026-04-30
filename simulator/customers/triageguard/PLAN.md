# TriageGuard customer-level infra — plan (4D)

Mirrors ScribeMD's customer-level orchestration for the second mock customer
(UC-3: AI triage / symptom checker for telehealth).

## 1. Architecture

```
   ┌───────────────┐   HTTP / SSE   ┌────────────────┐   SDK    ┌──────────────┐
   │   Browser     │  ────────────► │ TriageGuard    │ ───────► │ Vera         │
   │ (Next.js,     │                │ backend        │          │ production   │
   │  port 3002)   │  ◄──────────── │ (FastAPI 8002) │ ◄─────── │ usevera.xyz  │
   └───────────────┘                └────────┬───────┘          └──────────────┘
                                             ▼
                                      SQLite (operational state)
```

No Vera service in compose. No DB service — SQLite is bundled in the backend
container at `/app/triageguard_backend.db`.

## 2. docker-compose service specs

`triageguard-backend`:
- build context `../../..`, dockerfile `simulator/customers/triageguard/Dockerfile.backend`
- `working_dir /app`
- `uvicorn simulator.customers.triageguard.backend.main:app --host 0.0.0.0 --port 8002 --reload`
- ports `8002:8002`; bind mount `../../..:/app`
- `env_file .env.local`; `environment: PYTHONPATH=/app:/app/sdk`
- healthcheck `curl -f http://localhost:8002/api/health` every 5s
- network `triageguard-net`

`triageguard-frontend`:
- build context `../../..`, dockerfile `simulator/customers/triageguard/Dockerfile.frontend`
- `npm run dev`; ports `3002:3002`
- volumes `./frontend:/app` plus anonymous `/app/node_modules`
- `env_file .env.local`; `environment: NODE_ENV=development`
- `depends_on: triageguard-backend (service_healthy)`
- network `triageguard-net`

Single bridge network `triageguard-net`.

## 3. Dockerfile.backend

`python:3.12-slim`. Installs `curl` (healthcheck) + pip-installs
`backend/requirements.txt` plus shared deps (openai, anthropic, dotenv, faker,
rich). Bakes `PYTHONPATH=/app:/app/sdk`. No source COPY — the bind mount
provides editable-style reload.

## 4. Dockerfile.frontend

`node:22-slim`. Copies `frontend/package.json` + `package-lock.json`, runs
`npm ci`. `EXPOSE 3002`. No source COPY — compose bind-mounts `./frontend:/app`
with an anonymous `/app/node_modules`.

## 5. Makefile targets (POSIX)

- `help` — list targets (default).
- `bootstrap` — `python -m simulator.scripts.bootstrap_orgs --only triageguard --policies`.
- `up` — `docker compose up --build` foreground.
- `up-detached` — `docker compose up -d --build`.
- `down` — `docker compose down`.
- `logs` — tail compose logs.
- `test` — pytest `simulator/customers/triageguard/backend/tests/`.
- `clean` — `down -v` + drop `triageguard_backend.db`.
- `demo` — `bootstrap up`.

## 6. `.env.example` env vars

- Auth: `TRIAGEGUARD_PASSKEY`, `TRIAGEGUARD_USER_LABEL` ("Nurse Rivera, RN").
- Vera: `VERA_API_URL`, `VERA_API_KEY_TRIAGEGUARD`.
- LLMs: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- Frontend → backend: `NEXT_PUBLIC_TRIAGEGUARD_API_URL`.
- Backend tunables: `TRIAGEGUARD_DB_URL`, `TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS`, `CORS_ORIGINS`.

Top-of-file: copy to `.env.local`, never commit real keys.

## 7. README sections

1. What is this — second mock customer; UC-3; ICP examples.
2. Architecture — ASCII diagram.
3. Prerequisites — Docker, OpenAI, Anthropic, `make bootstrap`.
4. First-time setup.
5. Daily use.
6. Demo script — red-flag → escalation → audit.
7. What's next — `simulator/README.md`.
8. Troubleshooting — API key, CORS, SSE, rate limit.

## 8. Demo script beats

1. Frame: "AI triage says self-care looks fine — until it isn't."
2. Run: paste chest-pain symptom set; AI returns *self-care*.
3. Catch: red-flag detector trips; Vera routes to Nurse Rivera; she
   escalates to ER.
4. Audit: every step on Vera's chain. Patient never saw the unsafe call.

## 9. Differences from ScribeMD

| Knob | ScribeMD | TriageGuard |
|---|---|---|
| Backend port | 8001 | 8002 |
| Frontend port | 3001 | 3002 |
| DB file | `scribemd_backend.db` | `triageguard_backend.db` |
| Persona | Dr. Adams | Nurse Rivera, RN |
| Cookie | `scribemd_session` | `triageguard_session` |
| Env prefix | `SCRIBEMD_*` | `TRIAGEGUARD_*` |
| HITL var | `..._APPROVAL_TIMEOUT_SECONDS` | `..._REVIEW_TIMEOUT_SECONDS` |
| Network | `scribemd-net` | `triageguard-net` |
| Slug | `scribemd` | `triageguard` |

## 10. What's NOT mine

The compose file references siblings that arrive in PRs 4A and 4B:

- 4A — `backend/` (FastAPI app, `requirements.txt`, policies, fixtures).
- 4B — `frontend/` (Next.js, `package.json`, `package-lock.json`).

`docker compose config` validates YAML + interpolation only, so it passes
today. `docker compose build` and `make demo` work end-to-end after 4A and
4B merge.
