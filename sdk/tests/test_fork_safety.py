"""Fork-safety tests for :class:`VeraClient` (workstream A7).

The sync client tracks ``os.getpid()`` and re-initialises its queue +
worker thread on the first ``enqueue_action`` call inside a forked child.
A proactive ``os.register_at_fork`` handler does the same eagerly when the
platform supports it.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vera import VeraClient


pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(os, "fork"),
    reason="fork() not available on this platform",
)


# ---------------------------------------------------------------------------
# In-process counting server (shared with test_async_by_default but kept
# local so tests don't depend on each other's helpers).
# ---------------------------------------------------------------------------


class _CountingHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a, **_kw):
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        records = payload.get("records") or []
        # Lock-protected — under ThreadingHTTPServer multiple handler
        # threads can call do_POST concurrently, so a plain ``+=`` would
        # race and lose increments.
        with self.server.counter_lock:  # type: ignore[attr-defined]
            self.server.received_records += len(records)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


class _CountingServer:
    def __init__(self):
        # ThreadingHTTPServer instead of HTTPServer: the multiprocessing
        # test fires 4 worker processes at the mock server concurrently. A
        # single-threaded HTTPServer can only accept one connection at a
        # time — the rest sit in the kernel listen backlog or, when that
        # fills up, get ECONNREFUSED on Linux. The Vera SDK then burns its
        # 5s drain window retrying with 0.5s/1s/2s backoff and silently
        # drops batches. Threading makes the server actually concurrent.
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _CountingHandler)
        self.server.received_records = 0  # type: ignore[attr-defined]
        self.server.counter_lock = threading.Lock()  # type: ignore[attr-defined]
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
# A7-1: parent + forked child both succeed
# ---------------------------------------------------------------------------


def test_fork_after_init():
    """Parent enqueues, forks; child enqueues; both records reach the server."""
    with _CountingServer() as server:
        parent = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=5,
            atexit_drain_timeout=5.0,
        )
        # Parent gets a head-start so the worker thread is alive before fork.
        parent.enqueue_action(action_name="parent")
        time.sleep(0.1)

        pid = os.fork()
        if pid == 0:
            # Child branch.
            try:
                # First enqueue must trigger queue+thread reinit.
                parent.enqueue_action(action_name="child")
                # Drain.
                parent._atexit_drain_timeout = 5.0
                parent.close()
            finally:
                os._exit(0)
        else:
            # Parent waits for child + drains its own.
            os.waitpid(pid, 0)
            parent.close()
            # We can't guarantee the order because fork inherits the queue
            # state, so we just verify both records arrived.
            deadline = time.perf_counter() + 5.0
            while server.received < 2 and time.perf_counter() < deadline:
                time.sleep(0.05)
            assert server.received >= 2, f"only {server.received} records"


# ---------------------------------------------------------------------------
# A7-2: multiprocessing pool — each worker has its own background thread
# ---------------------------------------------------------------------------


# Module-level so the Pool can pickle it. This client is constructed in the
# parent and the Pool's fork-mode workers inherit a copy. Each child must
# notice the pid mismatch on first enqueue and reinit its own queue+thread.
_pool_client_holder: dict[str, VeraClient] = {}


def _pool_init(api_url: str) -> None:
    _pool_client_holder["c"] = VeraClient(
        api_url=api_url,
        api_key="test",
        flush_interval=0.05,
        batch_size=20,
        # Generous drain window: 4 workers contend for the same mock
        # server, and on Linux CI runners under load a tight 5s window
        # was insufficient for all batches to make the round-trip.
        atexit_drain_timeout=30.0,
    )


def _pool_worker(n: int) -> int:
    c = _pool_client_holder["c"]
    for i in range(n):
        c.enqueue_action(action_name=f"w{i}")
    # Explicit flush BEFORE close: blocks until the queue is empty so we
    # don't race close()'s atexit_drain_timeout window. Without this,
    # close()'s deadline can fire while batches are still in-flight (or
    # mid-retry on a slow CI runner) and records get dropped.
    c.flush(timeout=30.0)
    # Force final teardown.
    c.close()
    return n


def test_child_only_enqueue_after_parent_warmed_connection():
    """After fork(), the child can flush even when the parent already had open connections.

    CRITICAL #7 in the async-by-default review. The original
    ``_after_in_child`` reset ``_queue``, ``_thread``, ``_lock``,
    ``_owner_pid`` but NOT ``self._client`` (the ``httpx.Client``). On
    ``os.fork()`` the child inherits the parent's TCP connections + TLS
    session state. If the parent had already made a request (warmed the
    pool), the child's first POST hits a socket in undefined state —
    interleaved bytes (worst case) or a hung connection (best case).

    This is the gunicorn ``--preload`` / Celery prefork / multiprocessing
    failure mode: parent imports + warms client, then forks worker
    children, every child silently corrupts requests.

    The previous ``test_fork_after_init`` masked this because the parent
    *also* enqueued, so its still-working connection accepted the child's
    re-queued payloads — the child's broken connection was never actually
    used. This test deliberately keeps the parent OUT of the post-fork
    write path so any child-side socket corruption is fatal.
    """
    with _CountingServer() as server:
        parent = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=10,
            atexit_drain_timeout=5.0,
        )
        # Warm the parent's connection pool — open at least one TCP
        # connection so the child inherits an in-use socket. We use
        # record_action (sync, blocking) because it goes via the same
        # httpx.Client and we know it round-trips.
        parent.record_action(action_name="parent_warmup")
        # Allow the response to fully flush.
        time.sleep(0.1)
        parent_received = server.received

        pid = os.fork()
        if pid == 0:
            # Child only: no parent activity after this point. If the
            # child reuses the parent's TCP socket, requests will
            # interleave or hang and ``close()`` will time out without
            # delivering records.
            try:
                for i in range(50):
                    parent.enqueue_action(
                        action_name=f"child_{i}",
                        action_type="x",
                        result="success",
                    )
                # Force a drain on the child's brand-new httpx.Client.
                parent.close()
                os._exit(0)
            except BaseException:
                # If anything failed (e.g. socket corruption), exit
                # nonzero so the parent's assertion below catches it.
                os._exit(1)
        else:
            # Parent: do NOT enqueue. Wait for child.
            _, status = os.waitpid(pid, 0)
            assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, (
                f"child process failed (status={status}) — likely TCP "
                "corruption from inherited httpx.Client"
            )

        # Wait for all child records to land.
        deadline = time.perf_counter() + 5.0
        while server.received < parent_received + 50 and time.perf_counter() < deadline:
            time.sleep(0.05)
        # Exactly 50 records from the child must have arrived; no socket
        # errors, no interleaved bytes that the test server would reject.
        child_received = server.received - parent_received
        assert child_received == 50, (
            f"expected 50 records from child, got {child_received} — "
            "post-fork httpx.Client was not rebuilt"
        )

        # Cleanup the parent's copy too. Note: post-fork, the parent's
        # _after_in_child handler also fired (since register_at_fork
        # triggers in BOTH children of fork()? No — only after_in_child
        # fires in the child). The parent here is unmolested.
        parent.close()


def test_multiprocessing_pool():
    """4 workers × 100 enqueues each; expect 400 records server-side."""
    if mp.get_start_method(allow_none=True) != "fork":
        # On macOS Python 3.8+, default is "spawn" — explicitly request fork.
        ctx = mp.get_context("fork")
    else:
        ctx = mp.get_context()

    with _CountingServer() as server:
        with ctx.Pool(
            processes=4,
            initializer=_pool_init,
            initargs=(server.url,),
        ) as pool:
            results = pool.map(_pool_worker, [100, 100, 100, 100])
        assert sum(results) == 400

        # Workers each called flush() then close(), so by the time
        # pool.map returns the records have been delivered (or the worker
        # process exited without delivery — but flush() with a 30s
        # timeout makes that extremely unlikely). Give a generous drain
        # window for in-kernel TCP teardown on CI runners.
        deadline = time.perf_counter() + 15.0
        while server.received < 400 and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert server.received >= 400, f"only {server.received} records"
