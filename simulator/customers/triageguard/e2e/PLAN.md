# TriageGuard e2e — Plan (Wave 4E)

One Playwright happy-path test driving the real frontend against a
stubbed-backend Python harness. Mirrors ScribeMD's shape (ports,
routes, decision swapped).

## 1. Architecture

```
playwright.config.ts (chromium-only)
   ├── webServer[0] backend  → python -m simulator.customers.triageguard.e2e.harness.server  (uvicorn :8002, fakes installed)
   └── webServer[1] frontend → npm run dev (Next.js :3002)

tests/triage-happy-path.spec.ts → drives Chromium against http://localhost:3002
```

Playwright owns the lifecycle: it brings both services up in parallel,
waits for each port to answer, runs the spec, then tears them down.
On CI `reuseExistingServer: false`; locally `true` for fast iteration.

## 2. Fakes-reuse strategy

Per the brief I import `FakeVeraClient`, `FakeOpenAILLM`,
`FakeAnthropicLLM` directly from
`simulator.customers.triageguard.backend.tests.test_smoke`. Those
fakes already encode the contract: chest-pain trips
`["chest pain","diaphoresis","jaw radiation"]` with
`recommended_override="ER"`. One set of canned responses, two
consumers.

(ScribeMD's harness duplicated its stubs in `harness/stubs.py` —
deliberate divergence; called out in the harness docstring so future
readers don't think it's drift.)

## 3. Test beats (narrative)

1. `page.goto("/")` → expect URL matches `/login` (auth guard redirects).
2. Fill `getByLabel("Passkey")` with `e2e-passkey-123`.
3. Click `getByRole("button", { name: "Sign in" })`.
4. Expect URL `/triage`; expect heading `Start a triage session`.
5. The default-selected fixture card is already `red_flag_chest_pain`,
   so go straight to clicking `getByRole("button", { name: /Start triage session/i })`.
6. Scope `pipeline = page.getByLabel("Triage session pipeline")` and assert
   each of the four step labels visible inside that scope: `Listening to symptoms`,
   `Classifying triage level`, `Checking for red flags`,
   `Awaiting your triage decision` (10s timeout on the first).
7. Wait for the review-gate Escalate button:
   `getByRole("button", { name: /Escalate to ER/i })`. Scope the
   red-flag-terms assertions to its enclosing card region via the
   "Awaiting your triage decision" header text scoped to the gate.
8. Click "Escalate to ER".
9. Expect heading `Patient routed to ER.` (10–30s timeout while the
   workflow finalises and the SSE bus closes).
10. Audit-trail link: `getByRole("link", { name: /view audit trail/i })`,
    assert `target="_blank"` and `href` contains `/actions/`.

## 4. Strict-mode discipline

Every locator that could match more than one element is scoped:

- `pipeline = page.getByLabel("Triage session pipeline")` — pipeline
  step labels are queried under `pipeline.getByText(...)`. The topbar
  shows "Awaiting your triage decision" too while the gate is open
  (live-pipeline.tsx step 4 uses the same string), so an unscoped
  `getByText("Awaiting your triage decision")` would resolve to two
  elements. PR #122 burned us on this once.
- "Red-flag terms detected:" appears in both the pipeline payload
  and the review-gate. We don't assert that string globally; we
  assert via the dedicated chest-pain term ("chest pain") under a
  reasonable scope.
- All button assertions go through `getByRole("button", ...)` which
  excludes plain text matches.

## 5. Env wiring

| Var | Set by | Value |
|---|---|---|
| `TRIAGEGUARD_PASSKEY` | harness (env default) + Playwright `webServer[0].env` | `e2e-passkey-123` |
| `TRIAGEGUARD_DB_URL` | harness | `sqlite+aiosqlite:///<tmp>` per process |
| `TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS` | harness + Playwright | `10` |
| `CORS_ORIGINS` | Playwright `webServer[0].env` | `http://localhost:3002,http://127.0.0.1:3002` |
| `NEXT_PUBLIC_TRIAGEGUARD_API_URL` | Playwright `webServer[1].env` | `http://localhost:8002` |
| `PYTHONUNBUFFERED` | Playwright `webServer[0].env` | `1` |

## 6. CI workflow shape (`.github/workflows/triageguard-e2e.yml`)

Mirrors `.github/workflows/e2e.yml` with paths swapped:

1. checkout / setup-python 3.12 / setup-node 22
2. `pip install -r backend/requirements.txt -r simulator/customers/triageguard/backend/requirements.txt -e ./sdk pytest-timeout`
3. `cd simulator/customers/triageguard/frontend && npm ci`
4. `cd simulator/customers/triageguard/e2e && npm ci`
5. `npx playwright install --with-deps chromium`
6. `npm run e2e`
7. On failure: upload `playwright-report/` + `test-results/`.

`timeout-minutes: 15`. Hermetic — no real Vera/LLM calls.

## 7. Failure-artifact strategy

`playwright.config.ts` retains traces/screenshots/videos on failure
(`trace: "retain-on-failure"`, etc.). CI uploads `playwright-report/`
and `test-results/` only on failure (`if: failure()`), 14- and 7-day
retention respectively.
