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

import logging
import os
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
from .errors import (
    VeraError,
    VeraAuthError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraNetworkError,
    VeraValidationError,
)

logger = logging.getLogger("vera.init")

# Back-compat aliases (deprecated — will be removed in v1.0)
ActionLedgerClient = VeraClient
AsyncActionLedgerClient = AsyncVeraClient


# Module-level handles to the client(s) registered via :func:`init` /
# :func:`init_async`. ``None`` means no init() has been called yet.
_initialized_client: VeraClient | None = None
_initialized_async_client: AsyncVeraClient | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-shaped env var.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Empty / unset / anything else → ``default``.
    """
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


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
        **client_kwargs: Passed through to :class:`VeraClient` (e.g.
            ``timeout``, ``batch_size``, ``redactor``).

    Returns:
        The configured :class:`VeraClient` (or :class:`vera.dev.DevClient`
        when dev mode is active).

    Calling :func:`init` twice replaces the previous default client. The
    old client's :meth:`VeraClient.close` is invoked first to drain its
    queue. Errors from ``close()`` are swallowed so a stuck previous client
    can't block re-initialisation.

    Example::

        import vera
        vera.init(api_key="al_live_...", agent_name="my-agent")

        @vera.audit(action_name="approve_loan")
        def approve(applicant_id, amount):
            ...
    """
    global _initialized_client

    dev_active = dev if dev is not None else _env_bool("VERA_DEV", default=False)

    if dev_active:
        from .dev import build_dev_client

        client: VeraClient = build_dev_client(
            agent_name=agent_name,
            **client_kwargs,
        )
    else:
        client = VeraClient(
            api_key=api_key,
            api_url=api_url,
            agent_name=agent_name,
            agent_version=agent_version,
            model_id=model_id,
            framework=framework,
            persistent_buffer_path=persistent_buffer_path,
            **client_kwargs,
        )

    if _initialized_client is not None and _initialized_client is not client:
        try:
            _initialized_client.close()
        except Exception:  # noqa: BLE001 — defensive: close() must never block re-init
            logger.debug("vera.init: previous client close() raised", exc_info=True)
    _initialized_client = client
    set_default_client(client)
    return client


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
    """Initialize Vera for async codepaths.

    Mirrors :func:`init` but constructs an :class:`AsyncVeraClient` and
    registers it via :func:`set_default_async_client`. Returns the client
    so callers can ``await client.close()`` at process shutdown — the
    async client's drain MUST be awaited explicitly (atexit cannot drive
    async cleanup reliably).

    Dev mode is intentionally not supported here — the sync :class:`DevClient`
    captures records synchronously and works fine inside async test
    fixtures. Use :func:`init(dev=True)` for that.
    """
    global _initialized_async_client

    client = AsyncVeraClient(
        api_key=api_key,
        api_url=api_url,
        agent_name=agent_name,
        agent_version=agent_version,
        model_id=model_id,
        framework=framework,
        persistent_buffer_path=persistent_buffer_path,
        **client_kwargs,
    )
    # Re-init: we can't await the previous client's close() from this sync
    # function, so we just drop the reference. Callers re-initialising
    # in-process should explicitly ``await old.close()`` themselves.
    _initialized_async_client = client
    set_default_async_client(client)
    return client


def get_client() -> VeraClient | None:
    """Return the client registered via :func:`init`, or ``None``."""
    return _initialized_client


def get_async_client() -> AsyncVeraClient | None:
    """Return the client registered via :func:`init_async`, or ``None``."""
    return _initialized_async_client


__all__ = [
    # Sentry-style entry points
    "init",
    "init_async",
    "get_client",
    "get_async_client",
    # Clients
    "VeraClient",
    "AsyncVeraClient",
    # Decorators
    "audit",
    "async_audit",
    "set_default_client",
    "set_default_async_client",
    # HITL approvals
    "ApprovalRejectedError",
    "ApprovalTimeoutError",
    # Redaction
    "Redactor",
    "set_default_redactor",
    "get_default_redactor",
    # Branded errors
    "VeraError",
    "VeraAuthError",
    "VeraRateLimitError",
    "VeraServerError",
    "VeraTimeoutError",
    "VeraNetworkError",
    "VeraValidationError",
    # Back-compat aliases (deprecated)
    "ActionLedgerClient",
    "AsyncActionLedgerClient",
]
