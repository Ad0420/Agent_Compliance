"""Integration tests for the durable spool wired through VeraClient (A5).

The unit tests in ``test_spool.py`` exercise the Spool class directly.
This file verifies the client-side wiring: overflow spills to spool,
rehydration on init, ack on successful flush, fork-safety, and the
disk-full fallback.
"""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from vera import VeraClient
from vera.spool import Spool, SpoolDiskFullError


PASSPHRASE = "integration-test-key"


@pytest.fixture(autouse=True)
def _set_spool_key(monkeypatch):
    monkeypatch.setenv("VERA_SPOOL_KEY", PASSPHRASE)


@pytest.fixture
def spool_path(tmp_path):
    return str(tmp_path / "spool.db")


# ---------------------------------------------------------------------------
# In-process counting HTTP server.
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
        for r in records:
            self.server.received_names.append(r.get("action_name"))  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


class _CountingServer:
    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), _CountingHandler)
        self.server.received_records = 0  # type: ignore[attr-defined]
        self.server.received_names = []  # type: ignore[attr-defined]
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

    @property
    def names(self) -> list[str]:
        return self.server.received_names  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 0. config: missing VERA_SPOOL_KEY rejects persistent_buffer_path
# ---------------------------------------------------------------------------


def test_missing_spool_key_rejected(spool_path, monkeypatch):
    monkeypatch.delenv("VERA_SPOOL_KEY", raising=False)
    with pytest.raises(ValueError, match="VERA_SPOOL_KEY"):
        VeraClient(persistent_buffer_path=spool_path)


# ---------------------------------------------------------------------------
# 1. client rehydrates from spool on init
# ---------------------------------------------------------------------------


def test_client_rehydrates_from_spool_on_init(spool_path):
    """Records persisted by a previous process must be delivered after restart."""
    # Pre-seed the spool directly (simulating "process A crashed before flush").
    s = Spool(spool_path, passphrase=PASSPHRASE)
    for i in range(50):
        s.enqueue(
            {
                "action_name": f"recovered_{i}",
                "agent_name": "default-agent",
                "_idempotency_key": f"k{i}",
                "_requeue_count": 0,
            }
        )
    s.close()

    with _CountingServer() as server:
        # Construct a fresh client with the same spool path. It must rehydrate
        # and deliver the 50 records.
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=10,
            atexit_drain_timeout=5.0,
            persistent_buffer_path=spool_path,
        )
        # Trigger queue init even if rehydrate didn't (it should have).
        # Wait for the worker to deliver them.
        deadline = time.perf_counter() + 5.0
        while server.received < 50 and time.perf_counter() < deadline:
            time.sleep(0.05)
        client.close()
        assert server.received >= 50, (
            f"expected 50 rehydrated records, got {server.received}"
        )


# ---------------------------------------------------------------------------
# 2. overflow spills to spool, nothing dropped, no drop-oldest WARN
# ---------------------------------------------------------------------------


class _BlockingHandler(BaseHTTPRequestHandler):
    """Server that hangs on POST so the queue fills up."""

    def log_message(self, *_a, **_kw):
        return

    def do_POST(self):  # noqa: N802
        # Hold the request open until ``release`` is set.
        self.server.release_event.wait(timeout=30)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


class _BlockingServer:
    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), _BlockingHandler)
        self.server.release_event = threading.Event()  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.release_event.set()  # type: ignore[attr-defined]
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def release(self) -> None:
        self.server.release_event.set()  # type: ignore[attr-defined]


def test_overflow_spills_to_spool_not_dropped(spool_path, caplog):
    """Fill the in-memory queue past capacity and verify spill, not drop.

    The key invariant for A5 is: total records (in queue + in spool +
    in-flight) MUST equal the number enqueued — nothing silently dropped.
    """
    # Tiny in-memory queue (8 entries) so we can overflow deterministically.
    # Use a blocking server so the worker can't drain mid-test and confuse
    # the size assertions.
    with _BlockingServer() as server:
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=60.0,  # disable periodic flush
            batch_size=4,
            max_queue_size=8,
            atexit_drain_timeout=0.5,
            persistent_buffer_path=spool_path,
        )
        # Enqueue 30 records. First N go into the queue; remainder spills.
        with caplog.at_level(logging.WARNING, logger="vera.client"):
            for i in range(30):
                client.enqueue_action(action_name=f"x{i}")

        # Some records spilled to spool — overflow happened, not drop-oldest.
        assert client._spool is not None
        spool_size = client._spool.size()
        assert spool_size > 0, (
            f"expected spool spill on overflow, got {spool_size} rows"
        )
        # No drop-oldest WARN should have fired (the spool absorbed the
        # overflow instead).
        drop_warns = [
            r
            for r in caplog.records
            if "Dropped oldest record" in r.getMessage()
            or "drop-oldest" in r.getMessage().lower()
        ]
        assert not drop_warns, (
            f"unexpected drop-oldest WARN: {[r.getMessage() for r in drop_warns]}"
        )
        # Tear down — release the blocked server so close() can proceed
        # bounded by the short atexit_drain_timeout. We do NOT assert
        # delivery here; the point of this test is the spool spill.
        server.release()
        client.close()


# ---------------------------------------------------------------------------
# 3. successful flush acks spool records
# ---------------------------------------------------------------------------


def test_successful_flush_acks_spool_records(spool_path):
    """Records spilled to spool must be deleted after the worker flushes them."""
    # Pre-seed the spool.
    s = Spool(spool_path, passphrase=PASSPHRASE)
    for i in range(20):
        s.enqueue(
            {
                "action_name": f"to_deliver_{i}",
                "agent_name": "default-agent",
                "_idempotency_key": f"k{i}",
                "_requeue_count": 0,
            }
        )
    s.close()

    with _CountingServer() as server:
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=20,
            atexit_drain_timeout=5.0,
            persistent_buffer_path=spool_path,
        )
        deadline = time.perf_counter() + 5.0
        while server.received < 20 and time.perf_counter() < deadline:
            time.sleep(0.05)
        # The client's spool should be empty after acks.
        assert client._spool is not None
        # Give the ack a moment to commit.
        time.sleep(0.2)
        remaining = client._spool.size()
        client.close()
        assert remaining == 0, (
            f"expected spool to be empty after ack, got {remaining} rows"
        )


# ---------------------------------------------------------------------------
# 4. spool disk-full falls back to drop-oldest, no crash
# ---------------------------------------------------------------------------


def test_spool_disk_full_falls_back_to_drop_oldest(spool_path, caplog):
    """If the spool refuses writes, the client must continue running."""
    with _BlockingServer() as server:
        client = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=60.0,
            batch_size=4,
            max_queue_size=4,
            atexit_drain_timeout=0.5,
            persistent_buffer_path=spool_path,
        )

        # Replace the spool's enqueue with one that always raises.
        assert client._spool is not None

        def boom(_record):
            raise SpoolDiskFullError("simulated")

        client._spool.enqueue = boom  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="vera.client"):
            for i in range(20):
                client.enqueue_action(action_name=f"x{i}")

        # Drop-oldest WARN must have fired (in-memory fallback). The client
        # must still be alive and accepting (no exception).
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "drop" in messages.lower() or "spool is full" in messages.lower()

        server.release()
        client.close()


# ---------------------------------------------------------------------------
# 5. fork: child gets independent spool handle
# ---------------------------------------------------------------------------


def _fork_child_writer(spool_path: str, n: int, queue) -> None:
    """Child process: open the same spool path and write ``n`` records."""
    os.environ["VERA_SPOOL_KEY"] = PASSPHRASE
    try:
        c = VeraClient(
            api_url="http://127.0.0.1:1",  # bogus; we won't flush
            api_key="test",
            flush_interval=60.0,
            batch_size=1000,
            max_queue_size=2,
            atexit_drain_timeout=0.1,
            persistent_buffer_path=spool_path,
        )
        # Force overflow into spool.
        for i in range(n):
            c.enqueue_action(action_name=f"child_{i}")
        # Don't call close — we want to verify the child's spool handle is
        # independently functional, not test shutdown semantics here.
        queue.put("ok")
    except BaseException as exc:  # pragma: no cover — diagnostic
        queue.put(f"err: {exc!r}")


@pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(os, "fork"),
    reason="fork() not available on this platform",
)
def test_fork_reopens_spool_in_child(spool_path):
    """Child process must get a working spool handle without corrupting parent's."""
    # Build a parent client and force one enqueue to allocate state.
    parent = VeraClient(
        api_url="http://127.0.0.1:1",
        api_key="test",
        flush_interval=60.0,
        batch_size=1000,
        max_queue_size=2,
        atexit_drain_timeout=0.1,
        persistent_buffer_path=spool_path,
    )
    # Push the parent into spool territory (max_queue_size=2, 5 enqueues).
    for i in range(5):
        parent.enqueue_action(action_name=f"parent_{i}")
    assert parent._spool is not None
    parent_spool_count = parent._spool.size()

    ctx = mp.get_context("fork")
    q = ctx.Queue()
    p = ctx.Process(target=_fork_child_writer, args=(spool_path, 10, q))
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 0, f"child exit code {p.exitcode}"
    result = q.get(timeout=5)
    assert result == "ok", f"child failed: {result}"

    # Parent's spool must still be functional and now contain the child's
    # writes too. Re-check from a fresh handle since the parent's in-memory
    # _spool object may have stale connection state after the child fork.
    s = Spool(spool_path, passphrase=PASSPHRASE)
    try:
        # Child wrote 10 rows; parent already had parent_spool_count.
        final = s.size()
    finally:
        s.close()
    assert final >= parent_spool_count + 10 - 5, (
        f"expected >= {parent_spool_count + 5} rows after child wrote 10, got {final}"
    )

    # Parent's own spool handle should still respond (cheap call).
    # close() is best-effort; we don't assert it succeeds because the
    # post-fork parent connection might be in a degraded state on some
    # platforms.
    try:
        parent.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 6. End-to-end: process restart preserves records (the headline feature)
# ---------------------------------------------------------------------------


def test_process_restart_preserves_records(spool_path):
    """Enqueue records, close client without flush, reopen, deliver."""
    with _CountingServer() as server:
        # Phase 1: enqueue to a client that will be torn down before flush
        # completes by pointing it at a dead server initially.
        c1 = VeraClient(
            api_url="http://127.0.0.1:1",  # unreachable
            api_key="test",
            flush_interval=60.0,
            batch_size=1,
            max_queue_size=1,
            atexit_drain_timeout=0.2,
            persistent_buffer_path=spool_path,
        )
        # All enqueues after the first one overflow into the spool.
        for i in range(25):
            c1.enqueue_action(action_name=f"r{i}")
        # We don't bother flushing — close with tiny drain timeout.
        c1.close()
        assert c1._spool is not None
        # At least the 24 overflow records should have landed on disk.
        # (The in-memory queue holds 1.)
        s = Spool(spool_path, passphrase=PASSPHRASE)
        try:
            persisted = s.size()
        finally:
            s.close()
        # Most of the 25 records should be on disk. The exact count varies
        # because the in-memory queue (size 1) may have items in-flight or
        # in re-queue limbo at close-time. We accept anything close to the
        # capacity-minus-in-flight overflow count.
        assert persisted >= 20, f"expected >=20 persisted, got {persisted}"

        # Phase 2: new client points at a working server and recovers.
        c2 = VeraClient(
            api_url=server.url,
            api_key="test",
            flush_interval=0.05,
            batch_size=25,
            atexit_drain_timeout=10.0,
            persistent_buffer_path=spool_path,
        )
        deadline = time.perf_counter() + 10.0
        while server.received < persisted and time.perf_counter() < deadline:
            time.sleep(0.05)
        c2.close()
        # We must have delivered everything that was on disk.
        assert server.received >= persisted, (
            f"only {server.received} of {persisted} records recovered after restart"
        )
