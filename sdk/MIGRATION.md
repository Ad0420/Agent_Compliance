# Migration Guide

Major and minor version transitions with breaking behavioral changes are
documented here. Follow these guides when upgrading.

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
