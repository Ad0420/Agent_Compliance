"""Poison-batch handling tests for the sync + async clients (workstream A8).

Failures are classified into:

* permanent (4xx other than 429) — log ERROR, drop, do not re-queue
* transient (429 / 5xx / network / timeout) — re-queue with backoff
* circuit breaker — pause flushing after N consecutive failures
* re-queue cap — drop a record after K re-queue attempts to prevent infinite
  CPU burn on a poison record stuck in failure mode

The tests drive ``_drain_once`` (sync) and ``_flush`` (async) directly with
mocked httpx transports so the assertions are deterministic.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from vera import AsyncVeraClient, VeraClient


# ---------------------------------------------------------------------------
# Helpers — install a deterministic transport on the underlying httpx client.
# ---------------------------------------------------------------------------


def _install_sync_transport(client: VeraClient, handler) -> None:
    client._client._transport = httpx.MockTransport(handler)


def _install_async_transport(client: AsyncVeraClient, handler) -> None:
    client._client._transport = httpx.MockTransport(handler)


def _make_sync_client(**kwargs) -> VeraClient:
    """Construct a sync client with the worker thread NOT started.

    We avoid lazy-start by never calling ``enqueue_action``; instead the
    tests put items directly on the queue and call ``_drain_once``
    synchronously so we can observe every state transition.
    """
    defaults: dict = dict(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=10,
        max_queue_size=1000,
        atexit_drain_timeout=0.1,
        circuit_breaker_threshold=2,
        requeue_max_attempts=3,
    )
    defaults.update(kwargs)
    c = VeraClient(**defaults)
    # Manually populate queue without launching the worker thread.
    import queue as _queue

    c._queue = _queue.Queue(maxsize=c._max_queue_size)
    c._owner_pid = -1  # sentinel so enqueue_action would still reinit
    return c


def _enqueue_direct(c: VeraClient, n: int) -> None:
    """Put records directly onto the queue, bypassing enqueue_action."""
    assert c._queue is not None
    for i in range(n):
        c._queue.put_nowait(
            {
                "agent_name": c.agent_name,
                "action_name": f"a{i}",
                "_requeue_count": 0,
            }
        )


# ---------------------------------------------------------------------------
# 4xx permanent-drop variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_4xx_permanent_drops_does_not_requeue(status, caplog):
    c = _make_sync_client()
    _install_sync_transport(c, lambda req: httpx.Response(status))
    _enqueue_direct(c, 3)
    with caplog.at_level(logging.ERROR, logger="vera.client"):
        c._drain_once()
    assert c._queue.empty(), "4xx must permanent-drop the batch"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "permanent drop must log at ERROR"
    # Class name is in the error message so customers can grep.
    msg = errors[0].getMessage()
    assert "Vera" in msg or "Validation" in msg or "Auth" in msg


# ---------------------------------------------------------------------------
# 5xx + 429 — re-queue with backoff
# ---------------------------------------------------------------------------


def test_5xx_requeues_with_backoff(caplog, monkeypatch):
    """5xx -> re-queue. Then a 200 success drains everything.

    We patch ``MAX_RETRIES`` to 1 so each ``_drain_once`` makes exactly one
    transport call — otherwise the retry-with-backoff loop inside
    ``_request_with_retry`` swallows the transient failures internally.
    """
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)

    state = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = _make_sync_client()
    _install_sync_transport(c, handler)
    _enqueue_direct(c, 4)
    c._drain_once()  # 503 — re-queues
    assert c._queue.qsize() == 4
    c._drain_once()  # 200 — drains
    assert c._queue.empty()


def test_429_requeues(monkeypatch):
    """429 must be treated like 5xx (re-queued)."""
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)

    state = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ok": True})

    c = _make_sync_client()
    _install_sync_transport(c, handler)
    _enqueue_direct(c, 2)
    c._drain_once()
    assert c._queue.qsize() == 2
    c._drain_once()
    assert c._queue.empty()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens(monkeypatch):
    """After threshold consecutive failures the breaker opens."""
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)
    c = _make_sync_client(circuit_breaker_threshold=2)
    _install_sync_transport(c, lambda req: httpx.Response(503))
    _enqueue_direct(c, 1)
    c._drain_once()  # failure 1
    assert c._breaker_open_until == 0.0
    _enqueue_direct(c, 1)
    c._drain_once()  # failure 2 — breaker opens
    assert c._breaker_open_until > 0.0


def test_circuit_breaker_resets_on_success(monkeypatch):
    """After a success the consecutive-failure count resets."""
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)

    state = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = _make_sync_client(circuit_breaker_threshold=10)
    _install_sync_transport(c, handler)
    _enqueue_direct(c, 1)
    c._drain_once()
    assert c._consecutive_failures == 1
    c._drain_once()  # 503 again -> 2 (records re-queued, retried, server fails)
    assert c._consecutive_failures == 2
    c._drain_once()  # 200 — counter resets
    assert c._consecutive_failures == 0
    assert c._breaker_open_until == 0.0


# ---------------------------------------------------------------------------
# Re-queue cap
# ---------------------------------------------------------------------------


def test_requeue_depth_cap(caplog, monkeypatch):
    """A poison record is dropped after ``requeue_max_attempts`` re-queues."""
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)
    c = _make_sync_client(requeue_max_attempts=3, circuit_breaker_threshold=100)
    _install_sync_transport(c, lambda req: httpx.Response(503))
    _enqueue_direct(c, 1)
    # 1st drain -> requeue_count=1, 2nd -> 2, 3rd -> 3, 4th -> would be 4 (cap)
    with caplog.at_level(logging.WARNING, logger="vera.client"):
        for _ in range(5):
            c._drain_once()
    assert c._queue.empty()
    # The cap WARN should have fired.
    cap_warns = [
        r for r in caplog.records
        if "poison-record cap" in r.getMessage()
    ]
    assert cap_warns, "expected a poison-cap WARN"


# ---------------------------------------------------------------------------
# Async client variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_4xx_permanent_drops(caplog):
    c = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=10,
        circuit_breaker_threshold=10,
    )
    _install_async_transport(c, lambda req: httpx.Response(401))
    c._queue.append({"agent_name": "a", "action_name": "x", "_requeue_count": 0})
    with caplog.at_level(logging.ERROR, logger="vera.async_client"):
        await c._flush()
    assert not c._queue
    assert any(r.levelno == logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_async_5xx_requeues(monkeypatch):
    import vera.async_client as acm

    monkeypatch.setattr(acm, "MAX_RETRIES", 1)
    monkeypatch.setattr(acm, "RETRY_BACKOFF_BASE", 0.0)

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=10,
    )
    _install_async_transport(c, handler)
    c._queue.append({"agent_name": "a", "action_name": "x", "_requeue_count": 0})
    await c._flush()
    assert len(c._queue) == 1
    await c._flush()
    assert not c._queue


@pytest.mark.asyncio
async def test_async_circuit_breaker(monkeypatch):
    import vera.async_client as acm

    monkeypatch.setattr(acm, "MAX_RETRIES", 1)
    monkeypatch.setattr(acm, "RETRY_BACKOFF_BASE", 0.0)
    c = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=10,
        circuit_breaker_threshold=2,
        requeue_max_attempts=100,
    )
    _install_async_transport(c, lambda req: httpx.Response(503))
    c._queue.append({"agent_name": "a", "action_name": "x", "_requeue_count": 0})
    await c._flush()
    assert c._breaker_open_until == 0.0
    c._queue.append({"agent_name": "a", "action_name": "y", "_requeue_count": 0})
    await c._flush()
    assert c._breaker_open_until > 0.0
