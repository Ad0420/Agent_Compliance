# Harness

Boots the TriageGuard backend on `127.0.0.1:8002` with stubbed Vera and
LLM clients. Playwright's `webServer[0]` shells this out before the
test runs.

## Run it standalone

From the repo root:

```bash
python -m simulator.customers.triageguard.e2e.harness.server
```

The harness sets `TRIAGEGUARD_PASSKEY=e2e-passkey-123`, a per-run
sqlite DB url, CORS for `localhost:3002`, and a 10s nurse-review
timeout. Override any of these by exporting the env var before invoking
the harness — `setdefault` won't clobber a value that's already set.

## What gets stubbed

The harness calls
`simulator.customers.triageguard.backend.workflow_runner.install_test_factories(...)`
with two factories that return:

- `FakeVeraClient` — in-memory action recorder + approval registry,
  imported from `backend/tests/test_smoke.py`.
- `FakeOpenAILLM` / `FakeAnthropicLLM` — deterministic JSON payloads,
  also from the smoke test. The chest-pain narrative trips a red flag
  with terms `["chest pain","diaphoresis","jaw radiation"]` and
  `recommended_override="ER"` — which is exactly what the e2e clicks
  through.

## Why import from `tests/`?

The fakes there are the contract. If they change shape (e.g. a new
red-flag term gets added) the e2e should observe the change without
us having to remember to mirror it. ScribeMD's harness duplicated its
stubs locally — TriageGuard goes the importing route deliberately.
