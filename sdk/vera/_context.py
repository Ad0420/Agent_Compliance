"""Tenant resolver for the Vera SDK (Phase 1 PR 7 / Stream D3).

The tenant resolver is the SDK-side glue that decides which ``tenant_id``
to stamp on each outgoing action record. It supports four binding
mechanisms with strict precedence:

1. **Explicit kwarg** on the decorator / call (``vera.gate(tenant='x')``,
   ``client.record_action(tenant='x')``) — always wins.
2. **Context manager** — ``with vera.tenant('x'): ...`` — scoped to the
   current async task / thread.
3. **Middleware** — :class:`vera.middleware.VeraMiddleware` calls
   :func:`set_tenant` per request; reset in a ``finally`` block.
4. **Default** — ``vera.init(default_tenant='x')`` — process-wide
   fallback for single-tenant deployments.

If none of the above produces a value, :func:`resolve_tenant` raises
:class:`vera.errors.TenantMissingOrInvalid` with ``reason='missing'``.

Every successful resolution returns ``(tenant_id, source)`` so the
caller can stamp provenance onto the record (``tenant_source`` field).

Validation
----------
All entry points (``set_tenant``, ``set_default_tenant``, the ``tenant``
context manager, ``resolve_tenant(explicit=...)``) validate against
``^[a-zA-Z0-9_-]{1,64}$`` — the same regex the backend enforces on
``POST /v1/actions``. PHI-shape detection stays server-side; the SDK
does not duplicate it here.

Thread-pool gotcha (Codex F4)
-----------------------------
:class:`contextvars.ContextVar` propagates **automatically** across
:func:`asyncio.create_task` (a context snapshot is taken at task
creation time) and across :func:`asyncio.to_thread` (Python 3.9+,
which internally calls :func:`contextvars.copy_context`).

It does **NOT** propagate into:

* :meth:`asyncio.AbstractEventLoop.run_in_executor` — the workhorse
  most thread-pool integrations call through, including some
  database/HTTP libraries that submit work to a private pool.
* ``concurrent.futures.ThreadPoolExecutor.submit`` / ``map``.
* FastAPI ``BackgroundTasks`` when the task body is a **sync**
  function (Starlette runs sync tasks on a worker thread; current
  Starlette versions DO snapshot context, but historical and
  third-party background-task layers do not — don't rely on this).

Use :func:`copy_context_to_thread` to wrap callables you submit to
any of the above so the current context (including the tenant) is
restored inside the worker. Cheap insurance — see the function
docstring for the recommended patterns.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Literal, Optional, Tuple, TypeVar

from .errors import TENANT_REASON_MALFORMED, TenantMissingOrInvalid

# Provenance tag stamped onto each record alongside ``tenant_id`` so
# observability tooling can answer "where did the tenant come from?".
TenantSource = Literal["middleware", "context_manager", "explicit_kwarg", "default"]

# The ContextVar holding the tenant currently in effect for the running
# asyncio task / thread context. Tuple of ``(tenant_id, source)``.
#
# Default is ``None``; ``get_tenant`` falls back to the process-level
# default (``_default_tenant``) when this is unset.
_current_tenant: contextvars.ContextVar[Optional[Tuple[str, TenantSource]]] = (
    contextvars.ContextVar("vera_current_tenant", default=None)
)

# Process-level default set by ``vera.init(default_tenant=...)``. NOT a
# ContextVar — it is a single fallback for the whole process and would
# not survive being reset alongside a context-bound tenant.
_default_tenant: Optional[str] = None

# Process-level default ``agent_type`` set by ``vera.init(agent_type=...)``
# (Phase 1 PR 8 / Stream D7). The ``@vera.gate`` decorator reads this when
# no per-call ``agent_type=`` kwarg is supplied. Mirrors the
# ``_default_tenant`` pattern: single fallback for the whole process,
# explicit per-call kwarg takes precedence.
_default_agent_type: Optional[str] = None

# Tenant ID format — kept in sync with the backend regex on
# ``POST /v1/actions`` (Phase 1 PR 5 / Stream D2). The SDK validates
# client-side so callers see :class:`TenantMissingOrInvalid` before the
# request leaves the process; the backend re-validates as defense-in-depth.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _validate_tenant_id(tid: Any) -> None:
    """Raise ``TenantMissingOrInvalid(reason='malformed')`` if ``tid`` is invalid.

    Validation rules:

    * Must be a ``str`` (no bytes, no ints, no ``None``).
    * Must match ``^[a-zA-Z0-9_-]{1,64}$`` — letters, digits, underscore,
      hyphen; 1-64 characters.

    The ``provided_value`` is echoed onto the exception so callers (and
    the dashboard) can see what was rejected. PHI-shape values are
    auto-redacted inside the exception constructor.
    """
    if not isinstance(tid, str):
        raise TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED, provided_value=tid
        )
    if not _TENANT_ID_RE.match(tid):
        raise TenantMissingOrInvalid(
            reason=TENANT_REASON_MALFORMED, provided_value=tid
        )


def set_default_tenant(tenant_id: Optional[str]) -> None:
    """Set the process-level default tenant.

    Called from :func:`vera.init` when ``default_tenant=`` is passed.
    Passing ``None`` clears the default (useful for test teardown).
    Non-``None`` values are validated against the tenant-id regex; an
    invalid value raises :class:`TenantMissingOrInvalid` before any
    state is mutated.
    """
    global _default_tenant
    if tenant_id is not None:
        _validate_tenant_id(tenant_id)
    _default_tenant = tenant_id


def get_default_tenant() -> Optional[str]:
    """Return the process-level default tenant, or ``None``."""
    return _default_tenant


def set_tenant(
    tenant_id: str, source: TenantSource = "middleware"
) -> contextvars.Token:
    """Bind ``tenant_id`` to the current context. Returns a reset token.

    Used by :class:`vera.middleware.VeraMiddleware` (with the default
    ``source='middleware'``). Other callers should prefer the
    :func:`tenant` context manager — it handles token bookkeeping for you.

    Validates the ID format before mutating the ContextVar so a bad
    value leaves the previous tenant untouched.
    """
    _validate_tenant_id(tenant_id)
    return _current_tenant.set((tenant_id, source))


def reset_tenant(token: contextvars.Token) -> None:
    """Restore the tenant to its value before the matching :func:`set_tenant`.

    Counterpart to :func:`set_tenant`. Required because the middleware
    cannot use the context-manager form (the request lifecycle is
    spread across two callbacks).
    """
    _current_tenant.reset(token)


def get_tenant() -> Optional[Tuple[str, TenantSource]]:
    """Return ``(tenant_id, source)`` for the current context, or ``None``.

    Precedence (matches :func:`resolve_tenant` minus the explicit kwarg):

    1. ContextVar (set by :func:`set_tenant` or the :func:`tenant`
       context manager).
    2. Process-level default (set by :func:`set_default_tenant`).
    3. ``None``.

    Does NOT raise — callers who need a non-``None`` result should use
    :func:`resolve_tenant` instead.
    """
    current = _current_tenant.get()
    if current is not None:
        return current
    if _default_tenant is not None:
        return (_default_tenant, "default")
    return None


@contextmanager
def tenant(tenant_id: str) -> Iterator[None]:
    """Bind ``tenant_id`` for the duration of the ``with`` block.

    Example::

        with vera.tenant('cleveland_clinic'):
            agent_call()  # any @vera.gate inside sees tenant=cleveland_clinic

    Source is recorded as ``'context_manager'`` so the resolved
    ``tenant_source`` on each record reflects the actual binding mechanism.

    Safe to nest: each ``with`` block pushes its own ContextVar token
    and pops it on exit (including on exception). Nested blocks shadow
    the outer tenant for the duration of the inner block.
    """
    _validate_tenant_id(tenant_id)
    token = _current_tenant.set((tenant_id, "context_manager"))
    try:
        yield
    finally:
        _current_tenant.reset(token)


# ---------------------------------------------------------------------------
# Phase 1 PR 8 / Stream D7 — agent_type global.
# ---------------------------------------------------------------------------


def set_default_agent_type(agent_type: Optional[str]) -> None:
    """Set the process-level default ``agent_type``.

    Called from :func:`vera.init` when ``agent_type=`` is passed. Passing
    ``None`` clears the default (useful for test teardown). Unlike
    ``tenant_id``, ``agent_type`` is free-form (the backend treats unknown
    values as ``unclassified`` per Codex X4) so we do NOT validate here —
    the backend is the source of truth for the type taxonomy.
    """
    global _default_agent_type
    _default_agent_type = agent_type


def get_default_agent_type() -> Optional[str]:
    """Return the process-level default ``agent_type``, or ``None``."""
    return _default_agent_type


def resolve_agent_type(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the ``agent_type`` for an outgoing record.

    Precedence (highest first):

    1. ``explicit`` kwarg — typically the ``agent_type=`` arg on
       ``@vera.gate``. Wins even when ``None``? No — ``None`` means
       "no explicit override, consult the global". This mirrors the
       tenant resolver and means a per-call ``agent_type=None`` cannot
       be used to *unset* the global; callers should call
       :func:`set_default_agent_type` directly for that.
    2. Process-level default — :func:`set_default_agent_type` /
       ``vera.init(agent_type=...)``.
    3. ``None`` — no agent_type stamped; backend treats record as
       ``unclassified``.
    """
    if explicit is not None:
        return explicit
    return _default_agent_type


def resolve_tenant(explicit: Optional[str] = None) -> Tuple[str, TenantSource]:
    """Resolve the tenant for an outgoing record. Raises if none available.

    Precedence (highest first):

    1. ``explicit`` kwarg (typically the ``tenant=`` arg on
       ``@vera.gate`` / ``client.record_action``).
    2. ContextVar — set by :func:`set_tenant` (middleware) or the
       :func:`tenant` context manager.
    3. Process-level default — :func:`set_default_tenant` /
       ``vera.init(default_tenant=...)``.

    Raises :class:`TenantMissingOrInvalid` with ``reason='missing'``
    when nothing is set, and ``reason='malformed'`` when any of the
    candidate values fails the format regex.
    """
    if explicit is not None:
        _validate_tenant_id(explicit)
        return (explicit, "explicit_kwarg")
    current = get_tenant()
    if current is None:
        raise TenantMissingOrInvalid(reason="missing")
    return current


# ---------------------------------------------------------------------------
# Codex F4 — thread-pool propagation helper.
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


def copy_context_to_thread(
    fn: Callable[..., _T], /, *args: Any, **kwargs: Any
) -> Callable[[], _T]:
    """Return a zero-arg closure that runs ``fn(*args, **kwargs)`` inside
    a snapshot of the current context.

    :class:`contextvars.ContextVar` propagates automatically across
    :func:`asyncio.create_task` and :func:`asyncio.to_thread`, but it
    does **NOT** propagate across
    :meth:`asyncio.AbstractEventLoop.run_in_executor`,
    :class:`concurrent.futures.ThreadPoolExecutor`, or any third-party
    background-task layer that submits a sync function to a worker
    thread without an explicit context snapshot.

    The snapshot is taken on the CALLING thread (i.e. at the moment
    this helper is invoked, before the executor picks up the work). The
    returned closure replays that snapshot via ``ctx.run(...)`` on the
    worker thread, so ContextVar reads inside ``fn`` see the values
    that were in effect at submission time.

    Usage patterns::

        # loop.run_in_executor
        await loop.run_in_executor(
            None, copy_context_to_thread(do_work, arg1, arg2)
        )

        # FastAPI BackgroundTasks (sync function — defense in depth)
        background_tasks.add_task(copy_context_to_thread(do_work, arg1))

        # concurrent.futures.ThreadPoolExecutor
        pool.submit(copy_context_to_thread(do_work, arg1))

    The intermediate closure exists because ``run_in_executor`` / pool
    ``.submit`` invoke the callable they receive ON THE WORKER THREAD —
    if we took the snapshot inside ``fn``'s body, it would capture the
    worker's empty context, not the submitter's. Returning a closure
    lets us snapshot in the caller and replay in the worker.
    """
    ctx = contextvars.copy_context()

    def _runner() -> _T:
        return ctx.run(fn, *args, **kwargs)

    return _runner


__all__ = [
    "TenantSource",
    "tenant",
    "set_tenant",
    "reset_tenant",
    "get_tenant",
    "get_default_tenant",
    "set_default_tenant",
    "resolve_tenant",
    "copy_context_to_thread",
    # Phase 1 PR 8 / Stream D7 — agent_type global.
    "set_default_agent_type",
    "get_default_agent_type",
    "resolve_agent_type",
]
