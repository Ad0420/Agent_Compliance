"""Decorator-level tests for the switch to ``enqueue_action`` (workstream A1).

These pin the decorator behaviour so a future refactor can't silently flip
the sync ``@audit`` back to a blocking ``record_action`` call. The contract
is:

* ``@audit`` (sync) calls ``enqueue_action`` and never ``record_action``.
* ``@async_audit`` (async function) defaults to ``enqueue_action`` and
  only calls ``record_action`` when ``blocking=True`` is opted-in.
* ``@async_audit`` (sync function path) always uses ``enqueue_action``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vera.async_decorator import async_audit
from vera.decorator import audit


# ---------------------------------------------------------------------------
# Sync decorator
# ---------------------------------------------------------------------------


def test_decorator_calls_enqueue_not_record_on_success():
    mock_client = MagicMock()

    @audit(action_name="t", client=mock_client)
    def f():
        return 1

    f()
    mock_client.enqueue_action.assert_called_once()
    mock_client.record_action.assert_not_called()


def test_decorator_calls_enqueue_not_record_on_failure():
    mock_client = MagicMock()

    @audit(action_name="t", client=mock_client)
    def f():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        f()
    mock_client.enqueue_action.assert_called_once()
    mock_client.record_action.assert_not_called()


# ---------------------------------------------------------------------------
# Async decorator — async function
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_decorator_uses_enqueue_by_default():
    mock_client = MagicMock()
    mock_client.enqueue_action = MagicMock()
    mock_client.record_action = AsyncMock()

    @async_audit(action_name="t", client=mock_client)
    async def f():
        return 1

    await f()
    mock_client.enqueue_action.assert_called_once()
    mock_client.record_action.assert_not_called()


@pytest.mark.asyncio
async def test_async_decorator_uses_record_when_blocking():
    mock_client = MagicMock()
    mock_client.enqueue_action = MagicMock()
    mock_client.record_action = AsyncMock()

    @async_audit(action_name="t", client=mock_client, blocking=True)
    async def f():
        return 1

    await f()
    mock_client.record_action.assert_awaited_once()
    mock_client.enqueue_action.assert_not_called()


# ---------------------------------------------------------------------------
# Async decorator — sync function path
# ---------------------------------------------------------------------------


def test_async_decorator_sync_wrapper_uses_enqueue():
    mock_client = MagicMock()
    mock_client.enqueue_action = MagicMock()

    @async_audit(action_name="t", client=mock_client)
    def f():
        return 1

    f()
    mock_client.enqueue_action.assert_called_once()
