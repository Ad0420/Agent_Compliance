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
