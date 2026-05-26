# Vera v1 — Test Plan

**Generated:** 2026-05-21 via /autoplan Phase 3 (Eng Review)
**Updated:** 2026-05-22 with Merkle proof exposure test cases (Phase 3)
**Pairs with:** [v1-implementation-plan.md](v1-implementation-plan.md)

This is the test plan that closes the gaps surfaced by the eng review. Each NEW codepath in each phase maps to a specific test; the rightmost column flags gaps in the original plan's test gates.

## Phase 1 — Capture + Customers

| Codepath | Test | Coverage |
|---|---|---|
| Tenant precedence: explicit kwarg > context manager > middleware default | unit test: middleware sets tenant=A, kwarg=B → record has tenant=B; middleware=A, no kwarg → tenant=A; context manager + kwarg → kwarg wins | gap in plan |
| Tenant resolver under thread-pool worker (FastAPI BackgroundTasks) | integration test: middleware sets tenant in async req, decorator runs in `BackgroundTasks` callback → record has correct tenant (currently broken — contextvars don't propagate) | gap |
| Tenant `tenant_id` validation `^[a-zA-Z0-9_-]{1,64}$` | unit: malformed strings rejected with 4xx | covered |
| PHI-shape heuristic rejects in production key, warns in sandbox key | unit: `tenant_id="John Doe DOB 1972"` → 4xx with `al_live_*`, warn with `al_test_*` | gap (plan only had warn) |
| Auto-discover creates placeholder Customer row | integration: SDK call with new tenant_id → Customer row appears with `status=pending_setup` | covered (smoke) |
| metadata_ hash contract for new 5 fields | unit: same record with/without metadata_ keys yields different hash predictably; canonicalization is stable | gap |
| API key sandbox vs live BAA enforcement | integration: `al_live_*` without signed BAA → 403; `al_test_*` always works | gap |
| Promoted columns `tenant_id`, `domain`, `action_class` (per F3 fix) | migration test: rollback + forward; backfill from existing records works | gap |
| Cross-org tenant_id collision warning | integration: org A has `tenant_id=abridge`; org B fires action with `tenant_id=abridge` → no leak, warning surfaced | gap |
| CSV bulk import (if kept — see CEO finding #11) | integration: upload 25-row CSV → all rows create Customers; malformed CSV rejected with line-level errors | partial |

## Phase 2 — Gates + HITL via webhook

| Codepath | Test | Coverage |
|---|---|---|
| Gate 1 — new diagnosis triggers REQUIRE_HITL | integration: scribe payload with `new_diagnoses=[...]` → webhook fires with `required_role=attending_physician` | covered |
| Gate 2 — controlled substance via RxNorm/DEA lookup | integration: payload with Schedule II med → webhook with `required_role=dea_licensed_physician`; non-scheduled med → no HITL | covered |
| Gate 3 — stale BAA hard block | integration: org BAA expired → SDK raises `PolicyBlock` immediately, no webhook | covered |
| Strictest gate wins (BLOCK > REQUIRE_HITL > ALLOW) | unit: payload triggering all 3 → effect == BLOCK | covered (Wave 2B PR A2 #214 — reducer in `backend/app/services/gates/reducer.py` + `backend/tests/test_gates_reducer.py`) |
| **Webhook delivery — durable retry queue** (per F1 fix) | integration: receiver returns 5xx → retry after 1m, 5m, 30m, 2h, 8h, 24h; persist across process restart | covered (Wave 2B PR A3 #215 — new `webhook_deliveries` / `webhook_delivery_attempts` tables + sweeper in `backend/app/services/webhook_sweeper.py` + `backend/tests/test_webhook_sweeper.py`) |
| Webhook idempotency on `review_id` | integration: same review_id posted twice → first canonical, second logged as duplicate | covered (Wave 2B PR A3 #215 — composite `idempotency_key` + unique index `(subscription_id, idempotency_key)` in migration `r8m0n1o2p3q4_add_webhook_delivery_tables`) |
| Attestation conflict (second callback different decision) | integration: review_id approved, then second callback with decision=reject from different reviewer → logged as `attestation_conflict`, first stays canonical | covered (Wave 2D PR A6) |
| Atomic approval transaction (Wave 2D A6.5 follow-up) | unit: monkey-patch `_resolve_and_record` mid-flow → vote + chain record + status flip all roll back; monkey-patch chain write → same; happy path → vote + status + chain record all commit atomically. Closes Codex /review finding from A6 #224 (lock released mid-flow on Postgres). | covered |
| Reviewer role mismatch 403 | integration: callback attesting MD-only for DEA gate → 403 `reviewer_credentials_insufficient`, logged | covered |
| Concurrent callbacks race (two reviewers click Approve simultaneously) | integration: 2x parallel callbacks on same review_id → exactly one wins; row-level lock or unique constraint enforces | covered (Wave 2D PR A6 — `SELECT … FOR UPDATE` in `services/reviews.complete_review` serialises on Postgres; SQLite single-threaded driver makes the second caller observe the resolved row) |
| Callback timestamp validation | unit: `decided_at` 2h in future → 400; `decided_at` older than `requested_at + expiry` → 400 with `review_expired` | covered (Wave 2D closeout — `ReviewCompletionInput.decided_at` validation in `backend/app/services/reviews.py::complete_review` + tests in `backend/tests/test_callback_timestamp_validation.py`) |
| `review.expired` callback fires at expiry | integration: review unanswered for 4h → Vera POSTs `review.expired` to customer webhook | covered (Wave 2B PR A3 #215 — sweeper `_sweep_expired_approvals` in `backend/app/services/webhook_sweeper.py` + dispatch in `approvals._resolve_and_record` + tests in `backend/tests/test_approval_expiry_sweeper.py`) |
| Real-time mode latency | benchmark: `realtime=True` ALLOW path <10ms p99; HITL path returns `REQUIRE_DEFERRED_REVIEW` immediately, action proceeds | covered (Wave 2C PR B2 #221 — `sdk/tests/test_gate_latency_regression.py` covers p99 < 25ms / p50 < 5ms on the SDK gate fast path) |
| Pack-not-installed warning | integration: org with no pack → calls return ALLOW with warning header + dashboard banner; PDF generation blocked until pack installed | gap (deferred — `stale_baa.applies()` is always True today, so the "no gate fired" path is unreachable until a real per-org pack registry exists in Phase 5+) |
| SSRF on webhook URL | security test: registered URL `http://169.254.169.254/...` → outbound blocked at delivery time, customer warned | covered (Wave 2D B3 — `backend/app/services/webhook_url_validation.py::is_safe_outbound_url` blocks RFC 1918 / loopback / link-local / cloud metadata / non-http(s) at registration time (400 `ssrf_blocked`) and re-checks at delivery time in `services/webhooks._attempt_delivery`; tests in `backend/tests/test_webhook_ssrf_guard.py`) |
| Slack channel signature verification (if kept) | unit: Slack callback with wrong signing key → 401 | gap |
| Approval pipeline migration (per F2) | migration test: existing polling Approvals continue working; new Review records flow through callback model; no double-counting | gap |
| **Customer decisions feed — server-side join** (Wave 2C PR C1.5) | integration: `GET /v1/customers/{tenant_id}/decisions` joins ActionRecord ⋈ Approval ⋈ latest WebhookDelivery (idempotency_key prefix `"{approval_id}:"`) server-side; response carries Ruling from `Approval.context`, derived webhook status (`succeeded→delivered`, `pending+attempt>1+next_retry→retrying`), and `hitl_expires_at` only while pending; 404 for unknown tenant + cross-org isolated. ALLOW rulings remain `null` pending SDK denormalisation. | NEW (covered) |
| Review queue Recommendation card scaffold (Wave 2D C4) | typecheck/contract test: `ReviewRecommendations` component renders empty in Phase 2 (no API yet); `loading | empty | populated` state machine + `ReviewRecommendation` / `ReviewRecommendationsResponse` types match the Phase 4 §A6 AI Insights endpoint contract; `onApply` callback shape ready for Phase 4 task-creation wiring | covered |
| Review queue page — alt channel for HITL completion (Wave 2D C2) | integration: load `/compliance/reviews` → table lists all pending approvals across the org with filter-by-customer/gate/role; click row → Pattern B detail panel; submit Approve/Modify/Reject with required ≥10-char comment → POST `/v1/reviews/{review_id}/complete` succeeds (200); 403 surfaces "role insufficient" inline; 404/409 surface "already decided / no longer available" + auto-close; 410 surfaces "expired" + auto-close; gate-pack-provided `fix_url` is rendered as clickable only for http/https schemes (javascript:/data: rendered as inert text); full HITL loop completes end-to-end via dashboard with no customer webhook involved. | covered |
| Dashboard PHI redaction (W1.2 — HIPAA minimum-necessary) | unit + integration: dashboard responses (Clerk session) strip PHI from Approval.context + Decision rows + ActionRecord.input_data; SDK responses (API key) preserve full shape for in-band callers | covered |
| Local dev org provisioning (W1.6 — v1-register-removed) | integration: POST /v1/dev/orgs creates org + admin key in dev mode; returns 404 in production; raw key authenticates immediately | covered |
| Org name uniqueness (W1.6 — two-scribemd-orgs) | migration: UNIQUE constraint on organizations.name; duplicate insert raises IntegrityError | covered |
| Bootstrap key/org validation (W1.6) | unit: bootstrap warns when env_file key authenticates against different org than expected slug | covered |

## Phase 3 — Off-Vera checkpoint + offline verify

| Codepath | Test | Coverage |
|---|---|---|
| Daily KMS-signed checkpoint export to customer S3 | integration: configure customer bucket → next checkpoint lands; checkpoint contains hash + signature + key_id | covered |
| `vera verify` against Vera's public key | integration: known-good hash → OK; tampered hash → FAIL | covered |
| `vera verify --offline` against customer S3 + OTS | integration: Vera API blocked at firewall → verify passes using only S3 + OTS proof | covered |
| Offline verify with tampered ActionRecord | integration: modify one record in DB copy → offline verify identifies broken link | covered |
| OpenTimestamps calendar server unreachable | integration: block OTS calendar URLs → checkpoint write succeeds; `.ots` proof retries async; dashboard shows "anchor pending" | gap |
| KMS key rotation mid-chain | integration: rotate key between checkpoint N and N+1 → `vera verify --offline` consults key history and verifies both | gap |
| Customer S3 trust revoked mid-flight | integration: revoke trust → next checkpoint fails gracefully, dashboard surfaces error, Vera-internal checkpoint still succeeds | gap |
| Customer S3 ARN mistyped | integration: invalid bucket → onboarding flow rejects at setup, not at first checkpoint | gap |
| **Checkpoint cadence configurable** | unit: org with `cadence=hourly` produces 24 checkpoints/day; `cadence=daily` produces 1. Default for `al_test_*`=daily, `al_live_*`=hourly. | NEW — Merkle addition |
| **Merkle proof generation — happy path** | integration: pick a record from a closed checkpoint window; `GET /v1/records/{id}/merkle-proof` returns valid `MerkleProof` + signed checkpoint metadata; `verify_proof()` against the returned root succeeds. | NEW |
| **Merkle proof — record in pending checkpoint window** | integration: record written in current window (no checkpoint yet) → endpoint returns 409 `checkpoint_pending` with `Retry-After` header matching cadence. | NEW |
| **`vera verify --merkle-proof` — happy path** | integration: proof file downloaded from endpoint → CLI verifies offline against customer S3 mirror's KMS public-key history; exit 0. | NEW |
| **`vera verify --merkle-proof` — tampered leaf** | unit: flip a bit in `leaf_hash` → verification fails with `merkle_proof_invalid`; exit 1. | NEW |
| **`vera verify --merkle-proof` — tampered sibling** | unit: flip a bit in `proof_hashes[i]` → verification fails. | NEW |
| **`vera verify --merkle-proof` — wrong root** | unit: replace `root` with a different valid checkpoint root → verification fails (root mismatch). | NEW |
| **`vera verify --merkle-proof` — bad KMS signature** | unit: keep proof valid but tamper KMS signature → verification fails with `signature_invalid`. | NEW |
| **Merkle proof — power-of-2 padding edge case** | unit: build tree from 1, 2, 3, 5, 7, 9, 1023, 1024, 1025 leaves; every leaf's proof verifies; padding via last-leaf duplication (per [merkle.py:69-70](backend/app/services/merkle.py:69)) doesn't corrupt proofs. | NEW |
| **Merkle proof — single-record checkpoint** | unit: checkpoint with exactly 1 record → root == leaf hash, proof has empty `proof_hashes` list, verification passes trivially. | NEW |
| **Per-decision evidence PDF includes proof.json attachment** | integration: generate per-decision evidence PDF; open in Acrobat; `proof.json` is an embedded PDF attachment; extracted JSON validates via `vera verify --merkle-proof`. | NEW |
| **Audit PDF Scope page references checkpoint root** | integration: generate audit PDF for a customer; Scope page contains "Each decision … verifiable against checkpoint root `<short hash>`" with the actual short hash of the relevant checkpoint root. | NEW |
| **Selective disclosure CLI** | integration: `vera evidence-export --customer cleveland_clinic --since 2026-06-01` produces an archive containing only Cleveland Clinic's records + their Merkle proofs. Other customers' records absent. Each proof verifies independently. | NEW |
| **Selective disclosure — verifier can't infer other customers** | integration: verifier with only the Cleveland Clinic export + the public checkpoint root cannot reconstruct or count any other customer's records (only sibling hashes are present, not other leaves). | NEW |
| **KMS rotation between checkpoints — proof still verifies** | integration: rotate KMS key between checkpoint N and N+1; proof for a record in N verifies via `vera verify --merkle-proof` using the key history table (per Eng F10). | NEW — cross-references KMS rotation test |
| **Hash chain still independently valid** | regression: existing chain verification continues to pass for the same records; Merkle exposure is additive, not replacing the chain. | NEW |
| **OTS anchor on Merkle root** | integration: with OTS opt-in enabled, checkpoint's Merkle root is the OTS-anchored value (not the chain head); `vera verify --merkle-proof --include-ots` validates the OTS proof against the same root. | NEW |

## Phase 4 — Audit PDF + Compliance Posture + AI Insights

| Codepath | Test | Coverage |
|---|---|---|
| Audit PDF — happy path | integration: generate for customer with ≥100 decisions, ≥10 HITL, signed BAA → opens in Acrobat, sections in OCR order, verify URL works | covered |
| PDF — white-label cover with customer logo | integration: upload SVG logo → cover renders crisp; PNG → also crisp | covered |
| PDF — Vera-neutral branding | integration: select Vera-neutral → placeholder cover, customer name retained in body | covered |
| **PDF async job model (per F6 fix)** | integration: `POST /v1/audits` returns 202 + job_id; `GET /v1/audits/{job_id}` polls until done | gap |
| PDF timeout / ReportLab crash | integration: inject ReportLab failure → modal shows error state with retry CTA + support copy | gap |
| PDF blocked: BAA expired | integration: BAA expired for Customer → modal shows blocked state with deep-link to renew | gap (per design finding #3) |
| PDF partial-data warnings | integration: low HITL volume → PDF generates with "insufficient data for section X" inline warning | gap |
| PDF concurrency cap (30+ concurrent renders) | load test: 50 concurrent PDF generations → queue depth visible, no worker pinning | gap |
| Posture math at 1M actions | load test: 30-day posture aggregation completes <500ms via snapshot table | gap |
| Posture snapshot freshness | integration: snapshot updated every 5 min via cron; Home page reads snapshot | gap |
| Posture insufficient-data guards | unit: <10 HITL events → "insufficient data, see raw counts"; ≥10 → score | covered |
| Posture asymmetric layout (per design finding #4) | UI test: customer with 2 measured + 4 awaiting dimensions → composite headline + 2 prominent cards + 4 collapsed row | gap |
| AI Insights — Show insights button | integration: click → Haiku call → 3-5 cards render with severity pills | covered |
| AI Insights "Apply" no-side-effect | integration: click Apply → task created, no mutation of action records or posture | covered |
| Generated PDFs history — both surfaces | UI test: PDF appears in both Customer detail history and Compliance roll-up | gap |

## Phase 5 — Templates + Wizard

| Codepath | Test | Coverage |
|---|---|---|
| 5-question wizard happy path | integration: complete cold → templates generate, BAA draft offered | covered |
| Wizard abandonment + resume | integration: abandon mid-wizard → "Resume setup" banner on Home until complete; SDK traffic still flows | gap |
| Template attestation gate | integration: try to mark counsel-reviewed without checkbox → blocked; tick + submit → sign-off persists with timestamp | covered |
| Re-edit template after attestation | integration: edit signed template → attestation resets, must re-attest | covered |
| Conditional jurisdiction clauses (CA AB 489, TX TRAIGA, UT AIPA) | integration: select CA → AB 489 clause appears; deselect → removed | covered |

## Phase 6 — Home + Polish

| Codepath | Test | Coverage |
|---|---|---|
| Home — Things that need you | UI test: pending reviews, expiring BAAs, webhook failures, unattested templates render correctly | covered |
| Home — Generate-PDF shortcut (per design finding #1) | UI test: shortcut visible; click → modal opens | gap |
| Home — empty state | UI test: no pending items → status dot ok-green only, no other chrome | covered |
| Slack channel — install flow | integration: complete OAuth → workspace tokens encrypted, scoped to chat:write + commands only | gap |
| Slack callback signature verification | unit: bad signature → 401 | gap |
| Slack workspace token revoked | integration: revoke token → next callback fails gracefully, dashboard surfaces error | gap |
| Email channel (if added per CEO finding #9) | integration: digest at 9am UTC contains last 24h pending reviews | gap |
| Keyboard-only navigation | a11y test: tab through all pages; focus rings visible; modals trap focus + restore | covered |
| WCAG AA contrast | a11y test: ink-on-paper, ink-2-on-paper at body size | covered |

## Cross-cutting

| Codepath | Test | Coverage |
|---|---|---|
| Migration rollback | each phase: alembic downgrade → schema reverts cleanly; data preserved | gap |
| Feature flags | per-phase: env var disables behavior; old behavior intact | gap |
| Postgres unavailable | chaos test: kill primary mid-write → SDK spool buffers; recovery replays | gap (acceptable for v1 per F16 if documented) |
| KMS unavailable when signing checkpoint | chaos test: KMS 500s → checkpoint deferred to retry queue, surfaced on Home | gap |
