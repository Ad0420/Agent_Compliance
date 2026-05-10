"""Tests for ``AsyncVeraClient.enqueue_action`` from sync contexts.

CRITICAL #2 in the async-by-default review: the original implementation
called ``asyncio.create_task`` unconditionally inside ``enqueue_action``,
which raises ``RuntimeError`` when no event loop is running. The
``@async_audit`` sync-wrapper branch hits this path, and its broad
``except Exception`` swallowed the error — every audit record was silently
dropped before reaching the queue.

The fix: guard the ``create_task`` call. When no loop is running we still
buffer the record on the deque (so the next async caller can flush it) but
skip scheduling a flush.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from vera import AsyncVeraClient
from vera.async_decorator import async_audit, set_default_async_client


def _install_async_transport(client: AsyncVeraClient, handler) -> None:
    client._client._transport = httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# CRITICAL #2 — the production-fatal case
# ---------------------------------------------------------------------------


def test_async_enqueue_from_sync_context_no_loop_does_not_drop():
    """Filling past batch_size from sync code must NOT raise and must NOT lose records.

    Reproduces the exact failure mode the adversarial review surfaced:
    ``async_audit``'s sync-wrapper branch calls ``enqueue_action`` from
    plain sync code with no running event loop. The previous
    ``asyncio.create_task`` raised ``RuntimeError``; the decorator's
    broad ``except Exception`` swallowed it — silent record drop on every
    audited call once the queue had ``batch_size`` items.

    Now: records remain on the deque; no exception is raised.
    """
    client = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=5,
        max_queue_size=1000,
    )
    # Enqueue more than batch_size from a sync function — no
    # ``asyncio.run``, no ``loop.run_until_complete``, no running loop at
    # all.
    for i in range(20):
        client.enqueue_action(action_name=f"sync_call_{i}", action_type="x", result="success")

    # Records must be queued, not dropped.
    assert len(client._queue) == 20, (
        f"expected 20 queued records, got {len(client._queue)} — sync-context "
        "path silently dropped records"
    )
    # Sanity: action_name preserved
    queued_names = [r["action_name"] for r in client._queue]
    assert queued_names[0] == "sync_call_0"
    assert queued_names[-1] == "sync_call_19"


def test_async_enqueue_from_sync_context_warns_once(caplog):
    """We warn once per process when the no-loop branch fires — not per call."""
    client = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=2,
        max_queue_size=1000,
    )
    # Reset the once-flag in case another test in this session tripped it.
    client._sync_no_loop_warned = False

    with caplog.at_level(logging.WARNING, logger="vera.async_client"):
        for i in range(10):
            client.enqueue_action(action_name=f"x{i}")

    no_loop_warns = [
        r for r in caplog.records
        if "no running event loop" in r.getMessage()
    ]
    # Exactly one warning even though we crossed batch_size five times.
    assert len(no_loop_warns) == 1, (
        f"expected exactly 1 no-loop warning, got {len(no_loop_warns)}"
    )


def test_async_decorator_sync_wrapper_does_not_drop_records():
    """End-to-end: ``@async_audit`` on a sync function still queues records.

    This was the visible symptom — customers using ``@async_audit`` from
    sync code lost every audit record once the queue crossed ``batch_size``.
    """
    client = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=3,
        max_queue_size=1000,
    )
    set_default_async_client(client)

    @async_audit(action_name="my_op")
    def do_work(x: int) -> int:
        return x * 2

    try:
        # Call enough times to cross batch_size and hit the create_task
        # branch repeatedly from a fully-sync stack.
        results = [do_work(i) for i in range(10)]
        assert results == [i * 2 for i in range(10)]

        # Each successful call enqueues one record; no records should be
        # silently dropped by the decorator's swallowed RuntimeError.
        assert len(client._queue) == 10, (
            f"expected 10 records queued through @async_audit sync wrapper, "
            f"got {len(client._queue)}"
        )
    finally:
        set_default_async_client(None)


# ---------------------------------------------------------------------------
# Sanity: from inside a running loop, create_task DOES fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_enqueue_inside_running_loop_schedules_flush():
    """When a loop is running, the on-overflow ``create_task`` still fires."""
    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        return httpx.Response(200, json={"ok": True})

    client = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=3,
        max_queue_size=1000,
    )
    _install_async_transport(client, handler)

    for i in range(3):
        client.enqueue_action(action_name=f"a{i}")
    # Yield once so the create_task'd flush runs.
    await asyncio.sleep(0)
    # Allow another tick for the awaited POST to complete.
    for _ in range(10):
        if state["calls"] >= 1:
            break
        await asyncio.sleep(0.01)
    assert state["calls"] >= 1, "scheduled flush did not run inside a running loop"
