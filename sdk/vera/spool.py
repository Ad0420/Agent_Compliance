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

# NOTE: ``cryptography`` is an optional extra (vera-sdk[spool]). We import it
# lazily — only when ``Spool`` is actually instantiated or its crypto helpers
# are invoked — so that ``import vera`` (and therefore every downstream import
# of ``vera.client``) stays available to customers who never opt into the
# durable spool. Eager top-level import would force every Vera SDK user to
# install ``cryptography``, breaking lightweight environments (Lambda layers,
# CI images for the simulator, etc.) that don't need the spool.

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
    corrupted ciphertext, or tampering).

    When raised from :meth:`Spool.dequeue_batch`, the affected rows have been
    moved to the ``spool_quarantine_records`` table (NOT deleted). The audit
    chain is preserved; operator intervention is required to either recover
    the original key or accept the loss explicitly.

    The exception's ``quarantined_ids`` attribute lists the row ids that were
    moved during the current dequeue call.
    """

    def __init__(self, message: str, *, quarantined_ids: list[int] | None = None):
        super().__init__(message)
        self.quarantined_ids = list(quarantined_ids or [])


class SpoolPassphraseError(SpoolDecryptionError):
    """Raised when an existing spool's passphrase sentinel doesn't validate.

    Subclass of :class:`SpoolDecryptionError` so callers can either match
    the specific case (operator typo at startup) or the general one
    (decryption failure in any path). Tests written against the older
    "everything is SpoolDecryptionError" surface remain green.
    """

    def __init__(self, message: str):
        # Skip the parent's ``quarantined_ids`` machinery — passphrase
        # mismatch happens at init time when nothing has been dequeued.
        super().__init__(message, quarantined_ids=[])


def _require_cryptography() -> None:
    """Verify the optional ``cryptography`` dependency is installed.

    Raises ``ImportError`` with a hint that points at the ``[spool]`` extra
    so the customer gets a one-line fix instead of an opaque traceback.
    """
    try:
        import cryptography  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "vera-sdk[spool] required for durable spool. "
            "Install with: pip install 'vera-sdk[spool]'"
        ) from exc


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from a passphrase using PBKDF2-HMAC-SHA256.

    Iteration count: 200_000 (OWASP 2023 recommendation for SHA-256). Salt is
    stored in ``spool_metadata`` so the same passphrase produces the same key
    across process restarts. One salt per spool file — never reuse keys across
    spools.
    """
    # Lazy import so ``import vera.spool`` doesn't require ``cryptography``
    # when the customer hasn't installed the [spool] extra.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _is_disk_full_error(exc: sqlite3.OperationalError) -> bool:
    """Match SQLite disk-full / I/O errors.

    Prefers the numeric ``sqlite_errorcode`` attribute (Python 3.11+) which is
    locale-independent. Falls back to substring matching of the error message
    on Python 3.10 where the attribute is unavailable.
    """
    # Python 3.11+ exposes the SQLite extended error code directly. This is
    # the load-bearing locale-safe check.
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        try:
            # SQLITE_FULL = 13, SQLITE_IOERR = 10. Use the named constants if
            # available (Python 3.11+); fall back to literals if the module
            # constants aren't exposed yet on the running interpreter.
            full = getattr(sqlite3, "SQLITE_FULL", 13)
            ioerr = getattr(sqlite3, "SQLITE_IOERR", 10)
            # The extended error code's primary code lives in the low byte.
            primary = code & 0xFF
            if primary == full or primary == ioerr:
                return True
            # Don't return False yet — fall through to message check so the
            # 3.10 codepath behaves consistently. The 3.11+ probe is an
            # extra signal, not a substitute.
        except (AttributeError, TypeError):  # pragma: no cover — defensive
            pass
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

    -- Quarantine table: rows whose ciphertext refused to decrypt. Moved here
    -- (not deleted) so the operator can recover them after the underlying
    -- key issue is fixed. Same column shape as spool_records so a recovery
    -- procedure can INSERT ... SELECT them back once the right key is known.
    CREATE TABLE IF NOT EXISTS spool_quarantine_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_id INTEGER NOT NULL,
        payload_ciphertext BLOB NOT NULL,
        payload_nonce BLOB NOT NULL,
        enqueued_at REAL NOT NULL,
        requeue_count INTEGER NOT NULL DEFAULT 0,
        failure_reason TEXT NOT NULL,
        quarantined_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_quarantined_at
        ON spool_quarantine_records(quarantined_at);
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
        # Fail with a friendly error if ``cryptography`` isn't installed.
        # Doing this in ``__init__`` (rather than at module top) lets the
        # SDK be importable in environments that never use the spool.
        _require_cryptography()
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

        # Lock down file mode at creation time. ``sqlite3.connect`` creates
        # the file using the process umask (typically 0o022 → 0o644, world-
        # readable). Between connect and our explicit ``chmod 0600`` there's
        # a window where PHI ciphertext is readable by any local user. Set
        # the umask to 0o077 BEFORE connect so the file is created at 0o600
        # in the first place. We restore the umask immediately afterwards so
        # subsequent file creation in the same process isn't affected.
        old_umask = os.umask(0o077)
        try:
            self._conn = self._connect()
            try:
                self._init_schema()
                # Belt-and-suspenders: chmod the file too. Covers any sidecar
                # (-wal/-shm/-journal) that WAL mode created after connect,
                # and protects against the (rare) case where the umask trick
                # was defeated by a filesystem with ACL inheritance.
                self._set_file_mode()
                self._salt = self._load_or_create_salt(generate=not file_existed)
                self._key = _derive_key(self._passphrase, self._salt)
                self._init_passphrase_sentinel(file_existed=file_existed)
                # Note: an earlier "probe decryption of the first stored row"
                # check was removed because it conflated two failure modes:
                # wrong passphrase (now caught by the sentinel) and
                # individually-corrupt rows (now quarantined on dequeue).
                # Refusing to open the entire spool because one specific row
                # was corrupted destroyed the audit chain — the whole point
                # of A5 was to preserve evidence.
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                raise
        finally:
            os.umask(old_umask)

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
        """Chmod the spool file (and WAL/SHM/journal siblings) to 0600.

        WAL mode creates ``-wal`` and ``-shm`` side files which also contain
        the encrypted payload bytes — we set the same mode on all three.
        ``-journal`` is the rollback-mode counterpart; we cover it too in
        case ``PRAGMA journal_mode=WAL`` fails on a particular filesystem
        and SQLite silently downgrades to rollback journals.
        """
        # ``stat.S_IRUSR | stat.S_IWUSR`` is 0o600. Owner read/write only.
        target_mode = stat.S_IRUSR | stat.S_IWUSR
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = self._path + suffix
            try:
                if os.path.exists(target):
                    os.chmod(target, target_mode)
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

    # Sentinel plaintext written to spool_metadata at init time. Encrypted
    # with the operator-supplied passphrase so a future open can verify the
    # passphrase matches even when the row table is empty. Tagged with a
    # version so future cipher rotations can negotiate compatibility.
    _SENTINEL_PLAINTEXT = b"vera-spool-sentinel-v1"

    def _init_passphrase_sentinel(self, *, file_existed: bool) -> None:
        """Write or verify the encrypted-passphrase-sentinel.

        On first init (empty spool): write an encrypted sentinel into
        ``spool_metadata`` so future opens can verify the passphrase even
        before any records exist. Previously an empty spool accepted any
        passphrase silently — operator typos at first init became permanent
        and invisible until the first dequeue.

        On subsequent open: decrypt the stored sentinel. If decryption fails
        we raise :class:`SpoolPassphraseError` so the operator sees the typo
        BEFORE we accept new records (which would otherwise be unrecoverable
        when they're dequeued against the wrong key).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM spool_metadata WHERE key='passphrase_sentinel'"
            ).fetchone()
            if row is None:
                # Fresh spool (or pre-sentinel spool from a previous SDK
                # version) — write a fresh sentinel. We do this whenever
                # the sentinel row is missing, regardless of ``file_existed``,
                # so customers upgrading an older spool also get the
                # passphrase-validation guarantee on next open.
                ciphertext, nonce = self._encrypt_bytes(self._SENTINEL_PLAINTEXT)
                # Store as hex(nonce) + ":" + hex(ciphertext) for inspection
                # by tools that read the metadata table directly.
                self._conn.execute(
                    "INSERT INTO spool_metadata (key, value) VALUES "
                    "('passphrase_sentinel', ?)",
                    (f"{nonce.hex()}:{ciphertext.hex()}",),
                )
                return
            try:
                nonce_hex, ct_hex = str(row[0]).split(":", 1)
                nonce = bytes.fromhex(nonce_hex)
                ciphertext = bytes.fromhex(ct_hex)
                plaintext = self._decrypt_bytes(ciphertext, nonce)
            except Exception as exc:
                raise SpoolPassphraseError(
                    "Passphrase does not match existing spool sentinel. "
                    "Check VERA_SPOOL_KEY — the key supplied does not match "
                    "the one used to initialise this spool. Refusing to "
                    "proceed; existing records would be unrecoverable under "
                    "the wrong key."
                ) from exc
            if plaintext != self._SENTINEL_PLAINTEXT:
                # Decrypted to something other than our sentinel — corruption
                # or a downgrade attack. Fail closed.
                raise SpoolPassphraseError(
                    "Passphrase sentinel decrypted to unexpected plaintext "
                    "(spool may be corrupt or tampered with)."
                )

    # ------------------------------------------------------------------
    # Crypto helpers
    # ------------------------------------------------------------------

    def _encrypt_bytes(self, plaintext: bytes) -> tuple[bytes, bytes]:
        """AES-GCM encrypt a byte string; return (ciphertext, nonce)."""
        # Lazy import — see module docstring note about the [spool] extra.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)
        nonce = secrets.token_bytes(_NONCE_LENGTH)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return ciphertext, nonce

    def _decrypt_bytes(self, ciphertext: bytes, nonce: bytes) -> bytes:
        """AES-GCM decrypt a byte string; raises on auth failure."""
        # Lazy import — see module docstring note about the [spool] extra.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, associated_data=None)

    def _encrypt(self, record: dict) -> tuple[bytes, bytes]:
        plaintext = json.dumps(record, default=str).encode("utf-8")
        return self._encrypt_bytes(plaintext)

    def _decrypt(self, ciphertext: bytes, nonce: bytes) -> dict:
        plaintext = self._decrypt_bytes(ciphertext, nonce)
        return json.loads(plaintext.decode("utf-8"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, record: dict) -> None:
        """Append a record to the spool.

        Raises ``SpoolDiskFullError`` when the underlying file system or
        the configured ``max_bytes`` cap is exhausted. Caller handles the
        fallback (drop-oldest in memory with a WARN).

        Concurrency: this method wraps the size-check + insert in a single
        ``BEGIN IMMEDIATE`` transaction. ``BEGIN IMMEDIATE`` acquires a
        RESERVED lock that excludes other writers on the same database
        across both threads and processes. Within one process the RLock
        above already serialises us; across processes (gunicorn workers
        sharing one spool file) the SQLite WAL lock arbitrates. The cap is
        therefore "strict within one process, best-effort within ±1 batch
        across processes" — cross-process accounting can race on the final
        commit because the size probe inside the transaction sees a
        snapshot that may be slightly stale.
        """
        if self._closed:
            raise SpoolError("Spool is closed")
        with self._lock:
            ciphertext, nonce = self._encrypt(record)
            try:
                self._conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # Could be SQLITE_BUSY (another writer holds the reserved
                # lock and our 30s timeout elapsed). Surface as a transient
                # failure — caller will drop-oldest in memory and try again
                # on the next enqueue.
                if _is_disk_full_error(exc):
                    raise SpoolDiskFullError(str(exc)) from exc
                raise
            try:
                # Cheap byte-cap check using page count + WAL file size. We
                # check INSIDE the IMMEDIATE transaction so a customer-
                # configured cap is honoured even when multiple producer
                # threads race the check+insert (the lock excludes their
                # write but not their read).
                if self._size_bytes() >= self._max_bytes:
                    raise SpoolDiskFullError(
                        f"Spool exceeds max_bytes={self._max_bytes}"
                    )
                try:
                    self._conn.execute(
                        "INSERT INTO spool_records "
                        "(payload_ciphertext, payload_nonce, enqueued_at, requeue_count) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            ciphertext,
                            nonce,
                            time.time(),
                            int(record.get("_requeue_count", 0)),
                        ),
                    )
                except sqlite3.OperationalError as exc:
                    if _is_disk_full_error(exc):
                        raise SpoolDiskFullError(str(exc)) from exc
                    raise
                self._conn.execute("COMMIT")
            except BaseException:
                # Rollback on any error so we release the RESERVED lock
                # promptly. ``ROLLBACK`` after a failed COMMIT is a no-op
                # on SQLite — safe to call defensively.
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.OperationalError:  # pragma: no cover
                    pass
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

        Behavior change vs. earlier releases
        ------------------------------------
        Rows that fail to decrypt are now MOVED into
        ``spool_quarantine_records`` (not deleted) and a
        :class:`SpoolDecryptionError` is raised after collecting the batch.
        Previously the rows were silently DELETED with a single ERROR log,
        which destroyed the audit chain on key rotation. The whole point of
        the spool is to preserve evidence — silent destruction is the exact
        failure mode it should prevent.

        Operators see :class:`SpoolDecryptionError` rather than a quietly-
        empty queue; the client logs a once-per-process loud ERROR pointing
        at the recovery procedure (see ``sdk/docs/spool-key-rotation.md``).
        """
        if self._closed:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload_ciphertext, payload_nonce, enqueued_at, "
                "requeue_count FROM spool_records ORDER BY id ASC LIMIT ?",
                (int(max_count),),
            ).fetchall()
            out: list[tuple[int, dict]] = []
            quarantined: list[int] = []
            for row_id, ct, nonce, enqueued_at, requeue_count in rows:
                try:
                    record = self._decrypt(ct, nonce)
                except Exception:
                    # Move the row to quarantine in one transaction so we
                    # never have a window where the row is in NEITHER table.
                    # An audit-chain hole is the failure mode this whole
                    # subsystem exists to prevent.
                    try:
                        self._conn.execute("BEGIN IMMEDIATE")
                        try:
                            self._conn.execute(
                                "INSERT INTO spool_quarantine_records "
                                "(original_id, payload_ciphertext, payload_nonce, "
                                "enqueued_at, requeue_count, failure_reason, "
                                "quarantined_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (
                                    row_id,
                                    ct,
                                    nonce,
                                    enqueued_at,
                                    requeue_count,
                                    "decrypt_failed",
                                    time.time(),
                                ),
                            )
                            self._conn.execute(
                                "DELETE FROM spool_records WHERE id = ?",
                                (row_id,),
                            )
                            self._conn.execute("COMMIT")
                        except BaseException:
                            try:
                                self._conn.execute("ROLLBACK")
                            except sqlite3.OperationalError:  # pragma: no cover
                                pass
                            raise
                    except Exception as move_exc:  # pragma: no cover — defensive
                        logger.error(
                            "vera.spool: failed to quarantine row id=%d: %s. "
                            "Row remains in spool_records and will be retried.",
                            row_id,
                            move_exc,
                        )
                        # Skip this row but don't delete or include it.
                        continue
                    quarantined.append(row_id)
                    logger.error(
                        "vera.spool: row id=%d failed to decrypt — moved to "
                        "quarantine (reason=decrypt_failed). Possible key "
                        "rotation without migration. Run a recovery procedure "
                        "with the previous key before purging quarantine.",
                        row_id,
                    )
                    continue
                out.append((row_id, record))
            if quarantined:
                raise SpoolDecryptionError(
                    f"{len(quarantined)} row(s) failed to decrypt and were "
                    f"moved to quarantine. See sdk/docs/spool-key-rotation.md "
                    f"for recovery instructions.",
                    quarantined_ids=quarantined,
                )
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

        Counts the main DB file (``page_count * page_size``) PLUS the WAL
        sidecar file. Earlier versions counted only the main file, which let
        the customer's ``max_bytes`` cap silently leak gigabytes worth of
        un-checkpointed WAL writes during a flushing stall. The cap is
        meant to protect operators from runaway disk usage; ignoring the
        WAL defeats that.

        ``stat`` on the WAL file is wrapped in try/except — the sidecar
        may not exist yet on a freshly-created spool.
        """
        page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
        main = int(page_size) * int(page_count)
        wal = 0
        try:
            wal = os.stat(self._path + "-wal").st_size
        except OSError:
            # No WAL yet (fresh spool, or WAL was checkpointed back to main).
            pass
        return main + wal

    def list_quarantined(self) -> list[dict]:
        """List rows currently held in the quarantine table.

        Returns a list of dicts with row metadata (no decrypted payload —
        the whole point of quarantine is that we can't decrypt). Operators
        use this in a recovery procedure: dump quarantine ciphertext + nonce,
        decrypt offline with the previous key, re-enqueue under the current
        key, then purge the quarantine row.
        """
        if self._closed:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, original_id, enqueued_at, requeue_count, "
                "failure_reason, quarantined_at "
                "FROM spool_quarantine_records ORDER BY id ASC"
            ).fetchall()
        return [
            {
                "id": r[0],
                "original_id": r[1],
                "enqueued_at": r[2],
                "requeue_count": r[3],
                "failure_reason": r[4],
                "quarantined_at": r[5],
            }
            for r in rows
        ]

    def quarantine_size(self) -> int:
        """Number of rows currently in the quarantine table.

        Operators can poll this to detect a key-rotation incident.
        """
        if self._closed:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM spool_quarantine_records"
            ).fetchone()
            return int(row[0]) if row else 0

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
    "SpoolPassphraseError",
]
