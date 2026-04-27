from .client import (
    VeraClient,
    ApprovalRejectedError,
    ApprovalTimeoutError,
)
from .decorator import audit, set_default_client
from .async_client import AsyncVeraClient
from .async_decorator import async_audit, set_default_async_client

# Back-compat aliases (deprecated — will be removed in v1.0)
ActionLedgerClient = VeraClient
AsyncActionLedgerClient = AsyncVeraClient

__all__ = [
    "VeraClient",
    "audit",
    "set_default_client",
    "AsyncVeraClient",
    "async_audit",
    "set_default_async_client",
    "ApprovalRejectedError",
    "ApprovalTimeoutError",
    # Back-compat aliases (deprecated)
    "ActionLedgerClient",
    "AsyncActionLedgerClient",
]
