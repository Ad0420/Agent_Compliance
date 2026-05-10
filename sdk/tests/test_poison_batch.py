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
import os
import time

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
# CRITICAL #4 — permanent-failure breaker blocks enqueue
# ---------------------------------------------------------------------------


def test_permanent_4xx_breaker_blocks_enqueue(caplog, monkeypatch):
    """Persistent 401 must trip the permanent breaker; new enqueues are refused.

    Reproduces the customer-with-bad-API-key failure mode:
    - server returns 401 forever
    - the queue keeps accepting until it overflows, drops oldest, and the
      customer silently loses every audit record
    - one ERROR per process surfaces the misconfiguration so the customer
      can't miss it

    The transient-5xx path is exercised by
    ``test_transient_5xx_breaker_does_not_block_enqueue`` below — that
    path MUST keep accepting records (the queue is the buffer for retry).
    """
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    cm._reset_permanent_breaker_warning()

    c = _make_sync_client(circuit_breaker_threshold=2)
    _install_sync_transport(c, lambda req: httpx.Response(401))

    # Drain twice with 401s — the breaker opens with cause="permanent".
    # Keep RETRY_BACKOFF_BASE at the production default so the breaker's
    # ``open_until`` timestamp is meaningfully in the future.
    _enqueue_direct(c, 1)
    c._drain_once()
    _enqueue_direct(c, 1)
    c._drain_once()
    assert c._breaker_open_until > time.monotonic(), (
        "breaker open_until must be in the future to gate enqueue"
    )
    assert c._breaker_cause == "permanent"

    # The helper installs a sentinel _owner_pid so enqueue_action would
    # call _init_runtime_state and reset the queue. For the assertion
    # below we want enqueue_action to take the breaker-rejection path
    # WITHOUT rebuilding state. Pin pid so the fork-safety fast path
    # short-circuits.
    c._owner_pid = os.getpid()

    # Now the customer's code keeps calling enqueue_action. Records MUST
    # NOT be added — we'd silently fill the queue while every flush was
    # rejected.
    queue_size_before = c._queue.qsize()
    with caplog.at_level(logging.ERROR, logger="vera.client"):
        for i in range(50):
            c.enqueue_action(action_name=f"after_breaker_{i}")
    assert c._queue.qsize() == queue_size_before, (
        f"permanent breaker must refuse new enqueues; "
        f"queue grew from {queue_size_before} to {c._queue.qsize()}"
    )
    permanent_errors = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "PERMANENT failure" in r.getMessage()
    ]
    # Exactly one ERROR — once-per-client-instance, not per call.
    assert len(permanent_errors) == 1, (
        f"expected exactly 1 ERROR for permanent breaker, got {len(permanent_errors)}"
    )


def test_transient_5xx_breaker_does_not_block_enqueue(monkeypatch):
    """Persistent 5xx opens the breaker but enqueue STILL accepts records.

    The whole point of the queue is to buffer through transient outages.
    A 5xx (or network error) breaker must NOT stop the producer — when
    Vera comes back, the buffered records flush.
    """
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)
    cm._reset_permanent_breaker_warning()

    c = _make_sync_client(circuit_breaker_threshold=2, requeue_max_attempts=100)
    _install_sync_transport(c, lambda req: httpx.Response(503))

    _enqueue_direct(c, 1)
    c._drain_once()
    _enqueue_direct(c, 1)
    c._drain_once()
    # Force a future breaker window so the breaker check is meaningful
    # (RETRY_BACKOFF_BASE=0 makes the natural window 0.0).
    c._breaker_open_until = time.monotonic() + 60.0
    assert c._breaker_cause == "transient"

    # Pin pid so enqueue_action's fork-safety fast path doesn't reset
    # the queue when called from this test.
    c._owner_pid = os.getpid()

    # Queue must still accept new records — it's the retry buffer.
    queue_size_before = c._queue.qsize()
    for i in range(20):
        c.enqueue_action(action_name=f"during_5xx_{i}")
    assert c._queue.qsize() == queue_size_before + 20, (
        "transient breaker must NOT block enqueue — the queue is the retry buffer"
    )


def test_permanent_breaker_resets_on_successful_flush(monkeypatch):
    """A successful flush after a permanent failure clears the breaker cause.

    Some failure modes are transient-permanent (e.g. brief 401 during a
    secret rotation that resolves itself). Once a flush succeeds, the
    breaker MUST clear so enqueue_action goes back to accepting records.
    """
    import vera.client as cm

    monkeypatch.setattr(cm, "MAX_RETRIES", 1)
    monkeypatch.setattr(cm, "RETRY_BACKOFF_BASE", 0.0)
    cm._reset_permanent_breaker_warning()

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        if state["calls"] <= 2:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    c = _make_sync_client(circuit_breaker_threshold=2)
    _install_sync_transport(c, handler)
    _enqueue_direct(c, 1)
    c._drain_once()
    _enqueue_direct(c, 1)
    c._drain_once()
    assert c._breaker_cause == "permanent"

    # Force breaker to be already-elapsed so the next drain runs.
    c._breaker_open_until = 0.0
    _enqueue_direct(c, 1)
    c._drain_once()  # 200 — clears the breaker cause
    assert c._breaker_cause is None

    # enqueue_action accepts records again.
    pre = c._queue.qsize()
    c.enqueue_action(action_name="after_recovery")
    assert c._queue.qsize() == pre + 1


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
# CRITICAL #5 — wrap_httpx_error covers every httpx exception class
# ---------------------------------------------------------------------------


def test_wrap_httpx_error_handles_all_exception_classes():
    """Every httpx error subclass we'd see in production maps to a VeraError.

    Previously: ``LocalProtocolError``, ``DecodingError``, ``TooManyRedirects``,
    ``ProxyError``, ``UnsupportedProtocol`` fell through to "return exc" —
    customers caught raw httpx exceptions instead of a branded VeraError,
    breaking the SDK's "you only need to know vera.errors" promise.
    """
    from vera.client import wrap_httpx_error
    from vera.errors import (
        VeraAuthError,
        VeraError,
        VeraNetworkError,
        VeraRateLimitError,
        VeraServerError,
        VeraTimeoutError,
        VeraValidationError,
    )

    fake_request = httpx.Request("POST", "http://localhost/v1/actions/batch")

    def _status_error(code: int) -> httpx.HTTPStatusError:
        resp = httpx.Response(code, request=fake_request)
        return httpx.HTTPStatusError(f"HTTP {code}", request=fake_request, response=resp)

    cases: list[tuple[Exception, type]] = [
        # --- HTTP status branches ---
        (_status_error(401), VeraAuthError),
        (_status_error(403), VeraAuthError),
        (_status_error(429), VeraRateLimitError),
        (_status_error(500), VeraServerError),
        (_status_error(502), VeraServerError),
        (_status_error(503), VeraServerError),
        (_status_error(400), VeraValidationError),
        (_status_error(404), VeraValidationError),
        (_status_error(422), VeraValidationError),
        # --- Timeout family ---
        (httpx.TimeoutException("slow"), VeraTimeoutError),
        (httpx.ConnectTimeout("connect timeout"), VeraTimeoutError),
        (httpx.ReadTimeout("read timeout"), VeraTimeoutError),
        (httpx.WriteTimeout("write timeout"), VeraTimeoutError),
        (httpx.PoolTimeout("pool timeout"), VeraTimeoutError),
        # --- Network / transport family ---
        (httpx.ConnectError("dns fail"), VeraNetworkError),
        (httpx.NetworkError("net"), VeraNetworkError),
        (httpx.RemoteProtocolError("remote"), VeraNetworkError),
        (httpx.LocalProtocolError("local"), VeraNetworkError),
        (httpx.ProxyError("proxy"), VeraNetworkError),
        (httpx.UnsupportedProtocol("unsupported"), VeraNetworkError),
        # --- Decode / redirect ---
        (httpx.DecodingError("decode"), VeraNetworkError),
        (httpx.TooManyRedirects("loop"), VeraServerError),
    ]
    for exc, expected_cls in cases:
        wrapped = wrap_httpx_error(exc)
        assert isinstance(wrapped, expected_cls), (
            f"{type(exc).__name__} must wrap to {expected_cls.__name__}, "
            f"got {type(wrapped).__name__}"
        )

    # Catch-all: an exotic httpx.HTTPError subclass we never enumerated must
    # still wrap to VeraError, never leak as raw httpx.
    class _NovelHttpxError(httpx.HTTPError):
        pass

    wrapped = wrap_httpx_error(_NovelHttpxError("novel"))
    assert isinstance(wrapped, VeraError), (
        "every httpx.HTTPError descendant must wrap to a VeraError subclass"
    )

    # Non-httpx exceptions pass through unchanged so we don't mask
    # non-network bugs.
    bug = ValueError("not an httpx error")
    assert wrap_httpx_error(bug) is bug


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
async def test_concurrent_flush_serializes(monkeypatch):
    """Two concurrent ``_flush`` calls must produce exactly one batch on the wire.

    CRITICAL #3 in the async-by-default review: ``_flush`` had no mutex.
    The periodic flush_loop tick and the on-overflow ``create_task`` from
    ``enqueue_action`` could both ``popleft`` from the same deque. Without
    the lock, two tasks split the queue, each sent a partial batch, and
    we observed interleaved POSTs in production.

    With the ``asyncio.Lock`` added in this PR, the second caller waits;
    only one batch goes out per cycle and no record is double-sent.
    """
    import asyncio as _asyncio

    posted_batches: list[list[dict]] = []

    async def slow_handler(req):
        # Simulate latency so the second concurrent flush has a chance to
        # observe the queue mid-drain. Without the lock the second flush
        # would popleft the (now-empty) queue and observe records that
        # the first flush had already taken.
        body = req.content
        import json as _json
        payload = _json.loads(body)
        posted_batches.append(payload.get("records", []))
        await _asyncio.sleep(0.05)
        return httpx.Response(200, json={"ok": True})

    c = AsyncVeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=10,
        circuit_breaker_threshold=10,
    )
    _install_async_transport(c, slow_handler)
    # Pre-load queue with enough for one batch.
    for i in range(10):
        c._queue.append(
            {
                "agent_name": "a",
                "action_name": f"x{i}",
                "_requeue_count": 0,
                "_idempotency_key": f"k{i}",
            }
        )

    # Kick off two concurrent flushes. Without the lock, both would
    # popleft and the second would observe an empty queue (or a partial
    # one, depending on timing) — one of them would no-op and we'd lose
    # ordering, OR both would split the items.
    t1 = _asyncio.create_task(c._flush())
    t2 = _asyncio.create_task(c._flush())
    await _asyncio.gather(t1, t2)

    # Exactly one batch hit the wire — the other call observed the lock
    # held, then saw an empty queue under the lock and returned.
    assert len(posted_batches) == 1, (
        f"expected exactly 1 batch on the wire, got {len(posted_batches)} "
        "— concurrent _flush calls split the queue"
    )
    assert len(posted_batches[0]) == 10
    # Queue must be empty — no record stranded by the racing pop.
    assert len(c._queue) == 0


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
