"""Unit tests for :mod:`vera.spool` (workstream A5).

These exercise the Spool class directly. Integration tests that drive the
spool through a VeraClient live in ``test_durable_recovery.py``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import stat
import sys

import pytest

from vera.spool import (
    Spool,
    SpoolDecryptionError,
    SpoolDiskFullError,
    SpoolError,
)


PASSPHRASE = "test-passphrase-do-not-use-in-prod"


@pytest.fixture
def spool_path(tmp_path):
    return str(tmp_path / "spool.db")


# ---------------------------------------------------------------------------
# 1. roundtrip
# ---------------------------------------------------------------------------


def test_enqueue_dequeue_roundtrip(spool_path):
    s = Spool(spool_path, passphrase=PASSPHRASE)
    record = {"action_name": "foo", "input_data": {"x": 1, "y": "hello"}}
    s.enqueue(record)
    assert s.size() == 1

    batch = s.dequeue_batch(max_count=10)
    assert len(batch) == 1
    row_id, decoded = batch[0]
    assert decoded == record
    # Before ack, the row is still there (dequeue is non-destructive).
    assert s.size() == 1

    s.ack([row_id])
    assert s.size() == 0
    s.close()


# ---------------------------------------------------------------------------
# 2. encryption at rest
# ---------------------------------------------------------------------------


def test_encryption_at_rest(spool_path):
    """The plaintext of a record must NOT appear in the SQLite file."""
    s = Spool(spool_path, passphrase=PASSPHRASE)
    # Unique sentinel so we can grep for it deterministically.
    sentinel = "MEDICAL_RECORD_NUMBER_XYZZY_4242"
    record = {"action_name": "phi_carrier", "input_data": {"mrn": sentinel}}
    s.enqueue(record)
    s.close()

    # Re-open the SQLite file with the raw driver (no Spool wrapper) and
    # scan every byte of every stored payload for the sentinel.
    raw = sqlite3.connect(spool_path)
    try:
        rows = raw.execute(
            "SELECT payload_ciphertext, payload_nonce FROM spool_records"
        ).fetchall()
    finally:
        raw.close()
    assert rows, "no rows persisted"
    sentinel_bytes = sentinel.encode("utf-8")
    for ct, nonce in rows:
        # Defense-in-depth: assert neither blob contains the marker. This
        # is the load-bearing security check.
        assert sentinel_bytes not in ct, (
            "plaintext leaked into payload_ciphertext column"
        )
        assert sentinel_bytes not in nonce, (
            "plaintext leaked into payload_nonce column"
        )
    # Also scan the entire DB file at the OS level — covers any incidental
    # caching SQLite did inside the page.
    with open(spool_path, "rb") as fh:
        contents = fh.read()
    assert sentinel_bytes not in contents, (
        "plaintext leaked into the SQLite file on disk"
    )


# ---------------------------------------------------------------------------
# 3. file mode 0600
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_file_mode_0600(spool_path):
    s = Spool(spool_path, passphrase=PASSPHRASE)
    s.enqueue({"action_name": "trigger_wal"})
    mode = stat.S_IMODE(os.stat(spool_path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    # WAL side-files exist after a write; they MUST also be 0600.
    for suffix in ("-wal", "-shm"):
        target = spool_path + suffix
        if os.path.exists(target):
            sub_mode = stat.S_IMODE(os.stat(target).st_mode)
            assert sub_mode == 0o600, (
                f"{target} expected 0600, got {oct(sub_mode)}"
            )
    s.close()


# ---------------------------------------------------------------------------
# 4. wrong passphrase fails
# ---------------------------------------------------------------------------


def test_wrong_passphrase_fails(spool_path):
    a = Spool(spool_path, passphrase="passphrase-A")
    a.enqueue({"action_name": "hello"})
    a.close()

    with pytest.raises(SpoolDecryptionError):
        Spool(spool_path, passphrase="passphrase-B")


# ---------------------------------------------------------------------------
# 5. disk-full raises SpoolDiskFullError
# ---------------------------------------------------------------------------


def test_disk_full_raises(spool_path):
    s = Spool(spool_path, passphrase=PASSPHRASE)

    class _FakeConn:
        """Wraps the real connection but raises on INSERT statements."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kw):
            if sql.startswith("INSERT INTO spool_records"):
                raise sqlite3.OperationalError("database or disk is full")
            return self._real.execute(sql, *args, **kw)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_conn = s._conn
    s._conn = _FakeConn(real_conn)
    try:
        with pytest.raises(SpoolDiskFullError):
            s.enqueue({"action_name": "boom"})
    finally:
        s._conn = real_conn
    s.close()


def test_disk_full_non_full_error_propagates(spool_path):
    """A non-disk-full sqlite3.OperationalError should NOT map to SpoolDiskFullError."""
    s = Spool(spool_path, passphrase=PASSPHRASE)

    class _FakeConn:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kw):
            if sql.startswith("INSERT INTO spool_records"):
                raise sqlite3.OperationalError("syntax error in SQL")
            return self._real.execute(sql, *args, **kw)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_conn = s._conn
    s._conn = _FakeConn(real_conn)
    try:
        with pytest.raises(sqlite3.OperationalError):
            s.enqueue({"action_name": "boom"})
    finally:
        s._conn = real_conn
    s.close()


# ---------------------------------------------------------------------------
# 6. multi-process writers (WAL mode)
# ---------------------------------------------------------------------------


def _writer(path: str, passphrase: str, n: int) -> int:
    """Subprocess entry-point. Writes ``n`` records to the shared spool."""
    s = Spool(path, passphrase=passphrase)
    try:
        for i in range(n):
            s.enqueue({"action_name": f"p{os.getpid()}_r{i}"})
    finally:
        s.close()
    return n


@pytest.mark.skipif(sys.platform == "win32", reason="fork-based mp")
def test_multi_process_writers(spool_path):
    # Bootstrap the file + salt with one connection so the writers all see
    # the same encryption key. Without this, each process would race to
    # initialise its own salt and the second one in would crash.
    bootstrap = Spool(spool_path, passphrase=PASSPHRASE)
    bootstrap.close()

    ctx = mp.get_context("fork")
    procs = [
        ctx.Process(target=_writer, args=(spool_path, PASSPHRASE, 10))
        for _ in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"writer crashed: exitcode={p.exitcode}"

    s = Spool(spool_path, passphrase=PASSPHRASE)
    try:
        assert s.size() == 40, f"expected 40 rows, got {s.size()}"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 7. schema v1 init
# ---------------------------------------------------------------------------


def test_schema_v1_init(spool_path):
    Spool(spool_path, passphrase=PASSPHRASE).close()
    raw = sqlite3.connect(spool_path)
    try:
        row = raw.execute(
            "SELECT value FROM spool_metadata WHERE key='schema_version'"
        ).fetchone()
    finally:
        raw.close()
    assert row is not None
    assert row[0] == "1"


# ---------------------------------------------------------------------------
# 8. rehydration order preserved across close + reopen
# ---------------------------------------------------------------------------


def test_rehydration_order(spool_path):
    s = Spool(spool_path, passphrase=PASSPHRASE)
    expected = []
    for i in range(5):
        rec = {"action_name": f"r{i}", "ix": i}
        s.enqueue(rec)
        expected.append(rec)
    s.close()

    s2 = Spool(spool_path, passphrase=PASSPHRASE)
    try:
        batch = s2.dequeue_batch(max_count=100)
    finally:
        s2.close()
    got = [r for _, r in batch]
    assert got == expected, "spool rehydrate must preserve insertion order"


# ---------------------------------------------------------------------------
# 9. max_bytes cap
# ---------------------------------------------------------------------------


def test_max_bytes_cap(spool_path):
    # Set the cap very low. The schema + metadata already take a few KB so
    # any non-trivial write should exceed it.
    s = Spool(spool_path, passphrase=PASSPHRASE, max_bytes=4096)
    # Write a few small rows; the cap is enforced by ``_size_bytes()``,
    # which checks page_count*page_size and is conservative. Add until the
    # cap is exceeded.
    raised = False
    for i in range(2_000):
        try:
            s.enqueue({"action_name": f"r{i}", "data": "x" * 64})
        except SpoolDiskFullError:
            raised = True
            break
    assert raised, "max_bytes cap should refuse new writes"
    s.close()


# ---------------------------------------------------------------------------
# 10. passphrase is required
# ---------------------------------------------------------------------------


def test_empty_passphrase_refused(spool_path):
    with pytest.raises(ValueError):
        Spool(spool_path, passphrase="")


# ---------------------------------------------------------------------------
# 11. ack semantics — empty list is a no-op, partial ack works
# ---------------------------------------------------------------------------


def test_ack_partial(spool_path):
    s = Spool(spool_path, passphrase=PASSPHRASE)
    for i in range(5):
        s.enqueue({"action_name": f"r{i}"})
    batch = s.dequeue_batch(max_count=10)
    assert len(batch) == 5
    # Ack only the first 3.
    s.ack([row_id for row_id, _ in batch[:3]])
    assert s.size() == 2
    s.close()
