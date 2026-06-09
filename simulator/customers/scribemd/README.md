# ScribeMD

The flagship demo in the Vera simulator's multi-tenant medtech bench. A mock
AI-scribe vendor in the mould of Abridge or Ambience: physician records a
visit, an LLM drafts the SOAP note, a second LLM extracts orders, the
physician signs off, the chart writes back to a mock EHR. Every step lands
on Vera's audit chain — that's the point.

This directory is what a demoer opens. One command (`make demo`) brings up a
running stack pointed at Vera production.

## What is this?

ScribeMD is the customer-facing surface for use case 1 in `use_cases.md`.
It's a thin FastAPI/SSE backend wrapping the Week 1 `run_encounter` workflow
plus a Next.js frontend that drives the pipeline through a browser. Vera
holds the audit truth; ScribeMD only keeps operational state (the encounter
row, the SSE replay buffer, a session token) in a local SQLite file.

The simulator at large is documented at [`../../README.md`](../../README.md).

## Architecture

```
   ┌───────────────┐     HTTP / SSE      ┌────────────────┐     SDK      ┌──────────────┐
   │   Browser     │  ───────────────►   │ ScribeMD       │  ─────────►  │ Vera         │
   │ (Next.js,     │                     │ backend        │              │ production   │
   │  port 3001)   │  ◄───────────────   │ (FastAPI 8001) │  ◄─────────  │ usevera.xyz  │
   └───────────────┘                     └────────┬───────┘              └──────────────┘
                                                  │
                                                  ▼
                                         SQLite (operational
                                              state only)
```

Both services run as containers via `docker-compose.yml`. The browser hits
the backend on the host's `:8001` directly — no reverse proxy, no nginx.
The backend authenticates to Vera with an API key issued at bootstrap time.

## Prerequisites

- Docker Desktop (or Docker Engine 24+) with `docker compose`.
- An OpenAI API key. The note-drafting agent runs against `gpt-4o`-class
  models.
- An Anthropic API key. The orders-extraction agent runs against Claude.
- A Vera production URL (defaults to `https://api.usevera.xyz`).
- A one-time org bootstrap that registers ScribeMD on Vera and stashes the
  API key. The `make bootstrap` target handles this.

You do **not** need a local Vera. The chaos-mode local Vera under the repo
root is a separate concern.

## First-time setup

From this directory:

```bash
# 1. Configure env vars.
cp .env.example .env.local
$EDITOR .env.local
#    Fill in OPENAI_API_KEY and ANTHROPIC_API_KEY at minimum.
#    Leave VERA_API_KEY_SCRIBEMD as the placeholder for now — the next
#    step will overwrite it.

# 2. Register ScribeMD on Vera production (idempotent; safe to re-run).
make bootstrap
#    This calls POST /v1/register on Vera, installs ScribeMD's policies,
#    and writes VERA_API_KEY_SCRIBEMD to ../../.env.local
#    (i.e. simulator/.env.local). Copy that value into this directory's
#    .env.local so the docker-compose stack can read it:

grep VERA_API_KEY_SCRIBEMD ../../.env.local >> .env.local
$EDITOR .env.local   # de-duplicate if you re-ran bootstrap

# 3. Build and run.
make up
```

`make up` blocks in the foreground and streams logs from both containers.
Ctrl-C tears the stack down. First build takes ~2 minutes (Python wheels +
npm install). Subsequent builds reuse the layer cache.

When the backend logs `Application startup complete` and `npm` reports
`Ready in NNNms`, open `http://localhost:3001` in a browser.

## Daily use

```bash
make up
```

Then in the browser:

1. Sign in with the passkey from `.env.local`. The default is
   `demo-passkey-change-me`.
2. Pick a fixture transcript from the dropdown, or paste a custom one. The
   fixtures live in `simulator/customers/scribemd/fixtures/encounters.py`
   and cover routine, high-risk, and adversarial cases.
3. Click "Start encounter". The pipeline streams progress over SSE — note
   draft → orders extraction → policy check → HITL gate.
4. When the HITL gate fires, an approval modal pops up. Approve or reject.
5. On approval, the EHR mock confirms write-back. On rejection, the
   workflow stops cleanly and Vera records the override.
6. Click through to the audit trail on Vera. Every recorded action,
   approval, and chart commit is on the cryptographic chain — that's the
   demo.

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

1. **Frame the problem (15s).** "AI scribes are everywhere — Abridge,
   Ambience, Nuance — but every CIO has the same question: how do I prove
   the chart entry the model wrote down was the chart entry the doctor
   approved? That's a runtime trust problem."
2. **Show the customer (15s).** Open `http://localhost:3001`. "ScribeMD is
   a stand-in for one of those vendors. Browser, FastAPI backend, that's
   it. Vera is invisible from here."
3. **Run an encounter (45s).** Sign in. Pick the "routine follow-up"
   fixture. Click start. Narrate the SSE stream as it flows: "Note draft
   from OpenAI… orders extraction from Claude… policy check…"
4. **Catch the gate (30s).** When the HITL modal pops: "Vera's policy
   layer flagged this for review. The model proposed a controlled
   substance. Vera held the action. The clinician decides — model didn't."
   Approve.
5. **Show the EHR write (15s).** "And now the chart commit lands. The
   approved orders, signed by the physician, recorded by Vera."
6. **Pivot to Vera (45s).** Open the Vera dashboard tab. Show the
   encounter's actions on the audit chain — the SOAP draft, the orders,
   the approval, the commit, all linked, all signed. "Every event you saw
   in the UI is on this chain. Cryptographic. Append-only. That's the
   audit trail an EU AI Act auditor wants. ScribeMD didn't build any of
   this — it dropped in the SDK."

If the demo blows up mid-flow, that's a feature: pivot to "and Vera saw
that error too — let me show you" and walk the failure path.

## What's next

This is one of seven planned mock customers in the simulator bench. See
[`../../README.md`](../../README.md) for the full ICP map. Slugs in flight
or planned: `triageguard`, `authassist`, `trialscope`, `appealsai`,
`pvscope`, `credly`. Each will follow this same shape — backend + frontend
+ docker-compose at the customer level — so adding the next one is mostly
copy-modify.

The chaos mode (running Vera locally and tampering with its DB to verify
alarms fire) is **not** part of this stack. That's a separate compose at
the repo root.

## Troubleshooting

**Backend says "no API key" or 401s out of Vera.**
The backend reads `VERA_API_KEY_SCRIBEMD` from `.env.local`. Confirm the
value is the live key from `simulator/.env.local`, not the
`al_live_replace_me` placeholder. Re-run `make bootstrap` if unsure.

**CORS error in the browser console.**
The backend's allowed origins come from `CORS_ORIGINS`. The default covers
`http://localhost:3001` and `http://127.0.0.1:3001`. If you proxy the
frontend through a different host, add it here and `make down && make up`.

**SSE doesn't connect or hangs.**
The healthcheck waits for the backend to answer `/api/health` before the
frontend starts. If the backend never goes healthy, check
`docker compose logs scribemd-backend` for an import error — usually a
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
The compose file marks `.env.local` as `required: false`. If you see a
parse error instead, you're on an older docker compose — upgrade to v2.20+
or copy `.env.example` to `.env.local` to satisfy the loader.

**The bootstrap step succeeded but the key isn't in this directory's
`.env.local`.**
By design — `make bootstrap` writes to the shared
`simulator/.env.local`. Copy `VERA_API_KEY_SCRIBEMD=...` from there into
this directory's `.env.local`. We don't auto-sync the two files because the
demoer might want to point ScribeMD at a different Vera environment than
the rest of the simulator.
