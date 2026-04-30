# TriageGuard

The second mock customer in the Vera simulator's multi-tenant medtech bench.
A stand-in for an AI-driven telehealth front-door in the mould of K Health,
Teladoc, or Amwell: patient describes symptoms, an LLM classifies acuity,
a second LLM scans for red flags, an on-call nurse signs off on any
no-escalation call that touches a red flag. Every step lands on Vera's
audit chain — that's the point.

This directory is what a demoer opens. One command (`make demo`) brings up
a running stack pointed at Vera production.

## What is this?

TriageGuard is the customer-facing surface for use case 3 in `use_cases.md`.
It's a thin FastAPI/SSE backend wrapping the Week 2 triage workflow plus a
Next.js frontend that drives the pipeline through a browser. Vera holds the
audit truth; TriageGuard only keeps operational state (the encounter row,
the SSE replay buffer, a session token) in a local SQLite file.

ICP examples: K Health, Teladoc, Amwell, 98point6, MDLive — any platform
running an AI front-door for patient intake where a wrong "self-care" call
on a stroke or sepsis presentation is a malpractice event.

The simulator at large is documented at [`../../README.md`](../../README.md).

## Architecture

```
   ┌───────────────┐     HTTP / SSE      ┌────────────────┐     SDK      ┌──────────────┐
   │   Browser     │  ───────────────►   │ TriageGuard    │  ─────────►  │ Vera         │
   │ (Next.js,     │                     │ backend        │              │ production   │
   │  port 3002)   │  ◄───────────────   │ (FastAPI 8002) │  ◄─────────  │ usevera.xyz  │
   └───────────────┘                     └────────┬───────┘              └──────────────┘
                                                  │
                                                  ▼
                                         SQLite (operational
                                              state only)
```

Both services run as containers via `docker-compose.yml`. The browser hits
the backend on the host's `:8002` directly — no reverse proxy, no nginx.
The backend authenticates to Vera with an API key issued at bootstrap time.

## Prerequisites

- Docker Desktop (or Docker Engine 24+) with `docker compose`.
- An OpenAI API key. The triage classifier runs against `gpt-4o`-class
  models.
- An Anthropic API key. The red-flag detector runs against Claude.
- A Vera production URL (defaults to `https://api.usevera.xyz`).
- A one-time org bootstrap that registers TriageGuard on Vera and stashes
  the API key. The `make bootstrap` target handles this.

You do **not** need a local Vera. The chaos-mode local Vera under the repo
root is a separate concern.

## First-time setup

From this directory:

```bash
# 1. Configure env vars.
cp .env.example .env.local
$EDITOR .env.local
#    Fill in OPENAI_API_KEY and ANTHROPIC_API_KEY at minimum.
#    Leave VERA_API_KEY_TRIAGEGUARD as the placeholder for now — the next
#    step will overwrite it.

# 2. Register TriageGuard on Vera production (idempotent; safe to re-run).
make bootstrap
#    This calls POST /v1/register on Vera, installs TriageGuard's policies,
#    and writes VERA_API_KEY_TRIAGEGUARD to ../../.env.local
#    (i.e. simulator/.env.local). Copy that value into this directory's
#    .env.local so the docker-compose stack can read it:

grep VERA_API_KEY_TRIAGEGUARD ../../.env.local >> .env.local
$EDITOR .env.local   # de-duplicate if you re-ran bootstrap

# 3. Build and run.
make up
```

`make up` blocks in the foreground and streams logs from both containers.
Ctrl-C tears the stack down. First build takes ~2 minutes (Python wheels +
npm install). Subsequent builds reuse the layer cache.

When the backend logs `Application startup complete` and `npm` reports
`Ready in NNNms`, open `http://localhost:3002` in a browser.

## Daily use

```bash
make up
```

Then in the browser:

1. Sign in with the passkey from `.env.local`. The default is
   `qwertyuiop24072004`. The session lands as `triageguard_session` and
   `GET /api/auth/me` returns the persona ("Nurse Rivera, RN").
2. Pick a fixture symptom set from the dropdown, or paste a custom one. The
   fixtures live in `simulator/customers/triageguard/fixtures/symptoms.py`
   and cover routine, ambiguous, and red-flag-positive cases.
3. Click "Run triage". The pipeline streams progress over SSE — symptom
   classification → red-flag detection → policy check → HITL gate.
4. When the red-flag detector trips a no-escalation recommendation, an
   approval modal pops up. Approve (let the AI's call stand), escalate
   (override to virtual visit / urgent care / ER), or reject (hold).
5. On escalation, the routing screen confirms which queue the patient went
   to. On approval, the patient sees the AI's original recommendation. On
   rejection, the workflow stops cleanly and Vera records the override.
6. Click through to the audit trail on Vera. Every recorded action,
   review, and final routing decision is on the cryptographic chain —
   that's the demo.

To stop the stack:

```bash
make down
```

To wipe the operational DB (encounter history, sessions) between long
demos:

```bash
make clean
```

## The demo script

Roughly 2–3 minutes on a sales screenshare. Pace each beat to the visual
that lands.

1. **Frame the problem (15s).** "AI symptom checkers are rolling out across
   telehealth — K Health, Amwell, the lot. Every CIO has the same question:
   what happens when the model tells a stroke patient to drink fluids and
   rest? AB 316 already removed the 'AI did it autonomously' defense in
   California. That's a runtime trust problem."
2. **Show the customer (15s).** Open `http://localhost:3002`. "TriageGuard
   is a stand-in for one of those vendors. Browser, FastAPI backend,
   that's it. Vera is invisible from here."
3. **Run a triage (30s).** Sign in as Nurse Rivera. Pick the
   "chest-pain-with-anxiety" fixture. Click run. Narrate the SSE stream:
   "Classifier from OpenAI says self-care, low acuity. Red-flag detector
   from Claude is scanning the symptom set in parallel…"
4. **Catch the red flag (45s).** When the modal pops: "Vera's policy
   layer caught it. The classifier said self-care, but the red-flag
   detector tripped on chest pain. Vera held the recommendation — the
   patient never saw the unsafe call. The on-call nurse decides." Click
   *Escalate to ER*.
5. **Show the routing (15s).** "Patient's view updates: ER referral,
   not self-care. The AI's original recommendation never reached them.
   Nurse Rivera signed the override."
6. **Pivot to Vera (45s).** Open the Vera dashboard tab. Show the
   triage's actions on the audit chain — the symptom intake, the AI
   classification, the red-flag flag, the override, the final routing,
   all linked, all signed. "Every event you saw in the UI is on this
   chain. Cryptographic. Append-only. That's the audit trail a malpractice
   plaintiff's attorney will subpoena. TriageGuard didn't build any of
   this — it dropped in the SDK."

If the demo blows up mid-flow, that's a feature: pivot to "and Vera saw
that error too — let me show you" and walk the failure path.

## What's next

This is one of seven planned mock customers in the simulator bench. See
[`../../README.md`](../../README.md) for the full ICP map. Slugs in
flight or planned: `scribemd` (shipped), `triageguard` (this one),
`authassist`, `trialscope`, `appealsai`, `pvscope`, `credly`. Each
follows this same shape — backend + frontend + docker-compose at the
customer level — so adding the next one is mostly copy-modify.

The chaos mode (running Vera locally and tampering with its DB to verify
alarms fire) is **not** part of this stack. That's a separate compose at
the repo root.

## Troubleshooting

**Backend says "no API key" or 401s out of Vera.**
The backend reads `VERA_API_KEY_TRIAGEGUARD` from `.env.local`. Confirm
the value is the live key from `simulator/.env.local`, not the
`al_live_replace_me` placeholder. Re-run `make bootstrap` if unsure.

**CORS error in the browser console.**
The backend's allowed origins come from `CORS_ORIGINS`. The default covers
`http://localhost:3002` and `http://127.0.0.1:3002`. If you proxy the
frontend through a different host, add it here and `make down && make up`.

**SSE doesn't connect or hangs.**
The healthcheck waits for the backend to answer `/api/health` before the
frontend starts. If the backend never goes healthy, check
`docker compose logs triageguard-backend` for an import error — usually a
missing env var or a Vera-prod credential. Bring the stack up with
`make logs` running in another tab.

**Vera production rate limit.**
Vera's prod tier has per-org RPM caps. If a demo run hits 429, slow the
pacing or wait the cooldown. The simulator deliberately does not retry on
429 — surfacing the limit is part of the trust story.

**Frontend container can't find a module after I edited a dependency.**
The `node_modules` volume is anonymous and survives restarts. `make clean`
drops it; subsequent `make up` reinstalls.

**`docker compose` complains about a missing `.env.local`.**
Copy `.env.example` to `.env.local` to satisfy the loader. The file is
gitignored so it never gets committed.

**The bootstrap step succeeded but the key isn't in this directory's
`.env.local`.**
By design — `make bootstrap` writes to the shared `simulator/.env.local`.
Copy `VERA_API_KEY_TRIAGEGUARD=...` from there into this directory's
`.env.local`. We don't auto-sync the two files because the demoer might
want to point TriageGuard at a different Vera environment than the rest
of the simulator.

**Nurse review modal never fires.**
The HITL gate only trips when both (a) the classifier returns a
no-escalation recommendation and (b) the red-flag detector matches. Try
the `chest-pain-with-anxiety` or `sudden-weakness-elderly` fixture — both
are scripted to land in that combination. The
`TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS` env var caps how long the worker
waits before auto-rejecting.
