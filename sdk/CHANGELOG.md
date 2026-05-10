# Changelog

All notable changes to `vera-sdk` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
