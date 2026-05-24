# Migrating to Vera SDK 1.0.0

This guide covers upgrading from `vera-sdk` 0.3.x to 1.0.0. For
post-1.0 migrations, follow the section that names your current and
target versions.

## TL;DR

1. `pip install --upgrade 'vera-sdk[codemod]'`
2. `vera codemod audit-to-gate --dry-run path/to/your/code`
3. `vera codemod audit-to-gate path/to/your/code`
4. Run your test suite; address any new `PolicyBlock` / `PendingReview`
   raises in call sites that previously swallowed only HTTP errors.
5. Pin `vera-sdk>=1,<2` in your `requirements.txt` / `pyproject.toml`.

If you can't move yet, pin `vera-sdk>=0.3,<1` instead. The final 0.3
release (`0.3.1`) emits a `DeprecationWarning` from `@vera.audit` so
the migration surfaces in your CI logs on your own timeline.

## What changed in 1.0.0

- **`@vera.audit` is now a deprecated alias for `@vera.gate`.** The
  alias still works (and forwards to the same capture-only legacy
  semantics) but emits a `DeprecationWarning` once per call site.
  Removal is scheduled for `2.0.0`. See [Step 1](#step-1-decorator-rename-veraaudit--veragate).
- **Five new branded errors** — `PolicyBlock`, `PendingReview`,
  `WrongKeyTier`, `TenantMissingOrInvalid`,
  `ReviewerCredentialsInsufficient` — round out the 12-class catalog.
  See [Step 2](#step-2-new-error-classes--policyblock-and-pendingreview).
- **Tenant resolver** with four-source precedence (explicit kwarg >
  context manager > middleware > process default), plus
  `vera.middleware.VeraMiddleware` for FastAPI/Starlette. Tenant IDs
  are validated against `^[a-zA-Z0-9_-]{1,64}$`. See
  [Step 3](#step-3-tenant-resolver).
- **Production keys + BAA gate (server-side).** Live keys (`al_live_*`)
  now require an active BAA on the org. The SDK surface change is the
  new `PolicyBlock` code (`baa_required` / `baa_expired`). See
  [Step 4](#step-4-production-keys--baa-gate-server-side).
- **`vera codemod audit-to-gate`** ships a LibCST-powered migration
  tool. Install via the optional `[codemod]` extra. See
  [Codemod usage](#codemod-usage).
- **`@vera.audit` → `@vera.gate` adds tenant + agent_type stamping**
  even when the gate endpoint isn't reachable yet. The decorator falls
  back to legacy audit-only capture on 404 with one `UserWarning` per
  process, then auto-graduates to full gate routing when the Phase 2
  backend lands — no SDK release required.
- **`vera.testing.bypass_gates`** pytest fixture + `bypass_gates_cm`
  context manager so test suites can short-circuit the gate HTTP call
  without an httpx `MockTransport`.

## Step 1: Decorator rename (@vera.audit → @vera.gate)

`@vera.audit` is being renamed to `@vera.gate` as the v1 primitive.
The new decorator adds **policy enforcement** on top of the
audit-only capture behavior the existing `@vera.audit` provides.

### What stays the same

`@vera.audit` continues to work. The decorator's runtime behavior is
**unchanged** — it captures an `ActionRecord` and never raises
`PolicyBlock` / `PendingReview`. The only new behavior is a
`DeprecationWarning` emitted the first time each decorated call site
is invoked (deduped on `(filename, lineno)`).

### What `@vera.gate` adds

* `tenant=` resolution against the four-source resolver (explicit
  kwarg > context manager > middleware > process default). Missing
  tenant raises `TenantMissingOrInvalid` — gates are tenant-scoped
  by design.
* `agent_type=` per-call override of the `vera.init(agent_type=...)`
  global. Stamped onto the outgoing `ActionRecord`; the backend
  taxonomy maps unknown values to `unclassified`.
* Policy routing against `POST /v1/gates/evaluate`:
    * `ALLOW` → invoke + capture + return result (legacy audit behavior).
    * `REQUIRE_HITL` → invoke for draft, capture, raise `PendingReview`.
    * `BLOCK` → do NOT invoke, raise `PolicyBlock`.

### Phase 1 → Phase 2 bridge

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

### Recommended migration sequence

1. Run the [codemod](#codemod-usage) to handle the mechanical rewrite
   (imports + decorators + kwarg rename).
2. Decide if your wrapped function needs tenant scoping. Single-tenant
   pilots can call `vera.init(default_tenant="<id>", agent_type="<x>")`
   once at startup and the gate decorator picks both up.
3. Wrap call sites in `try / except PolicyBlock / except PendingReview`
   where the action might be blocked or queued for review. The codemod
   can scaffold this with `--wrap-callsites` (opinionated diff).
4. For test suites, use the `bypass_gates` pytest fixture from
   `vera.testing` to skip the `/v1/gates/evaluate` HTTP call in unit
   tests (the wrapped function is still invoked and still captured;
   only the policy lookup is short-circuited).

## Step 2: New error classes — PolicyBlock and PendingReview

The 12-class error catalog adds five new branded errors that any
`@vera.gate`-decorated call site MAY raise:

| Class                              | Raised when                                                                  |
|------------------------------------|------------------------------------------------------------------------------|
| `PolicyBlock`                       | Gate returned `BLOCK`, or backend emitted a `baa_required` / `policy_block`. |
| `PendingReview`                     | Gate returned `REQUIRE_HITL`; the draft was captured before the raise.       |
| `WrongKeyTier`                      | Test key tried to access a live-only endpoint (or vice versa).               |
| `TenantMissingOrInvalid`            | No tenant resolved, or the resolved tenant failed regex validation.          |
| `ReviewerCredentialsInsufficient`   | HITL approval call signed by a reviewer without the required role.           |

All five inherit from `VeraError`, so existing
`except VeraError:` blocks already catch them. Code that wants to
distinguish between, say, a transient backend issue (`VeraServerError`)
and a policy decision (`PolicyBlock`) should branch on the specific
class:

```python
import vera

try:
    approve_loan(applicant_id="a-123")
except vera.PolicyBlock as blocked:
    log.info("policy blocked: %s (fix_url=%s)", blocked.reason, blocked.fix_url)
    return {"status": "denied", "reason": blocked.reason}
except vera.PendingReview as pending:
    log.info("queued for review: %s", pending.review_id)
    return {"status": "pending", "review_id": pending.review_id}
except vera.VeraError as e:
    log.error("vera failed: %s (request_id=%s)", e, e.request_id)
    raise
```

`VeraError` does not inherit from `httpx.HTTPStatusError`, so
existing `except httpx.HTTPStatusError` blocks will no longer match
terminal failures from the SDK. Migrate to `except VeraError` or a
specific subclass.

## Step 3: Tenant resolver

The SDK now resolves a `tenant_id` for each outgoing action record
from four sources, in strict precedence:

1. Explicit `tenant=` kwarg on `record_action` / `enqueue_action` /
   `@vera.gate`.
2. `with vera.tenant("x"): ...` context manager.
3. `vera.set_tenant("x", source="middleware")` — used by
   `vera.middleware.VeraMiddleware`.
4. Process-level default: `vera.init(default_tenant="x")` or
   `vera.set_default_tenant("x")`.

When at least one source provides a value, the SDK stamps `tenant_id`
at the top level AND `metadata.tenant_source` (one of `explicit_kwarg`,
`context_manager`, `middleware`, `default`) onto the outgoing payload.

`tenant_source` is nested inside `metadata` rather than placed at the
top level because the backend's pydantic v2 schemas default to
`extra="ignore"` — a top-level `tenant_source` field would be silently
dropped before it ever landed on disk, and a future schema that flipped
to `extra="forbid"` would reject the field outright. Nesting under
`metadata` (a JSON column on the backend) preserves the provenance in
the spool dump, in structured logs, and in the audit trail regardless
of pydantic policy.

When no source provides a value, the SDK omits both fields —
backward-compatible for call sites that pre-date the resolver.

Tenant IDs are validated against `^[a-zA-Z0-9_-]{1,64}$` on the SDK
side (matching the backend regex). An explicit `tenant=` kwarg with a
malformed value raises `TenantMissingOrInvalid(reason="malformed")` —
this is a programmer error and must surface loudly.

### FastAPI / Starlette middleware

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

### Thread-pool propagation (Codex F4 gotcha)

`contextvars.ContextVar` propagates automatically across
`asyncio.create_task` AND `asyncio.to_thread`, but does **NOT**
propagate across `loop.run_in_executor`,
`ThreadPoolExecutor.submit`, or any third-party background-task layer
that submits a sync function to a worker thread without an explicit
context snapshot. Use `vera.copy_context_to_thread`:

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

## Step 4: Production keys + BAA gate (server-side)

API keys minted with `kind="live"` now require an active BAA on the
org. Previously this field was silently dropped on the backend; now
it's honored and gated.

* Without a BAA: the mint call returns HTTP 403 with
  `{"code": "baa_required", "fix_url": ...}`. The SDK surfaces this as
  `vera.PolicyBlock` via `wrap_httpx_error` → `CODE_TO_ERROR_CLASS`.
* With an expired BAA: each per-request gate returns
  `{"code": "baa_expired", ...}`, also surfaced as `PolicyBlock`.
* Sandbox keys (`kind="test"`, the default) are unaffected.

No client code changes are required if you already catch
`PolicyBlock` — the new `code` values route to the same class.
Log-grep / alerting that matches the URL substrings `errors/auth`,
`errors/timeout`, or `errors/network` should update to the new slugs
(`errors/invalid_api_key`, `errors/gate_timeout_or_network`) — the
first call to `str(err)` on each renamed class in a process emits a
one-shot `DeprecationWarning` carrying the old → new mapping so pilots
see the change in CI before it shows up in alert noise.

## Codemod usage

Most of the rename is mechanical. The bundled `vera codemod
audit-to-gate` tool applies it via LibCST (not regex — preserves
comments, whitespace, and formatting).

```bash
# Install the codemod extra (LibCST is ~15MB; optional so default
# installs stay slim).
pip install 'vera-sdk[codemod]'

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

### Idempotency

Running the codemod twice in a row on the same source produces zero
changes on the second run. This is asserted on every fixture in
`sdk/tests/test_codemod.py::test_double_run_idempotent`.

### Per-file opt-out

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

### Exit codes (CLI / CI)

The CLI matches `ruff`'s convention so wrappers can branch on rc:

| Code | Meaning                                                   |
|------|-----------------------------------------------------------|
| 0    | Clean run — nothing pending (or `--check` saw no changes) |
| 1    | `--check` mode and at least one file would change         |
| 2    | Read / parse errors during the run (always wins over 1)   |

### What the codemod will NOT do

The codemod is intentionally conservative. It will skip (and not warn
on) the following patterns; migrate them by hand:

* **`getattr` / dynamic decorator lookups** — `getattr(vera, "audit")(...)`
  is invisible to the AST walker. Search for `getattr.*audit` separately.
* **Factory-wrapped decorators** — `dec = my_factory(vera.audit)` then
  `@dec(...)` doesn't get rewritten; the factory call site is opaque.
* **Non-decorator uses** — `vera.audit` referenced as a value (passed
  as a callback, stored on an object) is left alone. The decorator
  rewrite is anchored to `@`-syntax + the import-statement walker.
* **`__all__` re-exports** — projects that put `"audit"` in a module's
  `__all__` to forward the symbol get an unrenamed entry. Update by
  hand.
* **Relative imports** — `from .vera_compat import audit` is not
  touched. The codemod only matches imports rooted at the `vera`
  package.
* **`async_audit(blocking=False)`** — `@vera.gate` has no `blocking=`
  kwarg. The codemod renames the decorator but leaves the kwarg in
  place; the next call site invocation will raise a `TypeError`. Drop
  the kwarg manually after migrating.
* **`try / except` body content** — the wrap-callsites transform
  inserts `raise` placeholders with TODO comments. Replace them with
  your queueing / block-handling logic.
* **Tenant resolution** — `@vera.gate` requires a tenant. Call
  `vera.init(default_tenant="<id>")` once at startup or pass `tenant=`
  per-decorator.

### Example

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

## Latency expectations

The 1.0.0 release adds the gate-evaluation HTTP call on the
`@vera.gate` hot path. Latency-regression baselines are captured in
`sdk/tests/test_latency_regression.py` for four critical paths:

| Path                                              | Baseline | Regression threshold |
|---------------------------------------------------|----------|----------------------|
| `@vera.gate` decorator, cold call under bypass    | 5 ms     | 3x baseline = 15 ms  |
| `@vera.gate` decorator, warm call under bypass    | 500 µs   | 3x baseline = 1.5 ms |
| `resolve_tenant` with explicit kwarg              | 50 µs    | 3x baseline = 150 µs |
| `resolve_tenant` from context manager             | 100 µs   | 3x baseline = 300 µs |

The baselines are intentionally loose (3x is "catastrophic regression",
not "micro-perf"). They're measured under `bypass_gates_cm()` so the
HTTP call is skipped — the goal is to catch a regression in the
decorator's own bookkeeping (ContextVar lookups, payload build,
redactor pass), not measure the backend round trip.

Skip the suite on slow CI hardware with
`pytest -m 'not latency'` or `VERA_SKIP_LATENCY_TESTS=1`. If your CI
is legitimately slower and the new baseline is well-characterized,
update the constants in `BASELINES_US` and note the new baseline
here.

## Release runbook (for SDK maintainers)

When this PR merges to `main`, a maintainer with PyPI publish
credentials cuts both releases from the same merge commit. The full
runbook lives at [`RELEASE.md`](./RELEASE.md). Short form:

1. Tag and publish `0.3.1` (the deprecation patch — backport built
   from the merge commit with `pyproject.toml::version` temporarily
   set to `0.3.1`).
2. Tag and publish `1.0.0` (the stable cut — pyproject.toml on `main`
   already points at `1.0.0`).
3. Smoke-test the published wheels in a fresh venv (`pip install
   vera-sdk==1.0.0` → `python -c "import vera; print(vera.__version__)"`).
4. Announce via the pilot channel + CHANGELOG-driven release notes.

## Historical migrations

The sections below cover migrations on the 0.x line. They're retained
for pilots upgrading from much older releases.

### Upgrading from pre-`0.3.x` (legacy)

The 0.4 cut never shipped to PyPI; the 0.3.x → 1.0.0 path described
above subsumes any pending 0.4 work. The notes below describe the
behavior the 1.0.0 release inherited from the pre-1.0 development
line:

#### Decorator-driven recording is non-blocking by default

`@audit` and `@async_audit` use `client.enqueue_action()` internally
(non-blocking, in-memory queue, daemon flush thread). Direct callers
of `client.record_action()` retain the original blocking semantics.

#### Durable spool — behavior changes

- **Undecryptable rows are quarantined, not deleted.** Pre-1.0
  alpha releases silently DELETED rows that AES-GCM refused to
  decrypt. The new behavior MOVES the row (in one transaction)
  into `spool_quarantine_records` and raises
  `SpoolDecryptionError` so the operator can run the documented
  recovery procedure (`sdk/docs/spool-key-rotation.md`) before
  purging.

  Operator action required:
  1. Watch for the loud `"SPOOL DECRYPTION FAILURE"` ERROR in
     your client logs. It fires once per process the first time
     decryption fails.
  2. If you see it, the spool's `quarantine_size()` is non-zero.
     Run the recovery procedure with the previous passphrase,
     or accept the loss explicitly and
     `DELETE FROM spool_quarantine_records`.
  3. The client falls back to in-memory-only operation for the
     rest of that process. Restart with the correct key (or
     after running the recovery procedure) to re-enable spool
     operation.

- **Wrong passphrase on an existing spool fails fast at init.** A
  `SpoolPassphraseError` (subclass of `SpoolDecryptionError`) is
  raised at construction time when the encrypted sentinel doesn't
  decrypt.

- **Per-record idempotency keys appear in the wire payload.** The
  internal `_idempotency_key` (chosen at enqueue time, persisted to
  the spool) is promoted into `metadata.record_idempotency_key` on
  each POST to `/v1/actions/batch`. Additive — backend accepts
  arbitrary `metadata: dict`.
