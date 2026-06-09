# ScribeMD — Backend

The customer-facing backend for the ScribeMD demo (Use Case 1). Wraps the
Week 1 `run_encounter` workflow as an HTTP/SSE service so a browser-side
frontend can drive the AI-scribe pipeline live on a screenshare.

This service holds **operational state only** — the encounter row, lifecycle
status, captured event stream for SSE replay. Vera holds the audit truth
(every recorded action, every approval decision, every chart commit lives
on Vera's cryptographic chain).

```
Browser  ─HTTP/SSE─►  ScribeMD backend  ─SDK─►  Vera production
                          │
                          ▼
                    SQLite (operational
                     state only)
```

## Running locally

```bash
# from repo root
pip install -r simulator/customers/scribemd/backend/requirements.txt
pip install -e sdk
pip install -e simulator

# env vars (or set them inline)
export SCRIBEMD_PASSKEY=demo-passkey-change-me
export VERA_API_URL=https://api.usevera.xyz
export VERA_API_KEY_SCRIBEMD=al_live_...    # from `bootstrap_orgs.py`
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn simulator.customers.scribemd.backend.main:app --reload --port 8001
```

The frontend dev server runs on `http://localhost:3001`. CORS is configured
to allow that origin by default.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SCRIBEMD_PASSKEY` | `demo-passkey-change-me` | Single passkey shared by every demo session. |
| `SCRIBEMD_USER_LABEL` | `Dr. Adams` | What `/api/auth/me` returns once signed in. |
| `SCRIBEMD_DB_URL` | `sqlite+aiosqlite:///./scribemd_backend.db` | Operational-state DB. |
| `SCRIBEMD_APPROVAL_TIMEOUT_SECONDS` | `300` | Soft cap on physician HITL wait. After this, the workflow auto-rejects so it doesn't block forever. |
| `VERA_API_URL` | `https://api.usevera.xyz` | Vera target. Override for local Vera dev. |
| `VERA_API_KEY_SCRIBEMD` | — | API key for the ScribeMD org. Bootstrap with `python -m simulator.scripts.bootstrap_orgs`. |
| `OPENAI_API_KEY` | — | For the note-drafting agent. |
| `ANTHROPIC_API_KEY` | — | For the orders-extraction agent. |
| `CORS_ORIGINS` | `http://localhost:3001,http://127.0.0.1:3001` | Comma-separated. |

## Tests

```bash
python -m pytest simulator/customers/scribemd/backend/tests/ -v
```

The smoke test stubs out Vera + LLMs so it runs hermetically — no API keys
needed. It exercises the full happy path (login → create encounter → SSE
stream → physician approve → terminal commit) and the reject path.

## API surface

See `contract.md` for the precise request/response/SSE shapes. The frontend
codes against that document.

## How the threading works

The Week 1 `run_encounter` is **synchronous** — it makes blocking HTTP calls
to Vera and the LLM providers. The backend wraps it as follows:

1. `start_workflow` resolves the fixture/custom encounter into a fixture
   object on the event-loop side, persists `patient_summary` immediately so
   a refresh-while-running has something to show.
2. `_run_workflow` runs the actual workflow inside `asyncio.to_thread(...)`
   so the event loop stays responsive while the worker thread blocks on
   Vera/OpenAI/Anthropic.
3. `on_step` callbacks fire from the worker thread. Each one:
   - calls `loop.call_soon_threadsafe(bus.publish, ...)` to fan out on the
     in-process pub/sub bus
   - schedules `_persist_event(...)` via `asyncio.run_coroutine_threadsafe`
     so the event lands in the encounter's `events` JSON column for SSE
     replay
4. The HITL gate uses a `threading.Event` per pending approval. The worker
   thread blocks on `event.wait(timeout=...)`. The HTTP route handler for
   `POST /api/approvals/{id}/decide` looks up the pending entry, captures
   the decision, and `event.set()`s. The worker wakes, hands the decision
   back to the workflow's `physician_callback`, the workflow calls Vera's
   `/v1/approvals/{id}/decide`, and continues to terminal state.

## File map

| File | Purpose |
|---|---|
| `main.py` | FastAPI factory, lifespan, CORS, router mount, `/api/health`. |
| `config.py` | Settings dataclass — env-var driven, freshly read each request. |
| `auth.py` | Constant-time passkey check, opaque session tokens, in-memory store, `require_session` FastAPI dependency. |
| `db.py` | Async SQLAlchemy engine + session factory; lazy init so tests can swap the DB URL. |
| `models.py` | The `Encounter` row — operational state only, no audit data. |
| `schemas.py` | Pydantic request/response models. |
| `events.py` | In-memory pub/sub for SSE fan-out, with replay-safe `is_closed` semantics. |
| `workflow_runner.py` | The thread bridge described above. Test factories live here for stubbing Vera + LLMs. |
| `routes/auth.py` | `POST /login`, `POST /logout`, `GET /me`. |
| `routes/encounters.py` | `POST /api/encounters`, `GET /api/encounters[/id]`. |
| `routes/approvals.py` | `POST /api/approvals/{id}/decide`. |
| `routes/events.py` | `GET /api/events/{id}` SSE stream with replay. |
| `tests/test_smoke.py` | End-to-end test with stubbed Vera + LLMs. |

## Limitations (by design)

- **Single-process only.** The session store and the event bus live in
  process memory. Don't run more than one uvicorn worker.
- **No CSRF.** The cookie is `samesite=lax`. Acceptable for a demo on
  `localhost`; harden before exposing to the internet.
- **No retention.** SQLite grows forever — wipe the file between long demo
  runs if you want a clean dashboard.
- **Soft approval timeout.** If nobody decides within
  `SCRIBEMD_APPROVAL_TIMEOUT_SECONDS`, the worker auto-rejects so the
  workflow can't block forever. The blocked path is part of the demo
  anyway, but bump the timeout if you're narrating slowly.
