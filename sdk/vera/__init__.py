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
    # Redaction
    "Redactor",
    "set_default_redactor",
    "get_default_redactor",
    # Back-compat aliases (deprecated)
    "ActionLedgerClient",
    "AsyncActionLedgerClient",
]
