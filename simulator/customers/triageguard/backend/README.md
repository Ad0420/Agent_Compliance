# TriageGuard — Backend

The customer-facing backend for the TriageGuard demo (Use Case 3 — AI
triage / symptom checker for telehealth). Wraps the Week-4 `run_session`
workflow as an HTTP/SSE service so a browser-side frontend can drive
the AI-triage pipeline live on a screenshare.

This service holds **operational state only** — the session row,
lifecycle status, captured event stream for SSE replay. Vera holds the
audit truth (every recorded action, every approval decision, every
routed/routing_blocked record lives on Vera's cryptographic chain).

```
Browser  ─HTTP/SSE─►  TriageGuard backend  ─SDK─►  Vera production
                          │
                          ▼
                    SQLite (operational
                     state only)
```

## Running locally

```bash
# from repo root
pip install -r simulator/customers/triageguard/backend/requirements.txt
pip install -e sdk
pip install -e simulator

# env vars (or set them inline)
export TRIAGEGUARD_PASSKEY=demo-passkey-change-me
export VERA_API_URL=https://api.usevera.xyz
export VERA_API_KEY_TRIAGEGUARD=al_live_...    # from `bootstrap_orgs.py`
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn simulator.customers.triageguard.backend.main:app --reload --port 8002
```

The frontend dev server runs on `http://localhost:3002`. CORS is
configured to allow that origin by default.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TRIAGEGUARD_PASSKEY` | `demo-passkey-change-me` | Single passkey shared by every demo session. |
| `TRIAGEGUARD_USER_LABEL` | `Nurse Rivera, RN` | What `/api/auth/me` returns once signed in. |
| `TRIAGEGUARD_DB_URL` | `sqlite+aiosqlite:///./triageguard_backend.db` | Operational-state DB. |
| `TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS` | `300` | Soft cap on nurse HITL wait. After this, the workflow auto-escalates so it doesn't block forever. |
| `VERA_API_URL` | `https://api.usevera.xyz` | Vera target. Override for local Vera dev. |
| `VERA_API_KEY_TRIAGEGUARD` | — | API key for the TriageGuard org. Bootstrap with `python -m simulator.scripts.bootstrap_orgs`. |
| `OPENAI_API_KEY` | — | For the triage classifier. |
| `ANTHROPIC_API_KEY` | — | For the red-flag detector. |
| `CORS_ORIGINS` | `http://localhost:3002,http://127.0.0.1:3002` | Comma-separated. |

## Tests

```bash
python -m pytest simulator/customers/triageguard/backend/tests/ -v
```

The smoke test stubs out Vera + LLMs so it runs hermetically — no API
keys needed. It exercises:

- The full nurse-confirm path (under-triaged + flagged → confirm → AI level used).
- The full nurse-escalate path (under-triaged + flagged → escalate → ER override).
- The auto-route path (clear self-care, no flag).
- SSE replay after terminal (anti-deadlock pattern).

## API surface

See `contract.md` for the precise request/response/SSE shapes. The
frontend codes against that document.

## How the threading works

The Week-4 `run_session` is **synchronous** — it makes blocking HTTP
calls to Vera and the LLM providers. The backend wraps it as follows
(verbatim mirror of ScribeMD's pattern):

1. `start_workflow` resolves the fixture/custom session into a
   `TriageFixture` on the event-loop side, persists `patient_summary`
   immediately so a refresh-while-running has something to show.
2. `_run_workflow` runs the actual workflow inside
   `asyncio.to_thread(...)` so the event loop stays responsive while
   the worker thread blocks on Vera/OpenAI/Anthropic.
3. `on_step` callbacks fire from the worker thread. Each one:
   - calls `loop.call_soon_threadsafe(bus.publish, ...)` to fan out on
     the in-process pub/sub bus
   - schedules `_persist_event(...)` via
     `asyncio.run_coroutine_threadsafe` so the event lands in the
     session's `events` JSON column for SSE replay
4. The HITL gate uses a `threading.Event` per pending approval. The
   worker thread blocks on `event.wait(timeout=...)`. The HTTP route
   handler for `POST /api/reviews/{id}/decide` looks up the pending
   entry, captures the decision, and `event.set()`s. The worker wakes,
   hands the decision back to the workflow's `nurse_callback`, the
   workflow calls Vera's `/v1/approvals/{id}/decide`, and continues to
   terminal state.

## File map

| File | Purpose |
|---|---|
| `main.py` | FastAPI factory, lifespan, CORS, router mount, `/api/health`. |
| `config.py` | Settings dataclass — env-var driven, freshly read each request. |
| `auth.py` | Constant-time passkey check, opaque session tokens, in-memory store, `require_session` FastAPI dependency. |
| `db.py` | Async SQLAlchemy engine + session factory; lazy init so tests can swap the DB URL. |
| `models.py` | The `TriageSession` row — operational state only, no audit data. |
| `schemas.py` | Pydantic request/response models. |
| `events.py` | In-memory pub/sub for SSE fan-out, with replay-safe `is_closed` semantics. |
| `workflow_runner.py` | The thread bridge described above. Test factories live here for stubbing Vera + LLMs. |
| `routes/auth.py` | `POST /login`, `POST /logout`, `GET /me`. |
| `routes/sessions.py` | `POST /api/sessions`, `GET /api/sessions[/id]`. |
| `routes/reviews.py` | `POST /api/reviews/{id}/decide`. |
| `routes/events.py` | `GET /api/events/{id}` SSE stream with replay. |
| `tests/test_smoke.py` | End-to-end test with stubbed Vera + LLMs. |

## Limitations (by design)

- **Single-process only.** The session store and the event bus live in
  process memory. Don't run more than one uvicorn worker.
- **No CSRF.** The cookie is `samesite=lax`. Acceptable for a demo on
  `localhost`; harden before exposing to the internet.
- **No retention.** SQLite grows forever — wipe the file between long
  demo runs if you want a clean dashboard.
- **Soft review timeout.** If nobody decides within
  `TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS`, the worker auto-escalates to the
  red-flag detector's recommended override (or `urgent_care` if none)
  so the workflow can't block forever.
