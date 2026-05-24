# Migration Guide

Major and minor version transitions with breaking behavioral changes are
documented here. Follow these guides when upgrading.

## `@vera.audit` → `@vera.gate` (Phase 1 PR 8)

`@vera.audit` is being renamed to `@vera.gate` as the v1 primitive.
The new decorator adds **policy enforcement** on top of the
audit-only capture behavior the existing `@vera.audit` provides.

### What changed

`@vera.audit` now emits a `DeprecationWarning` the first time each
decorated call site is invoked. The decorator's runtime behavior is
**unchanged** — it continues to capture an `ActionRecord` and never
raises `PolicyBlock` / `PendingReview`, so existing pilot code keeps
working with no behavior change.

`@vera.gate` is the new primitive and adds:

* `tenant=` resolution against the Phase 1 PR 7 resolver (explicit
  kwarg > context manager > middleware > default). Missing tenant
  raises `TenantMissingOrInvalid` — gates are tenant-scoped by design.
* `agent_type=` per-call override of the `vera.init(agent_type=...)`
  global. Stamped onto the outgoing ActionRecord; backend treats
  unknown values as `unclassified`.
* Policy routing against `POST /v1/gates/evaluate`:
    * `ALLOW` → invoke + capture + return result (legacy audit
      behavior).
    * `REQUIRE_HITL` → invoke for draft, capture, raise `PendingReview`.
    * `BLOCK` → do NOT invoke, raise `PolicyBlock`.

### Phase 1 / Phase 2 bridge

The backend `/v1/gates/evaluate` endpoint lands in Phase 2. Until then,
`@vera.gate` ships with a **404 fallback**: if the endpoint isn't
available, the decorator emits a single `UserWarning` per process and
degrades to audit-only capture (legacy `@vera.audit` semantics). When
Phase 2 lands the endpoint, the decorator auto-graduates to full gate
semantics without an SDK release.

### `realtime=True`

The `realtime=True` kwarg is plumbed through for callers configuring
decorators now, but raises `NotImplementedError` at call time until
the Phase 2 backend `REQUIRE_DEFERRED_REVIEW` ruling lands.

### Recommended migration

1. Decide if your wrapped function needs tenant scoping. Single-tenant
   pilots can call `vera.init(default_tenant="<id>", agent_type="<x>")`
   once at startup and the gate decorator picks both up.
2. Rename `@vera.audit(action_name="...")` to
   `@vera.gate(action_class="...")`. The decorator signature is
   otherwise the same.
3. Wrap calls in `try / except PolicyBlock / except PendingReview`
   where the action might be blocked or queued for review.
4. For test suites, use the `bypass_gates` pytest fixture from
   `vera.testing` to skip the `/v1/gates/evaluate` HTTP call in unit
   tests (the wrapped function is still invoked and the call is
   still captured as an ActionRecord — only the policy lookup is
   short-circuited).

### Automated migration via codemod (Phase 1 PR 9 / Stream D8)

Most of the rename is mechanical. Run the bundled codemod to apply it:

```bash
# Preview the diff without writing anything.
vera codemod audit-to-gate --dry-run path/to/your/code

# Apply the migration in place.
vera codemod audit-to-gate path/to/your/code

# CI gate: exit 1 if any file would change.
vera codemod audit-to-gate --check path/to/your/code

# Opt in to the try/except scaffold around call sites (opinionated diff).
vera codemod audit-to-gate --wrap-callsites path/to/your/code

# Skip the agent_type= TODO comment insertion.
vera codemod audit-to-gate --no-init-todo path/to/your/code
```

The codemod handles, in a single pass:

1. **Imports** — `from vera import audit` → `from vera import gate`,
   `from vera import async_audit` → `from vera import gate`, both
   preserving any `as <alias>`. Mixed imports of both names collapse
   to a single `from vera import gate`.
2. **Decorators** — `@vera.audit(...)`, `@vera.async_audit(...)`,
   `@audit(...)`, `@async_audit(...)` → `@vera.gate(...)` /
   `@gate(...)`. Aliased imports leave the local reference untouched
   (the import line already rebound the name).
3. **Kwarg rename** — `action_name=` → `action_class=` on any
   `@vera.gate(...)` decorator the codemod recognises. Positional
   args pass through unchanged.
4. **(Opt-in) try/except scaffold** — wraps bare call sites of
   gate-decorated functions in a `try / except (vera.PendingReview,
   vera.PolicyBlock)` skeleton with TODO comments. Skipped when the
   call site is already inside a try block that catches Exception,
   BaseException, or the two domain errors directly.
5. **`vera.init()` agent_type TODO** — when `vera.init(...)` is
   missing `agent_type=`, the codemod appends a trailing-comment TODO
   pointing at this migration guide. Idempotent: re-running won't add
   a second TODO.

#### Idempotency

Running the codemod twice in a row on the same source produces zero
changes on the second run. This is asserted on every fixture in
`sdk/tests/test_codemod.py::test_double_run_idempotent`.

#### Per-file opt-out

Prefix a file with `# noqa: VERA-CODEMOD` (top of file, after any
shebang / encoding cookie) to skip it entirely.

Grammar (case-insensitive, word-boundary anchored):

| Form                                       | Matches? |
|--------------------------------------------|----------|
| `# noqa: VERA-CODEMOD`                     | yes      |
| `# noqa: VERA-CODEMOD-AUDIT-TO-GATE`       | yes      |
| `# noqa: VERA-CODEMOD-FUTURE-SUFFIX`       | yes      |
| `# noqa: VERA-CODEMODISH`                  | no       |
| `# noqa: vera-codemod`                     | yes      |

The suffixed form (`VERA-CODEMOD-AUDIT-TO-GATE`) is reserved for
forward compatibility — when future codemods ship under their own
suffix, you'll be able to opt out of one without opting out of all.
For now the codemod treats every match as a global opt-out.

#### Exit codes (CLI / CI)

The CLI matches `ruff`'s convention so wrappers can branch on rc:

| Code | Meaning                                                   |
|------|-----------------------------------------------------------|
| 0    | Clean run — nothing pending (or `--check` saw no changes) |
| 1    | `--check` mode and at least one file would change         |
| 2    | Read / parse errors during the run (always wins over 1)   |

#### Manual steps the codemod will NOT do

* `async_audit(blocking=False)` — `@vera.gate` has no `blocking=`
  kwarg. The codemod renames the decorator but leaves the kwarg in
  place; the next call site invocation will raise a `TypeError`. Drop
  the kwarg manually after migrating.
* `try/except` body content. The wrap-callsites transform inserts
  `raise` placeholders with TODO comments. Replace them with your
  queueing / block-handling logic.
* Tenant resolution. `@vera.gate` requires a tenant; call
  `vera.init(default_tenant="<id>")` once at startup or pass
  `tenant=` per-decorator.

#### Example

Before:

```python
import vera
from vera import audit

vera.init(api_key="al_live_...")


@audit(action_name="approve_loan")
def approve_loan(applicant_id):
    return {"approved": True}


@vera.audit("chart_note_finalize")
async def finalize(note):
    return note


result = approve_loan("a-123")
```

After (`vera codemod audit-to-gate --wrap-callsites .`):

```python
import vera
from vera import gate

vera.init(api_key="al_live_...")  # TODO(audit-to-gate codemod): set agent_type= for new_agent_type_detected event (see MIGRATION.md)


@gate(action_class="approve_loan")
def approve_loan(applicant_id):
    return {"approved": True}


@vera.gate("chart_note_finalize")
async def finalize(note):
    return note


try:
    result = approve_loan("a-123")
except vera.PendingReview as pending:
    # TODO(audit-to-gate codemod): handle PendingReview (review_id=pending.review_id)
    raise
except vera.PolicyBlock as blocked:
    # TODO(audit-to-gate codemod): handle PolicyBlock (reason=blocked.reason)
    raise
```

The deprecation warning fires per call site (deduped on
`(filename, lineno)`) so the codemod can surface every site that
needs touching from a single test run.

## Upgrading from 0.3.x to 0.4.x

The 0.4.0 release will introduce non-blocking-by-default semantics for the
decorator-driven recording path. A `DeprecationWarning` will fire in 0.3.x
patch releases ahead of the 0.4.0 cut so existing code paths surface clearly.

(detailed migration steps will be added here as 0.4.x lands; this file
exists in 0.3.x so its presence is part of the upgrade contract)

### Behavior changes (planned for 0.4.0)
- `@audit` and `@async_audit` decorators will use `client.enqueue_action()`
  internally instead of `client.record_action()`. Direct callers of
  `client.record_action()` are unaffected — that method retains its current
  blocking, returns-server-JSON semantics.
- `VeraClient` will start a background worker thread on first use. If you run
  under `gevent`/`eventlet` or fork after init, see the new "Concurrency"
  section in the README.

### Durable spool — behavior changes

- **Undecryptable rows are now quarantined, not deleted.** Previous SDK
  releases of `0.4.0-pre` silently DELETED rows that AES-GCM refused to
  decrypt (one ERROR log per row, then the worker moved on). That destroyed
  the audit chain on `VERA_SPOOL_KEY` rotation — the exact failure mode the
  spool exists to prevent. The new behavior MOVES the row (in one
  transaction) into `spool_quarantine_records` and raises
  `SpoolDecryptionError` so the operator can run the documented recovery
  procedure (`sdk/docs/spool-key-rotation.md`) before purging.

  Operator action required:
  1. Watch for the loud `"SPOOL DECRYPTION FAILURE"` ERROR in your client
     logs. It fires once per process the first time decryption fails.
  2. If you see it, the spool's `quarantine_size()` is non-zero. Run the
     recovery procedure with the previous passphrase, or accept the loss
     explicitly and `DELETE FROM spool_quarantine_records`.
  3. The client falls back to in-memory-only operation for the rest of
     that process. Restart with the correct key (or after running the
     recovery procedure) to re-enable spool operation.

- **Wrong passphrase on an existing spool fails fast at init.** A
  `SpoolPassphraseError` (subclass of `SpoolDecryptionError`) is raised
  at construction time when the encrypted sentinel doesn't decrypt. The
  previous behavior accepted any passphrase silently for empty spools,
  which let operator typos at `VERA_SPOOL_KEY` rotation become permanent.

- **Per-record idempotency keys now appear in the wire payload.** The
  internal `_idempotency_key` (chosen at enqueue time, persisted to the
  spool) is promoted into `metadata.record_idempotency_key` on each POST
  to `/v1/actions/batch`. If your backend introspects `metadata`, a new
  `record_idempotency_key` field will appear there. Server-side per-record
  dedupe will land in a subsequent backend release; the SDK change is
  additive and harmless to current consumers.

### Tenant resolver (Phase 1 PR 7)

The SDK now resolves a `tenant_id` for each outgoing action record from
four sources, in strict precedence:

1. Explicit `tenant=` kwarg on `record_action` / `enqueue_action` (and,
   in PR 8, `@vera.gate`).
2. `with vera.tenant("x"): ...` context manager.
3. `vera.set_tenant("x", source="middleware")` — used by
   `vera.middleware.VeraMiddleware`.
4. Process-level default, `vera.init(default_tenant="x")` or
   `vera.set_default_tenant("x")`.

When at least one source provides a value, the SDK stamps `tenant_id`
at the top level AND `metadata.tenant_source` (one of `explicit_kwarg`,
`context_manager`, `middleware`, `default`) onto the outgoing payload.

`tenant_source` is nested inside `metadata` rather than placed at the
top level because the backend's pydantic v2 schemas default to
`extra="ignore"` — a top-level `tenant_source` field is silently
dropped before it ever lands on disk, and a future schema that flips
to `extra="forbid"` would reject the field outright. Nesting under
`metadata` (which the backend stores as a JSON column) preserves the
provenance in the spool dump, in structured logs, and in the audit
trail regardless of pydantic policy.

When no source provides a value, the SDK omits both fields — backward
compatible for call sites that pre-date the resolver.

Tenant IDs are validated against `^[a-zA-Z0-9_-]{1,64}$` on the SDK
side (matching the backend regex). An explicit `tenant=` kwarg with a
malformed value raises `TenantMissingOrInvalid(reason="malformed")` —
this is a programmer error and must surface loudly.

#### FastAPI / Starlette middleware

Install with the `middleware` extra to get the pinned starlette floor:

```
pip install vera-sdk[middleware]
```

The pin is `starlette>=0.21`. Older releases had a contextvar-isolation
bug in `BaseHTTPMiddleware` that broke per-request tenant bindings.

```python
from fastapi import FastAPI
from vera.middleware import VeraMiddleware

app = FastAPI()
app.add_middleware(VeraMiddleware, header="X-Tenant-ID")
```

Optional `strict=True` rejects requests with a missing or malformed
tenant header with a 400. Default `strict=False` lets the request
through with no tenant bound.

#### Thread-pool propagation (Codex F4 gotcha)

`contextvars.ContextVar` propagates automatically across
`asyncio.create_task` AND `asyncio.to_thread`, but it does **NOT**
propagate across `loop.run_in_executor`, `ThreadPoolExecutor.submit`,
or any third-party background-task layer that submits a sync function
to a worker thread without an explicit context snapshot. Use
`vera.copy_context_to_thread`:

```python
import vera

# loop.run_in_executor
await loop.run_in_executor(None, vera.copy_context_to_thread(do_work, arg1))

# concurrent.futures.ThreadPoolExecutor
pool.submit(vera.copy_context_to_thread(do_work, arg1))

# FastAPI BackgroundTasks (defense in depth; current Starlette snapshots
# context, but historical and third-party layers do not)
background_tasks.add_task(vera.copy_context_to_thread(do_work, arg1))
```

`copy_context_to_thread(fn, *args, **kwargs)` returns a zero-arg
closure that runs `fn(*args, **kwargs)` inside a snapshot of the
context taken at the moment the helper is called (not at the moment
the worker runs).
