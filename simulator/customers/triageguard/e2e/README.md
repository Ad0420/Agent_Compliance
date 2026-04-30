# TriageGuard e2e

Playwright end-to-end tests that drive the TriageGuard demo through a
real browser: login, fixture pick, live pipeline, HITL escalation,
routed-to-ER terminal screen. The backend runs with stubbed Vera + LLM
clients (imported from the existing pytest smoke) so the test is
deterministic and needs no API keys.

## What it covers

A single happy-path scenario:

1. `/` redirects to `/login`.
2. Sign in with the test passkey lands on `/triage`.
3. `red_flag_chest_pain` is the default-selected fixture; click
   **Start triage session**.
4. The pipeline runs through listening → classifying → red-flag check
   → awaiting review.
5. The review gate shows red-flag terms ("chest pain", …) and the
   recommended override `ER`.
6. Click **Escalate to ER**.
7. The routed-screen hero reads "Patient routed to ER."
8. The "View audit trail" link has `target="_blank"` and an `href`
   that contains `/actions/`.

## Architecture

```
e2e/
├── playwright.config.ts        chromium-only, two webServer entries
├── harness/
│   └── server.py               python -m … boots uvicorn :8002 with stubs
└── tests/
    └── triage-happy-path.spec.ts
```

Playwright owns process lifecycle. Its `webServer` config:

- starts the **backend** with `python -m simulator.customers.triageguard.e2e.harness.server` from the repo root, listening on `:8002`
- starts the **frontend dev server** with `npm run dev` from `../frontend`, listening on `:3002`
- tears both down at the end of the run

The harness imports the production FastAPI app, then calls
`workflow_runner.install_test_factories(...)` to swap in
`FakeVeraClient` and `FakeOpenAILLM` / `FakeAnthropicLLM` from the
pytest smoke at `backend/tests/test_smoke.py`. One source of truth for
both surfaces — when the fakes drift, both move together.

## Run

```bash
cd simulator/customers/triageguard/e2e
npm install
npx playwright install chromium
npm run e2e
```

In CI we add `--with-deps` so Chromium's system libs land too:

```bash
npx playwright install chromium --with-deps
```

The frontend's `node_modules` should already be installed (the e2e
config runs `npm run dev` against `../frontend`). If you've never run
the frontend, do a one-time:

```bash
cd ../frontend && npm ci
```

## Prerequisites

- Python 3.12 with the backend deps installed:
  `pip install -e ./sdk -r simulator/customers/triageguard/backend/requirements.txt`
- Node 22 with frontend deps installed (`cd ../frontend && npm ci`)
- Playwright + chromium (`npm install` + `npx playwright install chromium`)

## Troubleshooting

**Port 8002 / 3002 is already in use.** Locally `reuseExistingServer`
is true, so re-using is fine. In CI it's false, so kill the offender:

```bash
lsof -ti:8002 | xargs kill -9 || true
lsof -ti:3002 | xargs kill -9 || true
```

**Backend boot fails with "ModuleNotFoundError: simulator…".** The
harness needs the repo root on `sys.path`. The `python -m …` form
takes care of this; running the script directly does too (it inserts
the path explicitly). If you really want to run uvicorn yourself,
make sure your CWD is the repo root.

**The flow stalls at "Classifying triage level".** The stubs return
canned text synchronously, so the workflow should advance within a
few hundred ms. If it hangs, the backend probably failed to install
the test factories — check the Playwright run log for the harness's
stderr.

## Local-vs-CI differences

| | Local | CI |
|---|---|---|
| Reuse existing server | Yes | No (each job is fresh) |
| Reporters | `list` + `html` | `list` + `html` |
| Trace / video | retain on failure | retain on failure |
| Browser install | manual | step in workflow |

## Why is the suite a separate npm package?

The frontend is a Next.js app with its own types and lockfile. Putting
Playwright there would couple the test runner to the prod bundle and
slow down CI on every install. A sibling package keeps Playwright's
dependency graph independent of the app.
