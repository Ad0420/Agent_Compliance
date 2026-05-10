# Vera MVP Hardening Plan — Revised

**Date:** 2026-05-10 (revised after /autoplan + user overrides)
**Authors:** Advik, Priyansh (with Claude as office-hours partner)
**Status:** APPROVED — full revised plan with both user challenges accepted
**Scope:** Make Vera production-safe + DX-credible + auth-migrated for medtech pilot. Excludes policy engine rebuild (deferred).

---

## What changed from v1

User accepted both /autoplan challenges and added one new workstream:
1. ✅ **Challenge 1 accepted:** Pilot charter / signed design-partner agreement is now a pre-W1 gate (May 13 deadline). If not signed → freeze B+C, redirect to outbound.
2. ✅ **Challenge 2 accepted:** DX scope (DX-A through DX-I) added to plan. Wedge claim "30-min integration" must be deliverable.
3. ✅ **DX-8 promoted to required:** compliance-reviewer dashboard view added as Workstream F.
4. ✅ **NEW Workstream E:** Auth migration to Clerk for human auth; API keys retained for SDK.

End-state target slips one week: **June 13, 2026** (still inside Colorado AI Act window of June 30 and EU AI Act window of Aug 2).

---

## Why this plan exists

Office-hours grilling + /autoplan dual-voice review surfaced four classes of risk:

1. **Latency / exception injection** — sync `@audit` decorator can block customer's hot path up to ~90s; Vera HTTP failures propagate as exceptions out of customer code.
2. **HIPAA-insufficient redaction** — default Redactor catches ~4 of 18 PHI identifiers; regex approach is "false safety" for free-text PHI.
3. **DX gaps** — TTHW unmeetable, no dev mode, no env vars, no CHANGELOG, no branded exceptions, no CI/CD on PyPI. The 30-min integration claim is currently unsupported.
4. **Auth model** — API-key-only is the wrong fit for human dashboard users. Compliance reviewer handoff is unscoped.

Plus a parallel non-code track:

5. **No BAA in place** — pilot cannot legally begin without it.

Plus a strategic gate from CEO review:

6. **Premise 1 risk** — pilot is verbal-commit only. Without a binding agreement by May 13, 4 founder-weeks may be optimizing for a phantom.

---

## Premises (all confirmed via office-hours session + /autoplan gate)

1. ✅ Medtech pilot customer is real **but verbal-commit only** — verified by binding agreement (Workstream C0) before W1 spend.
2. ✅ Production-safety must precede PHI flow.
3. ✅ SDK behavior must match observability-tool norms (Sentry/Datadog: never add latency, never propagate errors).
4. ✅ Minimum viable HIPAA package suffices for pilot; SOC 2 / HITRUST is post-Series A.
5. ✅ Railway may need to be replaced for the data tier if no BAA is signable.
6. ✅ Human auth via Clerk; SDK auth via API keys (split per surface).

---

## Workstreams

### Workstream A — SDK hot-path safety

**Goal:** Vera SDK adds zero blocking latency to customer's wrapped functions, and never raises Vera-originated exceptions out of the wrapper. Records survive Vera outages.

**A1. Async-by-default sync client (background thread)**
- Background-thread queue model on `VeraClient`. Mirrors `AsyncVeraClient.enqueue_action`.
- New parameter on the **decorator**: implicit async-by-default. **`record_action()` keeps blocking semantics** (per A9 below).
- Bounded queue (default 10K). Drop-oldest with rate-limited WARN log on overflow — but only if A5 spool is unavailable.
- Periodic batched POST to `/v1/actions/batch`. Default flush interval 5s.
- Files: [sdk/vera/client.py](sdk/vera/client.py), [sdk/vera/decorator.py](sdk/vera/decorator.py).

**A2. Exception isolation in decorators**
- Wrap every `effective_client.record_action(...)` and `effective_client.enqueue_action(...)` call inside `@audit` and `@async_audit` in `try/except Exception`. Log at WARNING. Never re-raise.
- Customer function failures still propagate — only Vera-originated failures swallowed.
- Files: [sdk/vera/decorator.py](sdk/vera/decorator.py), [sdk/vera/async_decorator.py](sdk/vera/async_decorator.py).

**A3. Default timeout reduction**
- Change `httpx.Client/AsyncClient` default timeout from 30s → 5s.
- Document in SDK README: "audit ops fail fast, customer code never blocks."
- Files: [sdk/vera/client.py](sdk/vera/client.py), [sdk/vera/async_client.py](sdk/vera/async_client.py).

**A4. Real atexit drain**
- Replace `_atexit_warning` with actual queue drain. Sync and async paths.
- Bound drain at `atexit_drain_timeout=10s`.
- Files: [sdk/vera/async_client.py](sdk/vera/async_client.py), new sync drain in [sdk/vera/client.py](sdk/vera/client.py).

**A5. Persistent on-disk buffer (REQUIRED, was stretch)**
- SQLite WAL spool when in-memory queue saturates.
- Encryption at rest via SQLCipher (PHI is on-disk now).
- File mode 0600. No bearer tokens persisted (only payload body).
- Disk-full ENOSPC handled gracefully — WARN, retain mem queue, no crash.
- Schema migration on SDK upgrade.
- Multi-process WAL writer contention tested.
- Restart rehydration: spool → mem queue on client init.
- Off by default in dev mode; on by default in production mode.

**A6. Schema-driven redaction (NEW, replaces regex-only `Redactor.medtech()`)**
- `Redactor.medtech(schema=...)` accepts a customer-declared field schema.
- **Deny-by-default**: any field NOT in the schema is rejected or fully replaced with `[REDACTED:UNMAPPED]`.
- Schema declares each field as: `passthrough` (safe — opaque IDs only), `redact` (PHI — full mask), or `pattern` (apply named regex).
- Free-text fields explicitly marked `redact` or omitted; documentation says "free-text PHI is out of scope."
- Augments existing `Redactor` regex pass — regex still applies as defense-in-depth.

**A7. Fork safety + concurrency model**
- Track `os.getpid()` on client. On mismatch (post-fork in child), reinit queue + thread + lock.
- Register `os.register_at_fork(after_in_child=...)` handler.
- Document supported runtimes: gunicorn (preload + post-fork), Celery, multiprocessing.
- Document **un**supported: gevent/eventlet (or expose explicit `mode="thread"` vs `mode="loop"`).
- One owner thread/loop. Serialize flushes with lock/condition.

**A8. Poison-batch handling**
- Classify failures in `_flush`:
  - 4xx (except 429): permanent-drop with ERROR log; do NOT re-queue.
  - 429, 5xx, network timeout, DNS fail: re-queue with exponential backoff + jitter.
- Circuit breaker: skip flush if last N batches failed; global exponential backoff.
- Cap re-queue depth to prevent infinite-loop CPU burn.
- Split bad batches to isolate poison records.

**A9. Backwards-compat preservation for `record_action()`**
- `VeraClient.record_action()` keeps its current synchronous, returns-server-JSON semantics. **No silent default flip.**
- New `VeraClient.enqueue_action()` mirrors `AsyncVeraClient.enqueue_action()` — fire-and-forget, no return.
- Decorators (`@audit`, `@async_audit`) use `enqueue_action()` by default — that's where the "never blocking" promise lives.
- Direct callers of `record_action()` get blocking + ack as before. Document explicitly.

**Tests:** see [test plan artifact](~/.gstack/projects/Agent_Compliance/priyansh-claude-heuristic-elbakyan-d0456d-test-plan-20260509.md). 57 cases + 13 manual verifications.

**Effort:** 8–10 days (was 5–7), one engineer. Increase due to A5 promotion + A6 + A7 + A8 + A9.

---

### Workstream B — HIPAA-grade redaction (now anchored on A6 schema-driven approach)

**B1. `Redactor.medtech()` factory using A6 schema model**
- Defaults bundled with the factory: schema for the canonical medtech encounter (patient_id passthrough, name redact, MRN pattern, DOB pattern, ICD-10 flag-only, IPv4/v6 redact, address redact, free-text notes redact).
- Customer customizes via `Redactor.medtech(schema={...})`.

**B2. SDK README — HIPAA section**
- New section: "Using Vera with PHI."
- Lists all 18 HIPAA Safe Harbor identifiers + which schema entries cover each.
- Code sample showing `Redactor.medtech(schema=...)` + customizing.
- Strong warning: "Free-text PHI cannot be reliably scrubbed. Use opaque IDs."

**B3. BAA-required notice**
- INFO log via module logger on first use of `Redactor.medtech()`: "BAA required for production PHI use. Confirm signed BAA with Vera."
- One-time per process. NullHandler-default so it doesn't spam customer's stdout/Datadog.

**Effort:** 3–4 days (was 2–3). Increase due to schema model.

---

### Workstream C — BAA & legal/compliance

**C0. Pilot charter / design-partner agreement (NEW PRE-W1 GATE) — DEADLINE MAY 13**
- Signed pilot charter or paid design-partner agreement with the medtech customer.
- Must specify: workflow, PHI fields touched, environment (staging-first), pilot owner at customer, success criteria, fee (even $1).
- **Hard gate:** If not signed by May 13, freeze Workstreams B + C. Reallocate founder time to outbound (D0).
- Why a fee even if nominal: signals binding intent; compliance teams who won't sign a $1 PO won't sign a BAA either.

**C1. Customer-facing BAA**
- Engage healthcare-aware startup lawyer (Cooley / Wilson Sonsini / Gunderson Dettmer healthcare practice).
- Scope: BAA template + 1-hour consult. Budget $1.5–3K.
- Required clauses: 45 CFR 164.504(e).
- Turnaround target: signed BAA in < 14 days from May 13.

**C2. Subcontractor audit & BAAs (PROMOTED TO MAY 13 DEADLINE — was W2-W3)**
- Vendor stack PHI-exposure matrix in `compliance/vendors.md`.
- Critical-path-blocking: Railway BAA stance must be known by May 13. If no BAA → migrate Postgres to AWS RDS in W2 (week-long add).
- AWS BAA via Artifact (free, ~10 min).
- Vercel Pro BAA if frontend ever displays PHI.
- Resend: strip PHI from email payloads.
- All subcontractor BAAs signed by W2 end.

**C3. 4 policy documents (W2)**
- Privacy Policy
- Information Security Policy
- Incident Response Plan
- HIPAA Risk Assessment
- 2–3 pages each. Templates from HHS / Vanta / open source.
- Stored at `compliance/policies/*.md`.

**C4. Workforce training (W3)**
- Both founders complete 1-hour HIPAA training (Coursera or HHS free).
- Certificates filed in `compliance/training/`.

**C5. Customer alignment call (PROMOTED TO W1 — was W3)**
- Specific call with medtech customer's compliance/CTO contact.
- Confirm PHI fields, retention, BAA timeline, pilot scope.
- Earlier alignment surfaces scope creep before legal spend.

**Effort:** Founder time over 4 weeks, parallel to A/B/DX/E/F. ~$3–5K legal budget.

---

### Workstream D — Outreach + Collateral cleanup

**D0. Founder outbound carve-out (NEW)**
- 30% of one founder/week for W1-W4: **5 discovery calls/week with fintech + medtech compliance buyers.**
- Goal: surface 2nd pilot candidate by W4 end. Diversify away from one-customer dependency.
- Use usevera.xyz regulations content as the conversation opener.

**D1. Honest collateral edits**
- "tamper-proof" → "tamper-evident" (every customer-facing surface)
- "court-admissible" → "designed for FRE 901/902 admissibility (legal opinion in progress)"
- "policy engine" → "guardrails" or "alerting rules"
- "first customer" → "design partner pilot in progress" until C0 signed; "design partner" after
- Files: `README.md`, `BETA_ONBOARDING.md`, `usevera.xyz` content

**D2. Pilot-vs-production maturity page**
- Add `usevera.xyz/maturity` documenting current pilot-grade state, production-grade roadmap.
- Earns trust faster than overclaiming.

**Effort:** 2 days collateral + 4 weeks parallel outreach.

---

### Workstream DX — Developer experience (NEW, full scope)

**Goal:** lift DX score from ~3/10 to ≥7/10 to credibly claim "30-min integration."

**DX-A. `vera.init()` Sentry-style entry point**
- Single-call setup: `vera.init(api_key=..., agent_name=...)` configures the default client + redactor for `@audit`.
- Eliminates 4-line constructor + `set_default_client(...)` boilerplate.

**DX-B. Dev mode + test harness**
- `VeraClient.dev()` factory prints JSON records to stderr; no API key needed.
- `VERA_DEV=1` env var triggers dev mode automatically.
- `pytest` fixture `vera_recording` — tests can assert on captured records without a live Vera.

**DX-C. Branded exception hierarchy**
- New module `vera.errors`: `VeraError`, `VeraAuthError` (401/403), `VeraRateLimitError` (429), `VeraServerError` (5xx), `VeraTimeoutError`, `VeraNetworkError`.
- Each `__str__` includes server's `X-Request-ID` (server must add) + `https://docs.usevera.xyz/errors/<code>` link.
- Backend route work: emit `X-Request-ID` on every response.

**DX-D. CHANGELOG + DeprecationWarning machinery + migration guide**
- `CHANGELOG.md` in Keep-a-Changelog format. Cover 0.3.0 → 0.4.0 jump.
- Any breaking change: ship behind `DeprecationWarning` for one minor version before flipping default.
- `MIGRATION.md` for major version transitions.
- Semver policy documented in `sdk/README.md`.

**DX-E. Env var loader**
- `VeraClient` reads `VERA_API_KEY`, `VERA_API_URL`, `VERA_AGENT_NAME` from env if not passed explicitly.
- Constructor args take precedence.
- Env-var table documented in `sdk/README.md`.

**DX-F. `vera` CLI**
- `vera config show` — prints effective config (env vars + constructor)
- `vera ping` — verifies API key works against Vera
- `vera tail` — tails recent records for the org (uses `query_actions` server-side)
- ~50–100 lines via Click or argparse.

**DX-G. README expansion**
- 4 framework cookbooks (OpenAI, Anthropic, LangChain, CrewAI) — copy-paste-runnable.
- Troubleshooting section.
- Env-var table.
- HIPAA section (replaces B2 — same content, expanded).
- HTTP API reference link.
- Quickstart that reaches first record visible in dashboard in < 5 minutes including signup.

**DX-H. CI/CD on PyPI**
- `.github/workflows/sdk-test.yml`: pytest matrix Python 3.10/3.11/3.12 on push.
- `.github/workflows/sdk-publish.yml`: automated PyPI publish on `sdk-v*` tag.
- Latency budget enforcement in CI: fail PR if p99 > 1ms healthy / 5ms degraded.

**DX-I. Decorator empty-client warning**
- Single WARN on first invocation when `@audit` decorator runs with no client configured.
- Fixes the silent compliance-breach risk: today devs can deploy `@audit` thinking auditing is on, when it isn't.

**Effort:** 6–8 days, one engineer. Spread across W1-W4.

---

### Workstream E — Auth migration to Clerk (NEW)

**Goal:** Human auth via Clerk; SDK auth via API keys (cleanly split). Pre-customer migration cost = zero.

**E1. Clerk frontend integration**
- Add `@clerk/nextjs` to frontend.
- Replace existing `register` and `login` pages with Clerk-hosted or Clerk-component flows.
- Configure Clerk Organizations as the multi-tenant primitive.
- File touches: [frontend/app/login](frontend/app/login), [frontend/app/register](frontend/app/register), [frontend/app/layout.tsx](frontend/app/layout.tsx) (ClerkProvider wrap).

**E2. Backend Clerk JWT auth middleware**
- New middleware verifies Clerk JWT on dashboard routes.
- Existing API key middleware ([backend/app/services/auth.py](backend/app/services/auth.py)) stays for SDK routes.
- Routes split into `/v1/dashboard/*` (Clerk JWT) vs `/v1/*` (API key) vs shared (`/v1/agents`, `/v1/actions/query`).
- File touches: [backend/app/services/auth.py](backend/app/services/auth.py), [backend/app/middleware](backend/app/middleware).

**E3. Org model bridge**
- Clerk webhook on `organization.created`: backend creates corresponding `Organization` row.
- Clerk webhook on `organizationMembership.created`: backend tracks user → org mapping.
- Clerk roles: `admin`, `developer`, `compliance_reviewer` (RBAC primitive for Workstream F).
- File touches: [backend/app/models/organization.py](backend/app/models/organization.py), new webhook route.

**E4. API key issuance UX**
- API keys become a Clerk-authenticated dashboard feature.
- Admins can generate, rotate, revoke keys in the UI.
- Old `/v1/register` endpoint deprecated → returns 410 Gone with migration message.
- API key hash storage + verification unchanged from current ([backend/app/models/api_key.py](backend/app/models/api_key.py), [backend/app/services/auth.py](backend/app/services/auth.py)).

**E5. Migration smoke test**
- Test: create Clerk org → backend creates Vera org → admin issues API key → SDK authenticates with key → record posts.
- Existing API keys (from `register.py`-issued seed orgs) continue to work — no break.

**Effort:** 5 days, one engineer. W1 design + W2-W3 implementation + W3 smoke test.

---

### Workstream F — Compliance reviewer dashboard (NEW)

**Goal:** When dev hands a dashboard URL to compliance, compliance can use it without help. Delivers the wedge promise.

**F1. RBAC primitive (depends on E3)**
- Three roles via Clerk: `admin` (full access), `developer` (write API keys, view records), `compliance_reviewer` (view records + saved views + exports, no write).
- Backend authorization checks on every route based on Clerk role claim.

**F2. Compliance reviewer landing page**
- Custom dashboard route `/compliance` for `compliance_reviewer` role.
- Default view: last 30 days of high-risk decisions, HITL approvals taken, policy violations.
- Saved-view URLs (shareable with regulators).
- One-click PDF export (uses existing [backend/app/services/export.py](backend/app/services/export.py)).

**F3. Audit-of-the-audit-log**
- Every action by a compliance_reviewer (view, export, etc.) is itself recorded.
- Compliance teams can prove their reviews happened.
- File touches: [frontend/app/(dashboard)](frontend/app/(dashboard)), new `/compliance` route, new `compliance_review_record` model.

**F4. Compliance quickstart docs**
- 1-page doc: "I'm a compliance lead. What do I do here?"
- Covers: how to find decisions about a data subject, how to export evidence, how to interpret policy violations, what to ask the dev.

**Effort:** 5 days, one engineer. W3 only (depends on E being done). Some design work in W2.

---

## Sequencing & timeline

| Week | A (SDK) | B (Redaction) | C (BAA) | D (Outreach) | DX | E (Clerk) | F (Compliance) |
|---|---|---|---|---|---|---|---|
| **W1 (May 10–17)** | A2 ships, A3 ships, A9 split designed | (parked until C0) | **C0 charter signed by May 13**, **C2 vendor audit by May 13**, C1 lawyer engaged, C5 alignment call | D0 outreach begins (5 calls), D1 collateral edits drafted | DX-A `vera.init()`, DX-D CHANGELOG, DX-E env vars, DX-I decorator WARN | E1 Clerk frontend integration designed | (planning only) |
| **W2 (May 17–24)** | A1 ships with A7 fork-safety, A8 poison-batch | A6 schema design + B1 medtech defaults | C1 BAA in lawyer review, C3 policy docs drafted, AWS BAA executed, Railway migration started if needed | D0 (10 calls cumulative), D1 collateral ships | DX-B dev mode, DX-C branded exceptions | E2 Clerk JWT middleware, E3 org model bridge | F1 RBAC primitive design |
| **W3 (May 24–31)** | A4 atexit drain, A5 SQLite spool with SQLCipher | A6 ships with B2 README HIPAA section, B3 BAA-required log | C2 subcontractor BAAs signed, C3 docs final, C4 workforce training | D0 (15 calls cumulative), D2 maturity page ships | DX-F vera CLI, DX-G README expansion | E4 API key issuance UX, E5 smoke test | F1 RBAC ships, F2 compliance landing page, F3 audit-of-audit-log |
| **W4 (May 31–Jun 13)** | regression / hardening / latency benchmark in CI | A6 hardening | Pilot legally cleared. Begin staged staging integration. | D0 (20+ calls, 2nd pilot candidate identified) | DX-H CI/CD on PyPI | E hardening | F4 compliance quickstart docs |

End state target: **June 13, 2026** — pilot legally cleared, SDK production-safe, DX score ≥ 7/10, Clerk-based human auth, compliance-reviewer dashboard live.

Pre-Colorado AI Act (June 30) by 17 days. Pre-EU AI Act (Aug 2) by 50 days.

---

## Critical-path risks (revised)

| Risk | Detection | Mitigation | Owner |
|---|---|---|---|
| **C0 not signed by May 13** | End of day May 13 | Freeze B+C; redirect to D0. Reassess plan May 16. Find 2nd pilot candidate by May 31. | Advik |
| **Railway no-BAA** | C2 audit (May 13) | AWS RDS migration adds 1 week to W2. Plan slips to June 20. | Priyansh |
| **Customer's HIPAA acceptance > minimum-viable** | C5 call (W1) | Reset scope: accept higher bar OR de-scope to non-PHI workflow. | Both |
| **A5 SQLCipher integration takes longer than estimated** | W3 mid-week | Ship A5 without encryption-at-rest (lower bar); mark "SQLCipher pending" in CHANGELOG; address in v0.5. | Priyansh |
| **Clerk webhook reliability for org creation** | E5 smoke test (W3) | Polling fallback; retry with idempotency key; monitor delivery rates. | Priyansh |
| **Anthropic/OpenAI native audit logging announcement during W1-W4** | Daily news scan | Workstream D rewrite within 48h to lead with HITL + chain-of-custody, not logging. | Both |
| **Founder bandwidth saturates** | W2 retro | D0 outreach is non-negotiable; cut DX-F or DX-H first. | Both |

---

## Failure Modes Registry

| Mode | Detection | Mitigation |
|---|---|---|
| Customer ghosts after BAA reaches their legal team | C5 call (W1) catches scope drift early | If detected: switch to second pilot candidate from D0; don't wait |
| Vera service outage > queue capacity → silent record loss | A5 spool addresses; without it, customer audit fails | A5 promoted to required ✅ |
| Free-text PHI in agent reasoning fields leaks despite Redactor | A6 schema-driven required | Regex-only documented as defense-in-depth, not primary |
| Decorator silently no-ops with no client | DX-I emits WARN on first invocation | ✅ in plan |
| Customer rotates API key mid-pilot via deprecated `/v1/register` | E4 deprecates that endpoint to 410 Gone | Migration message points to dashboard UI |
| Compliance team can't navigate dashboard | F4 quickstart docs + F2 saved views | If still failing: 30-min compliance-team onboarding call |
| Founder bandwidth: code crowds out outreach | D0 weekly count tracked | Retros catch this; cut DX-F or DX-H first if needed |

---

## Decision Audit Trail (revised)

| # | Phase | Decision | Class | Principle | Rationale |
|---|---|---|---|---|---|
| 1 | Phase 0 | Skip Phase 2 (Design) | Mechanical | n/a | No UI scope detected |
| 2 | CEO 0D | Promote A5 to required | Mechanical | P1, P2 | Cross-phase critical: drop-oldest contradicts evidentiary positioning |
| 3 | CEO 0D | Hold scope on policy engine rebuild | Mechanical | n/a | User explicitly deferred in office-hours |
| 4 | CEO-1 | **Add C0 pilot charter gate (May 13)** | **User-accepted** | P1 | Cross-phase critical: validates premise 1 |
| 5 | CEO-2 | Add D0 outreach carve-out | Auto | P1, P2 | Both voices flag pre-revenue trap |
| 6 | Eng-1 | A5 required (confirms #2) | — | — | — |
| 7 | Eng-2 | Add A9 — keep `record_action()` blocking, add `enqueue_action()` | Auto | P5 (explicit > clever) | Both voices flag backwards-compat semantic shift |
| 8 | Eng-3 | Add A7 — fork safety + concurrency model | Auto | P1, P5 | Both voices flag fork/gevent/asyncio |
| 9 | Eng-5 | Add A8 — poison-batch handling | Auto | P5 | Both voices flag retry storm |
| 10 | Eng-6 | Add A6 — schema-driven redaction | Auto | P1 | Cross-phase: regex insufficient |
| 11 | DX-1 | **Add full DX scope (DX-A through DX-I)** | **User-accepted** | P1, P5 | Cross-phase: 30-min claim depends on DX |
| 12 | DX-2 | Add DX-B dev mode | Auto | P1 | Both voices: table stakes |
| 13 | DX-3 | Add DX-D CHANGELOG + DeprecationWarning | Auto | P5 | Both voices: A1 default flip needs migration story |
| 14 | DX-4..7 | Add env vars, CLI, README, errors | Auto | P1, P5 | Both voices |
| 15 | DX-8 | **Add Workstream F (compliance reviewer dashboard)** | **User-accepted** | P1 | Wedge delivery vehicle |
| 16 | C0 | Add pilot charter as pre-W1 gate (=#4) | — | — | — |
| 17 | C2 | Move vendor audit to May 13 | Auto | P1 | Both voices: critical-path item disguised |
| 18 | User | **Add Workstream E (Clerk auth migration)** | **User-initiated** | P3 (pragmatic), P5 (explicit) | Pre-customer = zero migration cost; enables F cleanly |
| 19 | E vs API keys | Keep API keys for SDK, Clerk for humans | Auto | P5 | Different auth surfaces; machine vs human |
| 20 | C5 | Move customer alignment call to W1 | Auto | P1 | Both voices: surface scope drift early |

---

## Success criteria (revised)

### Code
- [ ] Sync `@audit` decorator adds < 1ms p99 latency at default config when Vera is healthy
- [ ] Sync `@audit` decorator adds < 5ms p99 latency when Vera is hard-down
- [ ] No Vera-originated exceptions propagate out of `@audit` or `@async_audit` wrappers
- [ ] Records survive Vera outages (A5 SQLite spool with SQLCipher encryption)
- [ ] Fork-safety verified (`os.fork`, `multiprocessing.Pool`, gunicorn preload)
- [ ] Poison-batch handling: 4xx drops, 5xx retries with backoff+jitter
- [ ] `Redactor.medtech(schema=...)` deny-by-default; round-trips synthetic patient encounter to zero PHI leakage

### Legal/compliance
- [ ] **C0 pilot charter / design-partner agreement signed by May 13** (gates rest of plan)
- [ ] BAA signed with medtech pilot customer
- [ ] BAAs signed with all subcontractors that touch PHI (or Postgres migrated to AWS RDS)
- [ ] 4 policy docs in `compliance/policies/`
- [ ] Both founders HIPAA-trained (certificates filed)
- [ ] Customer alignment call complete (W1); pilot scope agreed in writing

### DX
- [ ] DX scorecard: ≥ 7/10 overall (currently ~3/10)
- [ ] TTHW < 5 minutes from `pip install` to first record visible (real new dev test)
- [ ] CHANGELOG + MIGRATION.md exist
- [ ] `vera` CLI ships with `config show` / `ping` / `tail`
- [ ] `vera.init()` + `VeraClient.dev()` + branded exceptions all shipped
- [ ] CI/CD on PyPI: pytest matrix + auto-publish on tag

### Auth
- [ ] Clerk integration ships; new dashboard signups go through Clerk
- [ ] Clerk roles: admin / developer / compliance_reviewer enforced on all dashboard routes
- [ ] API keys still work for SDK; issued via Clerk-authenticated dashboard
- [ ] `/v1/register` deprecated → 410 Gone with migration message

### Compliance UX
- [ ] `/compliance` dashboard route live; compliance_reviewer role can land and use without help
- [ ] Saved-view URLs shareable
- [ ] One-click PDF export works end-to-end
- [ ] Audit-of-audit-log captures all compliance_reviewer actions

### Outreach
- [ ] 20+ outbound discovery calls completed (5/week × 4 weeks)
- [ ] 2nd pilot candidate identified by May 31

### Collateral
- [ ] Zero "tamper-proof" / "court-admissible" / "policy engine" in customer-facing copy
- [ ] usevera.xyz/maturity page ships
- [ ] "First customer" → "design partner" framing used everywhere

---

## Out of scope (deferred)

- Policy engine rebuild (post-pilot)
- SOC 2 Type II (Q4 2026)
- HITRUST (2027)
- Self-host / VPC deployment (per strategy.md, July target)
- Insurance flywheel work (Act 2)
- Frontend dashboard improvements beyond F (general polish, design system work)
- New framework integrations beyond OpenAI/Anthropic/LangChain/CrewAI
- OIDC/SAML SSO (Clerk supports it; defer until enterprise customer asks)

---

## Effort summary

| Workstream | Effort | Owner |
|---|---|---|
| A (SDK) | 8–10 dev-days | Priyansh |
| B (Redaction) | 3–4 dev-days | Priyansh |
| C (BAA + legal) | Founder time, $3-5K legal | Both |
| D (Outreach + Collateral) | 30%/founder/week | Both |
| DX | 6–8 dev-days | Priyansh |
| E (Clerk) | 5 dev-days | Priyansh |
| F (Compliance dashboard) | 5 dev-days | Priyansh (some Advik on UX) |

**Total dev-days:** ~30 (one engineer × 4 weeks). Tight but feasible if D0 outreach stays on Advik primarily.

---

## What's in v2 / post-pilot

After June 13 pilot start:
- Real policy engine (customer-defined predicates over action fields)
- SOC 2 Type II prep
- Self-host / VPC deployment for fintech buyers
- 2nd pilot conversion
- Series Pre-seed conversation
- Insurance carrier data-sharing pilot conversation
