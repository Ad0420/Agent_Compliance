"""Vera SDK public API.

The Sentry-style entry point is :func:`init` (or :func:`init_async` for the
async client). It constructs a :class:`VeraClient` from explicit kwargs +
env vars, registers it as the default for the ``@audit`` decorator, and
returns the client so callers can keep a reference.

Env-var fallbacks honored by :func:`init` and the client constructors:
``VERA_API_KEY``, ``VERA_API_URL``, ``VERA_AGENT_NAME``,
``VERA_AGENT_VERSION``, ``VERA_MODEL_ID``, ``VERA_FRAMEWORK``,
``VERA_SPOOL_PATH``, ``VERA_DEV``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

from .client import (
    VeraClient,
    ApprovalRejectedError,
    ApprovalTimeoutError,
)
from .decorator import (
    audit,
    set_default_client,
    set_default_redactor,
    get_default_redactor,
)
from .async_client import AsyncVeraClient
from .async_decorator import async_audit, set_default_async_client
from .redaction import Redactor
from ._context import (
    # Phase 1 PR 7 / Stream D3 — tenant resolver. See vera/_context.py for
    # the precedence rules (explicit kwarg > context manager > middleware >
    # default) and the Codex F4 thread-pool propagation helper.
    tenant,
    set_tenant,
    reset_tenant,
    get_tenant,
    get_default_tenant,
    set_default_tenant,
    resolve_tenant,
    copy_context_to_thread,
    # Phase 1 PR 8 / Stream D7 — agent_type global.
    set_default_agent_type,
    get_default_agent_type,
    resolve_agent_type,
)
from .gate import (
    # Phase 1 PR 8 / Stream D5 — the v1 @vera.gate decorator. Synchronous
    # Ruling routing (ALLOW / REQUIRE_HITL / BLOCK) against the Phase 2
    # /v1/gates/evaluate endpoint with 404 fallback to legacy audit-only
    # capture so the decorator ships today and auto-graduates.
    gate,
    is_bypassing_gates,
)
from .errors import (
    VeraError,
    VeraAuthError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraNetworkError,
    VeraValidationError,
    VeraClientError,
    # Phase 1 PR 6 / Stream D1 — five new domain errors. Wired into the
    # httpx layer in :mod:`vera.client` so backend-emitted ``code`` strings
    # raise the matching branded class. Consumed by ``@vera.gate``
    # (Phase 2) and the tenant resolver (Phase 1 PR 7).
    PolicyBlock,
    PendingReview,
    WrongKeyTier,
    TenantMissingOrInvalid,
    ReviewerCredentialsInsufficient,
    # Wave 2C PR B2 — distinct error class raised by
    # ``@vera.gate(realtime=True)`` so customer code can route the
    # "queue and continue" pattern separately from the default
    # "block and wait" PendingReview pattern.
    RequiresDeferredReview,
)

logger = logging.getLogger("vera.init")

# Back-compat aliases (deprecated — will be removed in v1.0)
ActionLedgerClient = VeraClient
AsyncActionLedgerClient = AsyncVeraClient


# Module-level handles to the client(s) registered via :func:`init` /
# :func:`init_async`. ``None`` means no init() has been called yet.
_initialized_client: VeraClient | None = None
_initialized_async_client: AsyncVeraClient | None = None

# Module-level locks guarding the read-modify-write of the handles above.
# Concurrent ``init()`` callers (e.g. multiple worker threads in a web app
# starting up in parallel) could otherwise both see the same ``previous``,
# close it twice, and race on ``set_default_client``. The lock is taken
# AROUND the swap — client construction itself happens outside the lock so
# slow init paths (httpx connection setup, spool open) don't serialise.
_init_lock = threading.Lock()
# ``asyncio.Lock`` for the async-aware init path. Lazily constructed: at
# module import time there may be no running loop yet, and binding to a
# specific loop here would break callers who set up their own loop later.
_init_async_lock: asyncio.Lock | None = None
_init_async_lock_setup = threading.Lock()


def _get_async_init_lock() -> asyncio.Lock:
    """Return the module-level asyncio.Lock, constructing it on first use."""
    global _init_async_lock
    # Double-checked locking: the threading.Lock prevents two threads from
    # both winning the "first await" race and creating two asyncio.Locks.
    if _init_async_lock is None:
        with _init_async_lock_setup:
            if _init_async_lock is None:
                _init_async_lock = asyncio.Lock()
    return _init_async_lock


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-shaped env var.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Empty / unset / anything else → ``default``.
    """
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


class _UninitializedClient:
    """Sentinel returned by :func:`get_client` when :func:`init` hasn't run.

    Accessing any attribute raises :class:`VeraError` with a helpful message.
    Returning this instead of ``None`` means the failure mode for "forgot to
    call init()" is a loud, descriptive exception instead of a generic
    ``AttributeError: 'NoneType' object has no attribute ...``.
    """

    def __getattr__(self, name: str) -> Any:
        raise VeraError(
            f"vera.init() not called. Call vera.init(api_key=..., "
            f"agent_name=...) before accessing vera.get_client().{name}. "
            f"See https://docs.usevera.xyz/quickstart"
        )

    def __bool__(self) -> bool:  # so ``if vera.get_client():`` still works
        return False

    def __repr__(self) -> str:
        return "<vera.UninitializedClient — call vera.init() first>"


_UNINITIALIZED = _UninitializedClient()


def init(
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
    model_id: str | None = None,
    framework: str | None = None,
    dev: bool | None = None,
    persistent_buffer_path: str | None = None,
    default_tenant: str | None = None,
    agent_type: str | None = None,
    **client_kwargs: Any,
) -> VeraClient:
    """Initialize Vera. Sentry-style one-call setup.

    Constructs a :class:`VeraClient` from explicit kwargs + env vars (env
    wins over ``None`` args, explicit args win over env). Registers the
    client as the default for the ``@audit`` decorator and returns it so
    callers can keep a reference if they want.

    Args:
        api_key: Vera API key. Falls back to ``VERA_API_KEY`` env var.
        api_url: Vera API base URL. Falls back to ``VERA_API_URL`` env var,
            then to ``"https://api.usevera.xyz"``.
        agent_name: Name of this agent. Falls back to ``VERA_AGENT_NAME``,
            then to ``"default-agent"``.
        agent_version: Optional version string. Falls back to
            ``VERA_AGENT_VERSION``.
        model_id: Optional LLM model identifier. Falls back to
            ``VERA_MODEL_ID``.
        framework: Optional framework name (``openai``, ``anthropic``,
            ``langchain``, ``crewai``). Falls back to ``VERA_FRAMEWORK``.
        dev: If ``True`` OR ``VERA_DEV=1`` is set, returns a dev-mode
            client that prints records to stderr instead of POSTing.
        persistent_buffer_path: Durable spool path. Falls back to
            ``VERA_SPOOL_PATH`` env var. Requires ``VERA_SPOOL_KEY``.
        default_tenant: Process-wide tenant fallback (Phase 1 PR 7).
            Set this for single-tenant deployments so calls without an
            explicit ``tenant=`` kwarg, context manager, or middleware
            binding still resolve. Validated against
            ``^[a-zA-Z0-9_-]{1,64}$``; an invalid value raises
            :class:`TenantMissingOrInvalid` before the client is built.
            To clear a previously-registered default at runtime (e.g.
            for test isolation, since the binding lives on a
            module-level variable that persists across :func:`init`
            calls), call ``vera.set_default_tenant(None)``.
        agent_type: Process-wide ``agent_type`` fallback (Phase 1 PR 8).
            Stamped onto every ``@vera.gate`` outgoing payload unless
            overridden by a per-call ``agent_type=`` kwarg. Free-form;
            the backend taxonomy maps unknown values to
            ``unclassified`` per Codex X4. Backend (post PR #197)
            triggers a ``new_agent_type_detected`` event on first
            occurrence per org. To clear a previously-registered
            global, call ``vera.set_default_agent_type(None)``.
        **client_kwargs: Passed through to :class:`VeraClient` (e.g.
            ``timeout``, ``batch_size``, ``redactor``).

    Returns:
        The configured :class:`VeraClient` (or :class:`vera.dev.DevClient`
        when dev mode is active).

    Calling :func:`init` twice replaces the previous default client. The
    old client's :meth:`VeraClient.close` is invoked AFTER the swap so
    concurrent callers always see a valid default. Errors from ``close()``
    are logged at WARN but not re-raised so a stuck previous client can't
    block re-initialisation.

    Thread-safety: concurrent ``init()`` calls are serialised on the
    handle-swap section via a module-level :class:`threading.Lock`. Client
    construction itself runs outside the lock so a slow init path doesn't
    queue up other callers.

    Example::

        import vera
        vera.init(api_key="al_live_...", agent_name="my-agent")

        @vera.audit(action_name="approve_loan")
        def approve(applicant_id, amount):
            ...
    """
    dev_active = dev if dev is not None else _env_bool("VERA_DEV", default=False)

    # Phase 1 PR 7 — register the process-level tenant default BEFORE we
    # build the client. set_default_tenant validates against the regex and
    # raises TenantMissingOrInvalid for bad values; doing it first means a
    # bad default doesn't leak a half-initialised client or a spool.
    if default_tenant is not None:
        set_default_tenant(default_tenant)

    # Phase 1 PR 8 — register the process-level agent_type default.
    # No regex validation: ``agent_type`` is free-form on the wire and
    # the backend handles unknown values (Codex X4 — "unclassified").
    # We still set it BEFORE building the client so a future validation
    # tightening would fail-fast in the same place as the tenant check.
    if agent_type is not None:
        set_default_agent_type(agent_type)

    # Build the new client OUTSIDE the lock. Construction is expensive
    # (httpx setup, optional spool open) and any failures here should not
    # affect the previously-registered default.
    if dev_active:
        from .dev import build_dev_client

        new_client: VeraClient = build_dev_client(
            agent_name=agent_name,
            **client_kwargs,
        )
    else:
        new_client = VeraClient(
            api_key=api_key,
            api_url=api_url,
            agent_name=agent_name,
            agent_version=agent_version,
            model_id=model_id,
            framework=framework,
            persistent_buffer_path=persistent_buffer_path,
            **client_kwargs,
        )

    global _initialized_client
    with _init_lock:
        previous = _initialized_client
        _initialized_client = new_client
        set_default_client(new_client)

    # Close the previous client AFTER the swap so concurrent callers
    # always observe a valid default. ``close()`` is best-effort: a hung
    # close shouldn't deny re-init, and there's nothing the caller can do
    # if it raises.
    if previous is not None and previous is not new_client:
        try:
            previous.close()
        except Exception as e:  # noqa: BLE001 — close must never block re-init
            logger.warning("Failed to close previous Vera client: %s", e)

    return new_client


def init_async(
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
    model_id: str | None = None,
    framework: str | None = None,
    persistent_buffer_path: str | None = None,
    **client_kwargs: Any,
) -> AsyncVeraClient:
    """Initialize Vera for async codepaths (synchronous entry point).

    Mirrors :func:`init` but constructs an :class:`AsyncVeraClient` and
    registers it via :func:`set_default_async_client`. Returns the client
    so callers can ``await client.close()`` at process shutdown — the
    async client's drain MUST be awaited explicitly (atexit cannot drive
    async cleanup reliably).

    .. warning::
        This is a synchronous function and CANNOT ``await`` the previous
        client's ``close()`` when re-initialising. Any records still queued
        on the previous client are **abandoned** (no flush, no drain). If
        you re-init in a long-running async service and care about not
        losing in-flight records, use :func:`init_async_awaitable` instead.

    Dev mode is intentionally not supported here — the sync :class:`DevClient`
    captures records synchronously and works fine inside async test
    fixtures. Use :func:`init(dev=True)` for that.
    """
    new_client = AsyncVeraClient(
        api_key=api_key,
        api_url=api_url,
        agent_name=agent_name,
        agent_version=agent_version,
        model_id=model_id,
        framework=framework,
        persistent_buffer_path=persistent_buffer_path,
        **client_kwargs,
    )

    global _initialized_async_client
    with _init_lock:
        previous = _initialized_async_client
        _initialized_async_client = new_client
        set_default_async_client(new_client)

    # We can't await close() from a sync function. Warn loudly so callers
    # know in-flight records on the previous client are about to be
    # abandoned, and point them at the awaitable variant.
    if previous is not None and previous is not new_client:
        logger.warning(
            "vera.init_async: replacing the previous AsyncVeraClient WITHOUT "
            "awaiting its close(). Any records still queued on it will be "
            "dropped. Use vera.init_async_awaitable() if you need clean "
            "drain semantics on re-init."
        )

    return new_client


async def init_async_awaitable(
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
    model_id: str | None = None,
    framework: str | None = None,
    persistent_buffer_path: str | None = None,
    **client_kwargs: Any,
) -> AsyncVeraClient:
    """Async-aware variant of :func:`init_async` with clean re-init semantics.

    Identical to :func:`init_async` except that, when replacing a previous
    client, this function ``await``\\ s ``previous.close()`` so the old
    queue gets drained instead of dropped. Prefer this in long-running
    async services that may re-init mid-process.

    Use :func:`init_async` (sync) only for one-shot initialisation at
    application startup, where re-init is either a no-op or you've already
    accepted the data-loss risk.
    """
    new_client = AsyncVeraClient(
        api_key=api_key,
        api_url=api_url,
        agent_name=agent_name,
        agent_version=agent_version,
        model_id=model_id,
        framework=framework,
        persistent_buffer_path=persistent_buffer_path,
        **client_kwargs,
    )

    global _initialized_async_client
    lock = _get_async_init_lock()
    async with lock:
        previous = _initialized_async_client
        _initialized_async_client = new_client
        set_default_async_client(new_client)

    if previous is not None and previous is not new_client:
        try:
            await previous.close()
        except Exception as e:  # noqa: BLE001 — close must never block re-init
            logger.warning(
                "Failed to close previous AsyncVeraClient: %s", e
            )

    return new_client


def get_client() -> VeraClient:
    """Return the client registered via :func:`init`.

    If :func:`init` has not been called, returns a sentinel that raises
    :class:`VeraError` on any attribute access. This turns the
    "forgot to call init()" bug from a confusing
    ``AttributeError: 'NoneType' object has no attribute ...`` into an
    explicit message pointing at the docs. The sentinel is falsy, so
    existing ``if vera.get_client():`` checks still work.
    """
    return _initialized_client if _initialized_client is not None else _UNINITIALIZED  # type: ignore[return-value]


def get_async_client() -> AsyncVeraClient | None:
    """Return the client registered via :func:`init_async`, or ``None``."""
    return _initialized_async_client


__all__ = [
    # Sentry-style entry points
    "init",
    "init_async",
    "init_async_awaitable",
    "get_client",
    "get_async_client",
    # Clients
    "VeraClient",
    "AsyncVeraClient",
    # Decorators
    "audit",
    "async_audit",
    "gate",
    "is_bypassing_gates",
    "set_default_client",
    "set_default_async_client",
    # HITL approvals
    "ApprovalRejectedError",
    "ApprovalTimeoutError",
    # Redaction
    "Redactor",
    "set_default_redactor",
    "get_default_redactor",
    # Tenant resolver (Phase 1 PR 7 / Stream D3)
    "tenant",
    "set_tenant",
    "reset_tenant",
    "get_tenant",
    "get_default_tenant",
    "set_default_tenant",
    "resolve_tenant",
    "copy_context_to_thread",
    # agent_type global (Phase 1 PR 8 / Stream D7)
    "set_default_agent_type",
    "get_default_agent_type",
    "resolve_agent_type",
    # Branded errors — transport layer (existing 7)
    "VeraError",
    "VeraAuthError",
    "VeraRateLimitError",
    "VeraServerError",
    "VeraTimeoutError",
    "VeraNetworkError",
    "VeraValidationError",
    "VeraClientError",
    # Branded errors — domain layer (new 5, Phase 1 PR 6)
    "PolicyBlock",
    "PendingReview",
    "WrongKeyTier",
    "TenantMissingOrInvalid",
    "ReviewerCredentialsInsufficient",
    # Wave 2C PR B2
    "RequiresDeferredReview",
    # Back-compat aliases (deprecated)
    "ActionLedgerClient",
    "AsyncActionLedgerClient",
]
