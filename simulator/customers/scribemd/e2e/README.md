# ScribeMD e2e

Playwright end-to-end tests that drive the ScribeMD demo through a real
browser: login, encounter selection, live pipeline, HITL approval, EHR
mock. The backend runs with stubbed Vera + LLM clients so the test is
deterministic and needs no API keys.

## What it covers

A single happy-path scenario:

1. `/` redirects to `/login`.
2. Sign in with the test passkey lands on `/encounter`.
3. Pick the pancreatitis fixture, click **Start encounter**.
4. The pipeline runs through draft → orders → approval gate.
5. The approval gate shows "Acute pancreatitis", "Ondansetron", and a
   high/critical risk pill.
6. Click **Sign and commit**.
7. The EHR mock renders "Chart updated" + "Note signed by Dr. Adams".
8. The "View audit trail" link points at `https://usevera.xyz/actions/...`.

## Architecture

```
e2e/
├── playwright.config.ts        chromium-only, two webServer entries
├── harness/
│   ├── server.py               python -m … boots uvicorn with stubs
│   └── stubs.py                in-memory FakeVeraClient + fake LLMs
└── tests/
    └── encounter-happy-path.spec.ts
```

Playwright owns process lifecycle. Its `webServer` config:

- starts the **backend** with `python -m simulator.customers.scribemd.e2e.harness.server` from the repo root, listening on `:8001`
- starts the **frontend dev server** with `npm run dev` from `../frontend`, listening on `:3001`
- tears both down at the end of the run

The harness imports the production FastAPI app, then calls
`workflow_runner.install_test_factories(...)` to swap in
`FakeVeraClient` and `FakeOpenAILLM` / `FakeAnthropicLLM`. Same shape as
the pytest smoke test, lifted into a standalone module so e2e doesn't
have to depend on `tests/`.

## Run

```bash
cd simulator/customers/scribemd/e2e
npm install
npx playwright install chromium
npm test
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
  `pip install -e ./sdk -r simulator/customers/scribemd/backend/requirements.txt`
- Node 22 with frontend deps installed (`cd ../frontend && npm ci`)
- Playwright + chromium (`npm install` + `npx playwright install chromium`)

## Troubleshooting

**Port 8001 / 3001 is already in use.** Locally `reuseExistingServer`
is true, so re-using is fine. In CI it's false, so kill the offender:

```bash
lsof -ti:8001 | xargs kill -9 || true
lsof -ti:3001 | xargs kill -9 || true
```

**Backend boot fails with "ModuleNotFoundError: simulator…".** The
harness needs the repo root on `sys.path`. The `python -m …` form
takes care of this; running the script directly does too (it inserts
the path explicitly). If you really want to run uvicorn yourself,
make sure your CWD is the repo root.

**The flow stalls at "Drafting note".** The stubs return canned text
synchronously, so the workflow should advance within a few hundred ms.
If it hangs, the backend probably failed to install the test factories
— check the Playwright run log for the harness's stderr.

**`npm test` ends with an HTML report.** Open it from the report
directory the run prints — handy for screenshots, network log, traces.

## Local-vs-CI differences

| | Local | CI |
|---|---|---|
| Reuse existing server | Yes | No (each job is fresh) |
| Reporters | `list` | `list` + `html` |
| Trace / video | retain on failure | retain on failure |
| Browser install | manual | step in workflow |

## Why is the suite a separate npm package?

The frontend is a Next.js app with its own types and lockfile. Putting
Playwright there would couple the test runner to the prod bundle and
slow down CI on every install. A sibling package keeps Playwright's
dependency graph independent of the app.
