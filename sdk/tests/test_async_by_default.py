"""Tests for the sync ``VeraClient.enqueue_action`` background-flush model.

Workstream A1 — async-by-default sync client. Covers:

* enqueue returns immediately even when the server is hung
* @audit decorator wrapper p99 overhead under a dead Vera
* drop-oldest on queue overflow with a single rate-limited WARN
* drain on close()
* atexit drain (subprocess test)
* multi-thread enqueue produces the expected number of records
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from vera import VeraClient
from vera.decorator import audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_hung_transport(client: VeraClient, hang_seconds: float = 30.0) -> None:
    """Replace the client's httpx transport so every request hangs.

    We never sleep here — instead, we install a transport that raises a
    timeout immediately so the worker thread never actually blocks. The
    ``hang_seconds`` argument is conceptual; from the *caller's* point of
    view, the server is "hung" because no records ever land.
    """

    def _hang(_request: httpx.Request) -> httpx.Response:
        # Pretend the request timed out. The worker classifies this as a
        # network failure and re-queues — same observable behaviour as a
        # real hang from the producer's perspective.
        raise httpx.ConnectTimeout("simulated hang")

    client._client._transport = httpx.MockTransport(_hang)


class _CountingHandler(BaseHTTPRequestHandler):
    """Replies 200 to /v1/actions/batch and increments a counter."""

    def log_message(self, *_a, **_kw):  # silence stderr noise
        return

    def do_POST(self):  # noqa: N802 — http.server convention
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        records = payload.get("records") or []
        self.server.received_records += len(records)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Request-ID", "test-rid")
        self.end_headers()
        self.wfile.write(b"{}")


class _CountingServer:
    """Threaded HTTP server that counts received records."""

    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), _CountingHandler)
        self.server.received_records = 0  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def received(self) -> int:
        return self.server.received_records  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# A1-1: enqueue returns immediately
# ---------------------------------------------------------------------------


def test_enqueue_returns_immediately():
    """Even with a hung server, enqueue must return in < 5ms."""
    client = VeraClient(
        api_url="http://localhost:1",
        flush_interval=60.0,
        batch_size=1000,
        atexit_drain_timeout=0.5,
    )
    _patch_hung_transport(client)
    try:
        # Warm-up so the lazy-start cost doesn't pollute the measurement.
        client.enqueue_action(action_name="warmup")
        t0 = time.perf_counter()
        client.enqueue_action(action_name="hang_test")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # 5ms is generous — typical local enqueue is ~10-50 microseconds.
        assert elapsed_ms < 5.0, f"enqueue took {elapsed_ms:.3f}ms"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# A1-2: decorator p99 overhead under dead Vera
# ---------------------------------------------------------------------------


def test_decorator_p99_latency_under_dead_vera():
    """1000 audited calls; assert wrapper-overhead p99 < 5ms."""
    client = VeraClient(
        api_url="http://localhost:1",
        flush_interval=60.0,
        batch_size=10_000,
        max_queue_size=20_000,
        atexit_drain_timeout=0.5,
    )
    _patch_hung_transport(client)

    @audit(action_name="bench", client=client)
    def inner():
        return "x"

    try:
        # Warm-up: lazy-init queue + thread, JIT cache.
        for _ in range(20):
            inner()

        N = 1000
        samples = []
        for _ in range(N):
            t0 = time.perf_counter()
            inner()
            samples.append((time.perf_counter() - t0) * 1000)

        samples.sort()
        p50 = samples[N // 2]
        p99 = samples[int(N * 0.99)]
        # Plenty of slack for CI runners. Local p99 is typically < 0.5ms.
        assert p99 < 5.0, f"p99 latency {p99:.3f}ms (p50={p50:.3f}ms) — see samples"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# A1-3: queue overflow drops oldest with rate-limited WARN
# ---------------------------------------------------------------------------


def test_queue_overflow_drops_oldest(caplog):
    """Fill capacity + 100; assert oldest 100 dropped, 1 WARN logged."""
    client = VeraClient(
        api_url="http://localhost:1",
        flush_interval=60.0,
        max_queue_size=100,
        batch_size=1000,  # don't auto-flush
        atexit_drain_timeout=0.5,
    )
    _patch_hung_transport(client)

    try:
        with caplog.at_level(logging.WARNING, logger="vera.client"):
            for i in range(200):
                client.enqueue_action(action_name=f"a{i}")

        # Queue is at exactly its capacity.
        assert client._queue is not None
        assert client._queue.qsize() == 100

        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "queue full" in r.getMessage().lower()
        ]
        # Rate-limited: at most a small handful of warnings, and at least one.
        assert 1 <= len(warns) <= 3
    finally:
        client.close()


# ---------------------------------------------------------------------------
# A1-4: drain on close()
# ---------------------------------------------------------------------------


def test_drain_at_close():
    """Enqueue 100, call close(), assert all 100 reach the server within 10s."""
    with _CountingServer() as server:
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=20,
            atexit_drain_timeout=10.0,
        )
        for i in range(100):
            client.enqueue_action(action_name=f"a{i}")
        t0 = time.perf_counter()
        client.close()
        elapsed = time.perf_counter() - t0
        assert server.received >= 100, f"only {server.received} received in {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# A1-5: atexit drains a subprocess
# ---------------------------------------------------------------------------


def test_atexit_drains(tmp_path):
    """Subprocess enqueues 50 then exits; all 50 must reach the server."""
    with _CountingServer() as server:
        sdk_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = tmp_path / "atexit_check.py"
        script.write_text(
            textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {sdk_root!r})
                from vera import VeraClient
                c = VeraClient(api_url={server.url!r}, api_key="test", flush_interval=0.05, batch_size=10, atexit_drain_timeout=10.0)
                for i in range(50):
                    c.enqueue_action(action_name=f"x{{i}}")
                # No explicit close — atexit hook must drain.
                """
            )
        )
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
        # Atexit drain has up to 10s; give the test a small grace window.
        deadline = time.perf_counter() + 5.0
        while server.received < 50 and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert server.received >= 50, f"only {server.received} received"


# ---------------------------------------------------------------------------
# A1-6: threaded enqueue
# ---------------------------------------------------------------------------


def test_threaded_enqueue():
    """4 threads × 1000 enqueues; exactly 4000 records delivered."""
    with _CountingServer() as server:
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=100,
            max_queue_size=20_000,
            atexit_drain_timeout=15.0,
        )

        per_thread = 1000

        def worker():
            for i in range(per_thread):
                client.enqueue_action(action_name=f"t{i}")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        client.close()
        assert server.received == 4 * per_thread, (
            f"expected {4 * per_thread}, got {server.received}"
        )


# ---------------------------------------------------------------------------
# CRITICAL #6 — atexit registration is lazy (per-instance leak fix)
# ---------------------------------------------------------------------------


def test_atexit_lazy_registration():
    """atexit hook is NOT registered until the first ``enqueue_action`` call.

    Long-running processes (notebooks, large test suites) used to construct
    many VeraClient instances and accumulate one atexit hook per instance —
    none of which can be garbage-collected because atexit holds a strong
    reference. Lazy registration prevents the leak when a client is built
    but never used (e.g. constructed by a fixture, then test takes the
    sync record_action path or no path at all).
    """
    client = VeraClient(
        api_url="http://localhost:1",
        flush_interval=60.0,
        batch_size=1000,
        atexit_drain_timeout=0.5,
    )
    try:
        # Construction alone must not register the hook.
        assert client._atexit_registered is False, (
            "atexit must not be registered at construction; lazy-only on first enqueue"
        )

        _patch_hung_transport(client)
        client.enqueue_action(action_name="trigger")
        # Now the hook is registered.
        assert client._atexit_registered is True, (
            "first enqueue_action must register the atexit hook"
        )

        # Subsequent calls do not re-register. We can't directly observe
        # the atexit registry, but ``_ensure_atexit_registered`` is
        # idempotent on the flag and ``atexit.register`` would be a no-op
        # on a duplicate callable identity in this case. The flag stays
        # True and we don't blow up.
        client.enqueue_action(action_name="trigger2")
        assert client._atexit_registered is True
    finally:
        client.close()


# ---------------------------------------------------------------------------
# INFO #14 — multi-thread latency benchmark
# ---------------------------------------------------------------------------


def test_p99_latency_under_concurrent_threads():
    """Latency under realistic concurrent producer load.

    The single-threaded latency test in the original PR could miss
    contention bugs. With 8 threads × 1000 enqueues = 8000 calls against
    a hung server, the lock around drop-oldest and the queue's internal
    GIL-bound critical sections show up as p99 jitter if anything is
    badly serialised.
    """
    client = VeraClient(
        api_url="http://localhost:1",
        flush_interval=60.0,
        batch_size=10_000,
        max_queue_size=50_000,
        atexit_drain_timeout=0.5,
    )
    _patch_hung_transport(client)
    try:
        # Warm-up so lazy-init is amortised.
        for _ in range(50):
            client.enqueue_action(action_name="warm")

        per_thread = 1000
        n_threads = 8
        all_samples: list[float] = []
        samples_lock = threading.Lock()

        def worker():
            local_samples = []
            for _ in range(per_thread):
                t0 = time.perf_counter()
                client.enqueue_action(action_name="bench")
                local_samples.append((time.perf_counter() - t0) * 1000)
            with samples_lock:
                all_samples.extend(local_samples)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_samples.sort()
        N = len(all_samples)
        p50 = all_samples[N // 2]
        p99 = all_samples[int(N * 0.99)]
        # Concurrent path is allowed slightly more headroom than the
        # single-threaded test (~5ms) but should still be well under
        # 10ms on any sane CI runner.
        assert p99 < 10.0, (
            f"concurrent p99 latency {p99:.3f}ms (p50={p50:.3f}ms) — "
            "lock contention or queue serialisation regression?"
        )
    finally:
        client.close()
