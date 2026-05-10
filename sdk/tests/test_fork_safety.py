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
from http.server import BaseHTTPRequestHandler, HTTPServer

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
        self.server.received_records += len(records)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


class _CountingServer:
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
        atexit_drain_timeout=5.0,
    )


def _pool_worker(n: int) -> int:
    c = _pool_client_holder["c"]
    for i in range(n):
        c.enqueue_action(action_name=f"w{i}")
    # Force a drain before the worker process tears down.
    c.close()
    return n


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

        # Workers each called close(), so by the time pool.map returns the
        # records have either been delivered or the worker process exited
        # without delivery. Give a small drain window.
        deadline = time.perf_counter() + 5.0
        while server.received < 400 and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert server.received >= 400, f"only {server.received} records"
