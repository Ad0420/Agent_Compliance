# Changelog

All notable changes to `vera-sdk` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
