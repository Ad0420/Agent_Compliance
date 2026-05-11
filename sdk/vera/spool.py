"""Persistent SQLite-backed spool for Vera SDK records (workstream A5).

The spool sits between the in-memory queue and Vera's HTTP endpoint. Behavior:

* When the in-memory queue is at capacity, new records spill to the spool
  instead of being dropped.
* When the worker successfully flushes a batch, the corresponding rows are
  deleted from the spool.
* On client startup, queued records are rehydrated from the spool back into
  the memory queue (oldest first).

Security:

* SQLite file is created with mode 0600 (owner read/write only).
* Bearer tokens MUST NOT be persisted — only payload bodies. Authorization
  headers are on the httpx.Client, never in the queue payload.
* Payload bodies are encrypted at rest with AES-256-GCM. The encryption key
  is derived from a customer-supplied passphrase (``VERA_SPOOL_KEY`` env var)
  via PBKDF2-HMAC-SHA256 with 200_000 iterations.
* If no passphrase is set, the spool refuses to start. This is HIPAA-aware
  fail-closed behavior — silent on-disk plaintext PHI is the worst outcome.

Concurrency:

* WAL mode enables multiple readers + one writer per database. Multi-process
  customers (gunicorn workers, Celery pool) can share a single spool file.
* All writes go through ``sqlite3.connect(..., check_same_thread=False,
  isolation_level=None)`` with explicit BEGIN/COMMIT.
* A re-entrant lock serialises writes inside a single process so the worker
  thread and the producer threads don't trip over each other.

Why AES-GCM at the application layer instead of SQLCipher
---------------------------------------------------------
SQLCipher would give us page-level encryption "for free", but requires
``libsqlcipher`` installed system-wide on every customer host (linux distros
package it inconsistently; macOS users have to ``brew install`` it; Lambda /
container customers have to rebuild the wheel). Application-layer AES-256-GCM
matches the threat model (compliance team finds a copy of the spool file on a
backup disk, asks: is the PHI exposed?) without the ops headache.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import stat
import threading
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("vera.spool")

_SCHEMA_VERSION = 1
_PBKDF2_ITERATIONS = 200_000
_KEY_LENGTH = 32  # AES-256
_NONCE_LENGTH = 12  # AES-GCM standard
_SALT_LENGTH = 16


class SpoolError(Exception):
    """Base class for spool-related failures."""


class SpoolDiskFullError(SpoolError):
    """Raised when the underlying SQLite store cannot accept new writes
    because the disk (or the configured ``max_bytes`` cap) is exhausted.

    The client catches this and falls back to in-memory drop-oldest with
    a once-per-process WARN. The audit chain has a hole, but the customer's
    process keeps running.
    """


class SpoolDecryptionError(SpoolError):
    """Raised when a persisted payload cannot be decrypted (wrong passphrase,
    corrupted ciphertext, or tampering)."""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a passphrase using PBKDF2-HMAC-SHA256.

    Iteration count: 200_000 (OWASP 2023 recommendation for SHA-256). Salt is
    stored in ``spool_metadata`` so the same passphrase produces the same key
    across process restarts. One salt per spool file — never reuse keys across
    spools.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _is_disk_full_error(exc: sqlite3.OperationalError) -> bool:
    """Match SQLite disk-full / I/O error messages.

    SQLite surfaces "database or disk is full" for SQLITE_FULL and "disk I/O
    error" for SQLITE_IOERR. We look for either token so the heuristic
    survives across SQLite versions / locales.
    """
    msg = str(exc).lower()
    return "disk is full" in msg or "disk i/o" in msg or "database or disk" in msg


class Spool:
    """Bounded, encrypted, SQLite-backed durable spool.

    Records are stored as ``(nonce, ciphertext)`` pairs. The ciphertext is
    the AES-256-GCM encryption of ``json.dumps(record)``. Each row also
    records an enqueue timestamp (for ordering) and a re-queue counter (for
    the same poison-record protection the in-memory queue has).

    The spool is owned by one process. Multiple processes can share a single
    file (WAL mode) but each one keeps its own ``Spool`` handle. After
    ``fork()`` the child must call :meth:`reopen_after_fork` or close +
    reconstruct — the parent's ``sqlite3.Connection`` is not fork-safe.
    """

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS spool_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload_ciphertext BLOB NOT NULL,
        payload_nonce BLOB NOT NULL,
        enqueued_at REAL NOT NULL,
        requeue_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_enqueued_at ON spool_records(enqueued_at);

    CREATE TABLE IF NOT EXISTS spool_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """

    def __init__(
        self,
        path: str,
        *,
        passphrase: str,
        max_bytes: int = 100_000_000,
    ) -> None:
        if not passphrase:
            # Fail-closed. Silent plaintext PHI on disk is the worst possible
            # outcome for the customer; refusing to start is the correct
            # response when the operator hasn't supplied a key.
            raise ValueError(
                "Spool requires a non-empty passphrase. Set VERA_SPOOL_KEY "
                "or pass passphrase=... explicitly."
            )
        self._path = path
        self._max_bytes = max(1, int(max_bytes))
        self._passphrase = passphrase
        # Re-entrant so methods that call other methods (e.g. ``ack`` from a
        # caller already holding the lock for ``dequeue_batch``'s critical
        # section) don't deadlock.
        self._lock = threading.RLock()
        self._owner_pid = os.getpid()
        self._closed = False

        # Create the directory if missing, then open the SQLite connection.
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, mode=0o700, exist_ok=True)

        # Track whether the DB file is freshly created so we know whether to
        # generate a new salt (vs. read the existing one).
        file_existed = os.path.exists(path)

        self._conn = self._connect()
        try:
            self._init_schema()
            self._set_file_mode()
            self._salt = self._load_or_create_salt(generate=not file_existed)
            self._key = _derive_key(self._passphrase, self._salt)
            self._verify_passphrase()
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------
    # Connection / schema setup
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # ``isolation_level=None`` puts us in autocommit mode; we manage
        # transactions explicitly with BEGIN/COMMIT for write-batching.
        # ``check_same_thread=False`` lets the worker thread reuse the
        # connection — the RLock above serialises access.
        conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
            timeout=30.0,
        )
        # WAL mode survives across processes. ``synchronous=NORMAL`` is the
        # WAL-mode equivalent of the default "safe enough" durability —
        # FULL is the default but it's the wrong choice for WAL.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(self._SCHEMA_SQL)
            # Schema version pattern — read, compare, migrate if needed.
            row = self._conn.execute(
                "SELECT value FROM spool_metadata WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO spool_metadata (key, value) VALUES ('schema_version', ?)",
                    (str(_SCHEMA_VERSION),),
                )
            else:
                current = int(row[0])
                if current > _SCHEMA_VERSION:
                    # Future-incompatible spool. Refuse rather than corrupt.
                    raise SpoolError(
                        f"Spool schema version {current} is newer than this "
                        f"SDK supports ({_SCHEMA_VERSION}). Upgrade vera-sdk."
                    )
                # current == _SCHEMA_VERSION: no migration needed yet.
                # Future v1 -> v2 migration would dispatch here.

    def _set_file_mode(self) -> None:
        """Chmod the spool file (and WAL/SHM siblings) to 0600.

        WAL mode creates ``-wal`` and ``-shm`` side files which also contain
        the encrypted payload bytes — we set the same mode on all three.
        """
        for suffix in ("", "-wal", "-shm"):
            target = self._path + suffix
            try:
                if os.path.exists(target):
                    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            except OSError:  # pragma: no cover — defensive on weird FS
                pass

    def _load_or_create_salt(self, *, generate: bool) -> bytes:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM spool_metadata WHERE key='salt_hex'"
            ).fetchone()
            if row is not None:
                return bytes.fromhex(row[0])
            if not generate:
                # Existing DB with no salt — corruption or pre-v1 file.
                raise SpoolError(
                    "Spool file is missing salt metadata. Refusing to "
                    "initialise with a new salt over an existing payload "
                    "(this would render existing rows unreadable)."
                )
            salt = secrets.token_bytes(_SALT_LENGTH)
            self._conn.execute(
                "INSERT INTO spool_metadata (key, value) VALUES ('salt_hex', ?)",
                (salt.hex(),),
            )
            return salt

    def _verify_passphrase(self) -> None:
        """Probe: try decrypting one existing row.

        If the spool is non-empty and the passphrase is wrong, fail fast at
        init time rather than the first ``dequeue_batch`` call. Empty spool:
        we have no way to validate without a sentinel — accept the passphrase
        and trust the operator. (A future tag could be added in metadata.)
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_ciphertext, payload_nonce FROM spool_records "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return
            try:
                self._decrypt(row[0], row[1])
            except Exception as exc:
                raise SpoolDecryptionError(
                    "Spool decryption probe failed. The passphrase does not "
                    "match the one used to encrypt existing records, or the "
                    "file is corrupt."
                ) from exc

    # ------------------------------------------------------------------
    # Crypto helpers
    # ------------------------------------------------------------------

    def _encrypt(self, record: dict) -> tuple[bytes, bytes]:
        aesgcm = AESGCM(self._key)
        nonce = secrets.token_bytes(_NONCE_LENGTH)
        plaintext = json.dumps(record, default=str).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return ciphertext, nonce

    def _decrypt(self, ciphertext: bytes, nonce: bytes) -> dict:
        aesgcm = AESGCM(self._key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, record: dict) -> None:
        """Append a record to the spool.

        Raises ``SpoolDiskFullError`` when the underlying file system or
        the configured ``max_bytes`` cap is exhausted. Caller handles the
        fallback (drop-oldest in memory with a WARN).
        """
        if self._closed:
            raise SpoolError("Spool is closed")
        with self._lock:
            # Cheap byte-cap check using the page size * page count. We
            # check BEFORE attempting the write so a customer-configured
            # cap is honoured even if there's plenty of disk free.
            if self._size_bytes() >= self._max_bytes:
                raise SpoolDiskFullError(
                    f"Spool exceeds max_bytes={self._max_bytes}"
                )
            ciphertext, nonce = self._encrypt(record)
            try:
                self._conn.execute(
                    "INSERT INTO spool_records "
                    "(payload_ciphertext, payload_nonce, enqueued_at, requeue_count) "
                    "VALUES (?, ?, ?, ?)",
                    (ciphertext, nonce, time.time(), int(record.get("_requeue_count", 0))),
                )
            except sqlite3.OperationalError as exc:
                if _is_disk_full_error(exc):
                    raise SpoolDiskFullError(str(exc)) from exc
                raise

    def dequeue_batch(
        self, max_count: int = 100
    ) -> list[tuple[int, dict]]:
        """Return up to ``max_count`` records as ``(row_id, decrypted_record)``.

        Records are returned in insertion order (oldest first). The caller
        MUST call :meth:`ack` with the row_ids after a successful flush, or
        :meth:`requeue` to bump the retry counter for a failed batch. Until
        one of those happens the rows remain in the spool — there is no
        implicit "in-flight" hold.
        """
        if self._closed:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload_ciphertext, payload_nonce "
                "FROM spool_records ORDER BY id ASC LIMIT ?",
                (int(max_count),),
            ).fetchall()
            out: list[tuple[int, dict]] = []
            for row_id, ct, nonce in rows:
                try:
                    record = self._decrypt(ct, nonce)
                except Exception:
                    # Corrupt row — log and skip. Don't crash the worker.
                    logger.error(
                        "vera.spool: failed to decrypt row id=%d. Dropping. "
                        "(corruption or key rotation without migration?)",
                        row_id,
                    )
                    self._conn.execute(
                        "DELETE FROM spool_records WHERE id = ?", (row_id,)
                    )
                    continue
                out.append((row_id, record))
            return out

    def ack(self, row_ids: list[int]) -> None:
        """Delete the spool rows after a successful flush."""
        if not row_ids:
            return
        with self._lock:
            if self._closed:
                return
            placeholders = ",".join("?" * len(row_ids))
            self._conn.execute(
                f"DELETE FROM spool_records WHERE id IN ({placeholders})",
                list(row_ids),
            )

    def size(self) -> int:
        """Number of rows currently persisted."""
        if self._closed:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM spool_records"
            ).fetchone()
            return int(row[0]) if row else 0

    def _size_bytes(self) -> int:
        """Approximate size of the SQLite database in bytes.

        ``page_count * page_size`` is a fast, deterministic measure that
        matches what ``ls -l`` would show for the main DB file. WAL contents
        are checkpointed back into the main file periodically, so this is
        the best snapshot we have without stat()-ing both files.
        """
        page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
        return int(page_size) * int(page_count)

    def reopen_after_fork(self) -> None:
        """Re-open the SQLite connection in a forked child.

        The parent's ``sqlite3.Connection`` is not fork-safe — the child
        inherits the same FD but SQLite's internal state (locks, busy timers)
        is shared in undefined ways. The correct behaviour after ``fork()``
        is to drop the inherited handle (don't ``close()`` it — that would
        munge the parent's state) and open a fresh one.
        """
        with self._lock:
            self._conn = self._connect()
            self._owner_pid = os.getpid()
            self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._conn.close()
            except Exception:  # pragma: no cover — defensive
                pass


__all__ = [
    "Spool",
    "SpoolError",
    "SpoolDiskFullError",
    "SpoolDecryptionError",
]
