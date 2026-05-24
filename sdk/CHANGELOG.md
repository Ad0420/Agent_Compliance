# Changelog

All notable changes to `vera-sdk` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `vera review-status <review_id>` now fetches a real approval via
  `GET /v1/approvals/{id}` and renders it as a human-readable summary
  (or raw JSON with `--json`). Supports `--watch` to poll until the
  approval reaches a terminal state, `--interval` (default 5s, min
  0.5s, max 60s) to tune cadence, `--timeout` to bound watch duration,
  and `--no-color` (honors `NO_COLOR`). Watch + JSON emits NDJSON
  suitable for `jq -c` pipelines.
  Exit codes: 0 ok, 1 not-found, 2 transport, 3 watch-timeout,
  130 Ctrl-C. (Wave 2B PR B3 — replaces the Phase 1 PR 11 stub.)

## [1.0.0] - 2026-05-24

### Stable release
- First stable cut of the Vera SDK. The public API surface is now under
  semver: no breaking changes will land until 2.0.0. `vera-sdk<1` users
  who want to stay on the pre-rename surface should pin `vera-sdk>=0.3,<1`
  (the final 0.3.x release is the deprecation patch, `0.3.1`).
- Public surface (frozen until 2.0.0): `vera.init`, `vera.init_async`,
  `vera.init_async_awaitable`, `vera.get_client`, `vera.get_async_client`,
  `vera.VeraClient`, `vera.AsyncVeraClient`, `vera.gate`,
  `vera.audit` (legacy alias — emits DeprecationWarning, removal in 2.0.0),
  `vera.is_bypassing_gates`, `vera.set_default_client`,
  `vera.set_default_async_client`,
  `vera.async_audit` (legacy alias — codemod rewrites to `@vera.gate`,
  removal in 2.0.0; no runtime warning today),
  `vera.Redactor`, `vera.set_default_redactor`, `vera.get_default_redactor`,
  `vera.tenant`, `vera.set_tenant`, `vera.reset_tenant`, `vera.get_tenant`,
  `vera.get_default_tenant`, `vera.set_default_tenant`, `vera.resolve_tenant`,
  `vera.copy_context_to_thread`, `vera.set_default_agent_type`,
  `vera.get_default_agent_type`, `vera.resolve_agent_type`,
  `vera.VeraError`, `vera.VeraAuthError`, `vera.VeraRateLimitError`,
  `vera.VeraServerError`, `vera.VeraTimeoutError`, `vera.VeraNetworkError`,
  `vera.VeraValidationError`, `vera.VeraClientError`, `vera.PolicyBlock`,
  `vera.PendingReview`, `vera.WrongKeyTier`, `vera.TenantMissingOrInvalid`,
  `vera.ReviewerCredentialsInsufficient`,
  `vera.ApprovalRejectedError`, `vera.ApprovalTimeoutError`,
  `vera.middleware.VeraMiddleware`,
  `vera.testing.bypass_gates` (pytest fixture) + `vera.testing.bypass_gates_cm`
  (context-manager form),
  `vera.codemod` (with `[codemod]` extras).
- `Development Status` classifier promoted from
  `4 - Beta` → `5 - Production/Stable`.

### Added (since 0.3.0)
- `@vera.gate` decorator with synchronous Ruling routing
  (ALLOW / REQUIRE_HITL / BLOCK) against the backend `/v1/gates/evaluate`
  endpoint, including a 404 fallback to legacy audit-only capture so
  the decorator ships today and auto-graduates when Phase 2 lands
  (Phase 1 PR 8 / #203).
- Tenant resolver with four-source precedence — explicit kwarg >
  context manager > middleware > process default — plus
  `vera.middleware.VeraMiddleware` for FastAPI/Starlette and
  `vera.copy_context_to_thread` for thread-pool propagation
  (Phase 1 PR 7 / #200).
- 12-error catalog: 5 new branded errors (`PolicyBlock`, `PendingReview`,
  `WrongKeyTier`, `TenantMissingOrInvalid`,
  `ReviewerCredentialsInsufficient`) on top of the existing 7
  transport-layer errors (`VeraError`, `VeraAuthError`,
  `VeraRateLimitError`, `VeraServerError`, `VeraTimeoutError`,
  `VeraNetworkError`, `VeraValidationError`) (Phase 1 PR 6 / #194).
- `vera codemod audit-to-gate` LibCST migration tool. Renames imports,
  decorators, and kwargs in a single pass with `--dry-run`, `--check`
  (CI gate, exit codes match ruff), `--wrap-callsites` (opt-in
  try/except scaffold), and a `# noqa: VERA-CODEMOD` per-file opt-out.
  Install via `pip install vera-sdk[codemod]` (Phase 1 PR 9 / #208).
- `vera.testing.bypass_gates` pytest fixture + `bypass_gates_cm`
  context-manager form so pilot test suites don't need an httpx
  `MockTransport` for every gate (Phase 1 PR 8 / #203).
- `vera.init(agent_type=...)` kwarg + `vera.set_default_agent_type` /
  `get_default_agent_type` / `resolve_agent_type` helpers. The
  resolved `agent_type` is stamped onto every `@vera.gate` outgoing
  payload (Phase 1 PR 8).

### Changed (since 0.3.0)
- `@vera.audit` is now a deprecated alias for `@vera.gate`. The
  decorator continues to work; the first invocation per call site
  emits a `DeprecationWarning` pointing at `@vera.gate` and the
  `vera codemod audit-to-gate` tool. Removal scheduled for 2.0.0.
- `libcst` is an optional extra (`[codemod]`) — saves ~15MB on
  installs that don't run the codemod (most SDK consumers).
- `VeraAuthError.code` renamed `auth` → `invalid_api_key`;
  `VeraTimeoutError.code` and `VeraNetworkError.code` collapsed to
  `gate_timeout_or_network`. Realigns the SDK with the 12-class
  catalog documented in `docs/error-discipline.md`. Constructor
  signatures, `except` matching, and the `VeraError` base class are
  all unchanged — only the `code` value (and therefore the `docs_url`
  suffix in `str(err)`) changed. A one-shot `DeprecationWarning`
  carries the old → new mapping the first time `str(err)` runs on
  each renamed class.
- Backend behavior change visible in the SDK: API keys minted with
  `kind="live"` now require an active BAA on the org. Callers without
  one get HTTP 403 `baa_required` (at mint time) or `baa_expired`
  (per-request gate). Routed through `wrap_httpx_error` →
  `PolicyBlock` — `except PolicyBlock` already catches it, no client
  code changes required.

See the [1.0.0 migration guide](MIGRATION.md) for upgrade steps.

## [0.3.1] - 2026-05-24

### Added
- `DeprecationWarning` emitted by `@vera.audit` pointing users at
  `@vera.gate` and `vera codemod audit-to-gate`. This is a NO-OP
  functionally — the alias continues to capture `ActionRecord`s with
  the legacy semantics. Purpose: give existing pilots a visible
  warning on the 0.3 line BEFORE they upgrade to 1.0.0, so the move
  is intentional rather than surprise-on-pin. The warning fires once
  per call site (deduped on `(filename, lineno)`) so a large codebase
  with hundreds of `@vera.audit` call sites produces one warning per
  site, not one per call. `@vera.async_audit` does NOT emit a
  warning in `0.3.1` — pilots on `async_audit` should still run the
  codemod and migrate to `@vera.gate`.
- This release is intentionally identical to `0.3.0` plus the
  DeprecationWarning. Pilots who can't move yet should pin
  `vera-sdk>=0.3,<1`; the warning will guide them through the move
  on their own timeline.

### Deprecated
- `@vera.audit` — renamed to `@vera.gate`. Run
  `vera codemod audit-to-gate` to migrate automatically. Removal
  scheduled for `2.0.0` (per the `removed_in="2.0.0"` annotation
  on the alias and the `_AUDIT_DEPRECATION_MESSAGE` constant in
  `vera/decorator.py`).

## [Pre-1.0 changelog — historical detail kept for reference]

### Behavior change (backend-driven)
- API keys minted with `kind="live"` now require an active BAA on the org.
  Previously this field was silently dropped on the backend; now it's honored
  and gated. Callers without a BAA get HTTP 403 `baa_required` (at mint time)
  or `baa_expired` (per-request gate). Sandbox keys (`kind="test"`, the
  default) are unaffected. The structured error envelope is now emitted at the
  top level of the response body (`{"code": "baa_required", "fix_url": ...}`)
  so the SDK's `wrap_httpx_error` dispatches to `PolicyBlock` via
  `CODE_TO_ERROR_CLASS` without an SDK release. No client code changes
  required — `except PolicyBlock` already catches it.

### Breaking (log surface only)
- `VeraAuthError.code` is now `invalid_api_key` (was `auth`); `VeraTimeoutError.code`
  and `VeraNetworkError.code` are now `gate_timeout_or_network` (were `timeout` and
  `network`). This realigns the SDK with the 12-class catalog documented in
  `docs/error-discipline.md`. Constructor signatures, `except` matching, the
  `VeraError` base class, and `to_dict()` field names are all unchanged — only
  the `code` value (and therefore the `docs_url` suffix that appears in
  `str(err)`) changed. **Update any log-grep / alerting that matches
  `errors/auth`, `errors/timeout`, or `errors/network` URL substrings to the
  new slugs.** The first call to `str(err)` on each renamed class in a process
  emits a one-shot `DeprecationWarning` carrying the old → new mapping so
  pilots see the change in CI before it shows up in alert noise.

### Documentation
- README expansion (Phase 4b DX-G + B2). The README is now a reference doc
  instead of a quickstart-only file. New sections:
  - 5-minute quickstart with signup, install, init, verify, and dashboard
    steps.
  - Concepts section for `vera.init()`, `@audit`, `Redactor`, dev mode,
    durable spool, and branded errors.
  - Four framework cookbooks (OpenAI, Anthropic, LangChain, CrewAI), each
    with a minimal and a realistic example plus an example audit-record
    JSON.
  - HIPAA and medtech section covering the 18 PHI Safe Harbor identifiers,
    opaque vs MRN-shaped patient IDs, free-text PHI handling, custom block
    keys and patterns, and the durable-spool encryption-at-rest requirement.
  - Environment variables table covering every `VERA_*` env var the SDK
    reads.
  - Command-line interface section with `vera config show`, `vera ping`
    (with exit codes), and `vera tail` (with `--follow`, `--json`, `jq`
    pipelines).
  - Troubleshooting section with the 11 most common errors and resolutions.
  - HTTP API reference link.

### Added
- `vera` command-line interface (Phase 4a DX-F) with three subcommands:
  - `vera config show` — print the effective configuration (env vars +
    defaults). API key is masked by default; pass `--reveal-secrets` to
    print it in full.
  - `vera ping` — verify the API key authenticates against the
    `/v1/verify` endpoint. Reports latency in ms.
  - `vera tail` — tail recent records for the org via `query_actions`.
    Supports `--agent`, `--result`, `--follow`, `--interval`, `--json`,
    and `--limit` (clamped to 500).

  Entry point registered in `pyproject.toml` as `vera = "vera.cli:main"`.
  Uses Click — `click>=8.0` is now a **runtime dependency** so the CLI
  works out of the box after `pip install vera-sdk` (no extra needed).
- `vera.init(api_key=..., agent_name=...)` Sentry-style one-call setup.
  Constructs a `VeraClient` from explicit kwargs + env vars and registers it
  as the default for `@audit` decorators. Calling `init()` twice replaces
  (and drains) the previous default.
- `vera.init_async(...)` for the async equivalent.
- `vera.get_client()` / `vera.get_async_client()` to retrieve the
  initialized client(s).
- `VeraClient.dev()` factory and `VERA_DEV=1` env var for dev mode (prints
  records to stderr instead of POSTing). Returns a `DevClient` subclass
  whose `record_action` / `enqueue_action` route through an in-memory
  `_StderrSink` after running the same `_build_payload` + redactor path as
  the production client. No API key required.
- pytest fixture `vera_sdk_recording` (auto-loaded via the `pytest11`
  entry point). Yields the underlying sink so tests can assert on captured
  audit records without HTTP mocks. Echo disabled by default so test
  output stays clean. Renamed from `vera_recording` in this release to
  reduce collision risk with customer fixtures named `recording`. The
  fixture teardown also no longer clobbers an in-test `vera.init(...)`
  call — if the test replaces the default client mid-test, the fixture
  respects that choice instead of restoring the entry-default.
- `vera.init_async_awaitable(...)` — async-aware variant of
  `vera.init_async()` that properly `await`s `previous.close()` when
  replacing an existing client. Prefer this in long-running async services
  where re-init must not drop in-flight records. The sync `init_async()`
  still exists for startup-only use and now WARNs loudly when it replaces
  a previous client (since it can't await close()).
- Dev mode safety rails: WARN log line `[vera-dev-001]` plus stderr banner
  on construction so accidental `VERA_DEV=1` in prod is visible
  immediately. `DevClient` refuses to construct when `api_key` looks like
  a production key (`al_live_*` prefix) unless `VERA_DEV_CONFIRM=1` is
  also set.
- `vera.init` is now thread-safe: concurrent callers serialise on a
  module-level lock during the handle-swap. Client construction itself
  runs outside the lock so slow init paths don't block other callers.
- `vera.get_client()` before `init()` now returns a sentinel that raises
  a `VeraError` with a helpful message on attribute access (instead of
  `None`). The sentinel is falsy, so `if vera.get_client():` still works.
- One-time INFO log on first `VeraClient` construction in a process,
  surfacing the resolved `api_url` / `agent_name` / spool state. Lets ops
  see where audit traffic is going.
- Env-var loaders in `VeraClient` and `AsyncVeraClient` constructors:
  `VERA_API_KEY`, `VERA_API_URL`, `VERA_AGENT_NAME`, `VERA_AGENT_VERSION`,
  `VERA_MODEL_ID`, `VERA_FRAMEWORK`, `VERA_SPOOL_PATH`. Explicit kwargs
  always win — including explicit empty string. Empty-string env vars
  still fall through to defaults. Semantic is now consistent across every
  arg (`None` means unset, anything else is explicit).
- README Quickstart that leads with `vera.init()` plus an env-var table
  and dev-mode + pytest fixture cookbook.

### Changed
- Default `api_url` changed from `"http://localhost:8000"` (self-host
  default) to `"https://api.usevera.xyz"` (SaaS default) when neither arg
  nor env is provided. Self-host customers should set `api_url=` or
  `VERA_API_URL` explicitly. All existing tests already pass explicit
  `api_url` so this is a no-op for the test suite; production self-host
  deployments need to update their config.
- `VeraClient.__init__` (and `AsyncVeraClient.__init__`) now WARN once when
  no API key is configured rather than silently shipping records with a
  blank `Bearer` header. The warning points at `vera.init(dev=True)` /
  `VERA_DEV=1` for development workflows.
- `record_action` payload construction extracted into `_build_payload()`
  so the dev-mode subclass can reuse the production identity-stamping
  logic without duplicating the field shape.
- `DevClient.record_action` now returns a dict matching the production
  shape (`status="success"`, `record_id`, `sequence_number`, `recorded_at`)
  plus a dev-only `mode="dev"` marker. Previously returned only
  `{"status": "dev", "record_id": ...}`, which made customer code that
  unpacked `sequence_number` KeyError only in dev.
- Dev mode (`DevClient`) now force-disables the durable spool, ignoring
  `VERA_SPOOL_PATH`. Inheriting the parent client's spool path was a
  HIPAA leak path: PHI written by a prior production process could be
  rehydrated from disk and echoed to stderr in a dev run. This is enforced
  via a new `_NO_SPOOL_SENTINEL` value passed to the parent constructor.

- Durable on-disk spool (`vera/spool.py`). When in-memory queue overflows, records
  spill to an encrypted SQLite spool instead of being dropped. Survives process
  restarts via `persistent_buffer_path` constructor param. Requires
  `VERA_SPOOL_KEY` env var for AES-256-GCM encryption at rest. WAL mode for
  multi-process safety. File mode 0600.
- New extra `pip install vera-sdk[spool]` adds the `cryptography` dependency.
- **Quarantine table for undecryptable rows.** When `Spool.dequeue_batch`
  encounters a row whose AES-GCM tag fails, the row is now MOVED (in one
  transaction) into the new `spool_quarantine_records` table rather than
  silently DELETED. A `SpoolDecryptionError` is raised carrying the affected
  ids. Behavior change vs. earlier releases — the old behavior destroyed the
  audit chain on key rotation. See `sdk/docs/spool-key-rotation.md` for the
  recovery procedure. New API: `Spool.list_quarantined()` and
  `Spool.quarantine_size()`.
- **Passphrase sentinel.** Every spool now writes an encrypted sentinel into
  `spool_metadata` at first init. Subsequent opens decrypt the sentinel and
  raise `SpoolPassphraseError` (a subclass of `SpoolDecryptionError`) when
  the passphrase doesn't match — even when the row table is empty. Catches
  operator typos at `VERA_SPOOL_KEY` rotation time before they become
  permanent.
- **`AsyncVeraClient` post-fork hook.** Mirrors the sync client: registers
  `os.register_at_fork(after_in_child=...)` (where available) to rebuild the
  `httpx.AsyncClient`, reopen the spool's SQLite connection, and clear the
  `id()`-keyed `_spool_row_map`. Without this, uvicorn workers /
  gunicorn+uvloop / anything that forks would inherit the parent's SQLite
  connection and corrupt the spool DB on the child's first write.
- `sdk/docs/spool-key-rotation.md` — operator-facing recovery procedure for
  the new quarantine behavior, plus the supported planned-rotation path.

### Changed
- When `persistent_buffer_path` is configured, enqueue overflow spills to spool
  rather than triggering drop-oldest. Drop-oldest remains the fallback when the
  spool is full or unconfigured.
- **`max_bytes` cap is now enforced under concurrency.** `Spool.enqueue` wraps
  the size-check + insert in a single `BEGIN IMMEDIATE` transaction so
  multiple producer threads (or processes sharing the spool file) can't all
  pass the check independently and exceed the cap by N batches. `_size_bytes`
  also now counts the WAL sidecar file in addition to the main DB pages.
  Documented as "strict within one process, best-effort within ±1 batch
  across processes" — cross-process accounting can race on the final commit.
- **Spool file mode race fixed.** Process umask is set to `0o077` BEFORE
  `sqlite3.connect`, so the `.db` (and any `.db-wal`/`.db-shm`/`.db-journal`
  sidecars) are created at `0o600` rather than the process default (often
  `0o644`, world-readable). Belt-and-suspenders explicit `chmod 0600`
  remains for any sidecar created later.
- **Per-record idempotency key is now on the wire.** The internal
  `_idempotency_key` (set at enqueue time, persisted to spool) is promoted
  into `metadata.record_idempotency_key` before the batch is POSTed.
  Previously the only idempotency signal on the wire was the batch header,
  which used the first record's key and could shift across restart-induced
  batch recomposition. The metadata-key approach lets the server dedupe per
  record. Additive — backend accepts arbitrary `metadata: dict` already.
- `_is_disk_full_error` now prefers Python 3.11's
  `sqlite3.Error.sqlite_errorcode` (locale-independent) over substring
  matching of the error message. Substring matching is retained as a 3.10
  fallback.

### Redactor.medtech() review fixes (PR #165)
- **Bare ``"patient"`` removed from ``_MEDTECH_BLOCK_KEYS``.** A kwarg
  named ``patient`` (e.g. ``def process(patient: PatientRecord)``) is no
  longer blocked wholesale — the redactor recurses so the schema's
  per-field rules apply at every depth. The schema's deny-by-default for
  unmapped fields still protects nested PHI. Customers who want the old
  wholesale behaviour can opt in via
  ``Redactor.medtech(extra_block_keys={'patient'})``.
- **``"patient_id"`` removed from ``_MEDTECH_BLOCK_KEYS``** to resolve
  the contradiction with ``medtech_starter_schema()`` (which marks it
  ``PASSTHROUGH``). Opaque, randomly-generated patient IDs ARE the
  HIPAA-safe pattern; preserving them keeps audit trails searchable.
  ``patient_name``, ``mrn``, ``medical_record_number`` remain in
  ``_MEDTECH_BLOCK_KEYS``. Customers whose ``patient_id`` is MRN-shaped
  should pass ``Redactor.medtech(extra_block_keys={'patient_id'})``.
- **Bare ``"url"`` removed from ``_MEDTECH_BLOCK_KEYS``.** API endpoints,
  callback URLs, doc links, and asset URLs are no longer destroyed. PHI
  embedded inside URL strings is now caught by a new ``url_phi`` regex
  pattern that matches URLs containing MRN, SSN, DOB, ``patient_id=``,
  ``ssn=``, or ``mrn=`` substrings in path/query.
- **Stable error code on the BAA reminder.** Log message now prefixed
  with ``[vera-baa-001]`` for SIEM filtering / mute rules.
- **Pattern caching.** ``_default_patterns()`` and ``_medtech_patterns()``
  now share an ``lru_cache``-backed compile step. Each call constructs
  a fresh list around cached, immutable ``re.Pattern`` objects, so hot
  code paths that instantiate per-request Redactors no longer pay the
  re-compilation cost.
- **``vera._test_hooks`` module** for the BAA-flag reset hook. Private
  by convention; not part of the SDK stability contract.
- **Headline round-trip test expanded** to cover nested dicts, lists of
  dicts, dataclass-style objects (schema-mode object refusal), and a
  FHIR-shaped Bundle. Substring-based PHI assertions run at every depth.

### Security / Reliability
- **Fork-safety:** `_after_in_child` now closes the inherited `httpx.Client`
  and creates a fresh one. Customers using `gunicorn --preload`, Celery
  prefork, or `multiprocessing.Pool` are no longer at risk of TCP
  connection corruption in worker children. Belt-and-suspenders pid-mismatch
  detection in `_init_runtime_state` rebuilds the client on platforms
  where `os.register_at_fork` doesn't fire.
- **AsyncVeraClient.enqueue_action** no longer raises `RuntimeError`
  (silently swallowed by the `@async_audit` sync-wrapper) when called from
  a sync context with no running event loop. Records remain queued for
  the next async caller. A single per-process WARN surfaces the misuse
  without spamming logs.
- **Concurrent `_flush` serialization:** added `asyncio.Lock` around
  `AsyncVeraClient._flush` to prevent interleaved `popleft` from racing
  the periodic flush_loop tick and the on-overflow `create_task`. Fixes
  split batches and double-POSTs under high enqueue throughput.
- **Permanent 4xx breaker:** `enqueue_action` now refuses to accept new
  records once the circuit breaker has opened due to persistent 4xx
  (e.g. bad API key). Surfaces a once-per-process ERROR. Transient 5xx
  behavior is unchanged — the queue is still the buffer for retry.
- **Branded error coverage:** `wrap_httpx_error` now handles
  `LocalProtocolError`, `DecodingError`, `TooManyRedirects`, `ProxyError`,
  `UnsupportedProtocol`, with a catch-all `VeraError` fallback for any
  unmapped `httpx.HTTPError`. The SDK no longer leaks raw httpx classes.
- **atexit lazy registration:** `VeraClient` registers `atexit` on first
  `enqueue_action` rather than at construction, eliminating per-instance
  hook leaks in long-running processes (notebooks, large test suites).
- **Idempotency keys persist across re-queues:** re-queued batches now
  retain their original `Idempotency-Key` (chosen at enqueue time, not
  flush time). Eliminates duplicate inserts when a retry succeeds after
  a previously-failed flush. Behavior change: customers with their own
  server-side dedupe MAY observe fewer duplicate writes than before.
- **Drop-oldest race fix:** the `get_nowait`/`put_nowait` pair on queue
  overflow is now wrapped in `_overflow_get_put_lock` so concurrent
  producers can't race into double-drops.
- **Close-time fallback flush:** `_flush_from_calling_thread` now
  acquires `_state_lock` for the get/post pair so a still-running daemon
  worker can't race close() into double-popping the same records.

### Added
- `Redactor.medtech()` one-call factory for HIPAA-aware redaction. Preloads the
  medtech starter schema, augments default `block_keys` with HIPAA Safe Harbor
  identifiers, and includes MRN/DOB/IP regex patterns by default. Emits a
  single INFO log on first use reminding customers to sign a BAA before
  sending PHI.
- Schema-driven redaction mode. `Redactor(schema=...)` with `Schema`,
  `FieldRule`, `FieldPolicy` types from `vera.redaction`. Deny-by-default
  for unmapped fields; PHI fields explicitly tagged. `Redactor.medtech_starter_schema()`
  provides a canonical patient-encounter schema as a starting point.
  Defense-in-depth: existing regex pass and `block_keys` still apply on
  top of schema rules.
- Default redaction patterns for MRN, DOB (multiple formats), IPv4/IPv6
  addresses. ICD-10 pattern is available via schema (`pattern_name="icd10"`)
  but intentionally excluded from the default regex pass — it collides
  with normal English text.
- Branded exception hierarchy in `vera.errors` (public API ahead of v0.4 client integration)
- Single-WARN on first `@audit` invocation when no Vera client is configured
- DeprecationWarning utility for orderly behavioral changes
- `CHANGELOG.md` and `MIGRATION.md`
- `VeraClient.enqueue_action()` for fire-and-forget recording from hot paths.
  Bounded in-memory queue (default 10,000) with a daemon background flush
  thread. Drop-oldest on overflow with a rate-limited WARN. Drains on
  `close()` and at interpreter exit (bounded by `atexit_drain_timeout`,
  default 10s). (workstream A1, A4, A9)
- Fork-safety on `VeraClient`: tracks `os.getpid()` and re-initialises queue
  + worker thread on first `enqueue_action()` call inside a forked child.
  Registers an `os.register_at_fork(after_in_child=...)` handler when
  available. Supported runtimes: gunicorn (preload + post-fork), uvicorn
  workers, Celery, multiprocessing pools. Best-effort warn-once detection
  for gevent monkey-patched threading. (workstream A7)
- Poison-batch handling on the background flush worker (sync + async):
  classify failures as permanent (4xx other than 429) — drop with ERROR —
  vs transient (429 / 5xx / network / timeout) — re-queue with backoff +
  jitter. Circuit breaker pauses flushing for an exponential cool-down
  capped at 60s after `circuit_breaker_threshold` (default 5) consecutive
  failures. Per-record re-queue cap (default 10) drops poison records
  before they burn CPU. (workstream A8)

### Operations notes
- **AsyncVeraClient.close():** MUST be awaited explicitly before process
  exit. `atexit` cannot reliably run async cleanup; records remaining in
  the queue at exit are logged but NOT flushed. For sync codepaths or
  any context where you can't guarantee an explicit `await client.close()`,
  use `vera.VeraClient` (sync) — the sync client's atexit drain is reliable.
- **AWS Lambda:** explicitly call `client.close()` in the handler shutdown
  path. Long Lambda freezes between invocations may invalidate connection
  state — the safest pattern is to construct the client at handler init
  for cold-start safety and close it at end-of-invocation.
- **Re-queue ordering:** the sync (`queue.Queue`) and async (`deque`)
  paths use slightly different re-queue ordering — sync FIFO (re-queued
  records go to the back), async LIFO-ish (re-queued records go to the
  front via `appendleft`). Documented for visibility; will be unified in
  v0.5.

### Changed
- Default HTTP timeout reduced from 30s to 5s for fail-fast semantics
- `@audit` and `@async_audit` decorators now use `enqueue_action()`
  internally so customer code paths never block on Vera availability.
  Direct callers of `record_action()` retain the original blocking +
  ack semantics (no silent default flip). (workstream A1, A9)
- `_request_with_retry` now raises branded exceptions from `vera.errors`
  (`VeraAuthError`, `VeraRateLimitError`, `VeraServerError`,
  `VeraTimeoutError`, `VeraNetworkError`, `VeraValidationError`) instead
  of raw `httpx` errors. The server's `X-Request-ID` is propagated onto
  the error for log correlation.

### Fixed
- `@audit` and `@async_audit` decorators no longer propagate Vera-side HTTP failures as exceptions in customer code
- `AsyncVeraClient._flush()` no longer infinitely re-queues on every
  exception — permanent (4xx) failures now drop the batch with an ERROR
  log, transient failures re-queue under the new poison-batch policy.

## Migration

If your code currently catches `httpx.HTTPStatusError` from
`record_action()`, switch to catching `VeraError` (or a more specific
subclass like `VeraAuthError`):

```python
from vera import VeraAuthError, VeraServerError, VeraError

try:
    client.record_action(action_name="checkout")
except VeraAuthError:
    # 401/403 — your API key is missing, invalid, or revoked
    refresh_credentials()
except VeraServerError:
    # 5xx after retries — Vera is having a bad day
    queue_for_later()
except VeraError as e:
    # Any other Vera-originated failure
    log.error("vera failed: %s (request_id=%s)", e, e.request_id)
```

`VeraError` does not inherit from `httpx.HTTPStatusError`, so existing
`except httpx.HTTPStatusError` blocks will no longer match terminal
failures from the SDK. They will continue to match low-level transport
errors that escape outside the retry loop, but you should plan to
migrate.

If you've been calling `record_action()` from a hot path and want
async-by-default behaviour, switch to `enqueue_action()`:

```python
# Before (blocking):
client.record_action(action_name="charge", input_data=payload)

# After (fire-and-forget, returns in <50us):
client.enqueue_action(action_name="charge", input_data=payload)
```

### Security
- **PHI leak fixes in schema-driven redaction**: case-insensitive schema field
  lookup so mixed-case keys (`Patient_Name`, `MRN`) hit the declared rule;
  defensive redaction of positional args in schema mode (parameter names are
  not visible at the redactor layer, so positional args fail closed); refuse
  `repr()` fallback for unknown objects (pydantic models, dataclasses, ORM
  rows) when a schema is active so attribute PHI cannot slip through; callable
  replacement in `pattern.sub` to prevent `re.error` raises (and resulting
  fail-open) when customer-supplied replacements contain regex backreferences
  (`\1`, `\g<...>`); consistent tagged replacement for `FieldPolicy.PATTERN`
  so non-bracketed customer replacements (`<scrubbed>`) produce clean output
  instead of `<scrubbed:mrn]`. Validate `Redactor.replacement` rejects
  newlines / null bytes (log injection). Starter `medtech_starter_schema()`
  expanded to cover common free-text field names (`description`, `summary`,
  `comment`, `comments`, `message`, `transcript`, `audio_transcript`,
  `email_body`, `body`, `text`). `Schema(unmapped_policy=PASSTHROUGH)` now
  emits a warning at init noting that deny-by-default is disabled. Closes
  review findings on PR #158.

## [0.3.0] - 2026-04-27

### Added
- `Redactor` class for built-in PII/secret redaction
- Opt-in redaction for direct `client.record_action()` calls
- LangChain and CrewAI integrations with redaction on captured content
- OpenAI integration: audit streaming responses with `Redactor` applied to captured content
- Anthropic integration: audit streaming responses with `Redactor` applied to captured content
- Auto-generated `Idempotency-Key` header on action writes
- Human-in-the-loop approval flow (`request_approval` / `wait_for_approval`)

### Changed
- Renamed `actionledger` SDK package to `vera` (published on PyPI as `vera-sdk`)
