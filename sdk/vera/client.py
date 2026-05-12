"""Synchronous client for the Vera API.

# Concurrency model (workstream A1 + A7)

The synchronous :class:`VeraClient` mirrors :class:`AsyncVeraClient` and
provides a fire-and-forget :meth:`VeraClient.enqueue_action` in addition to
the original blocking :meth:`VeraClient.record_action`. The decorator in
:mod:`vera.decorator` switches to ``enqueue_action`` so customer code never
blocks on Vera availability.

Internals
---------
* A bounded :class:`queue.Queue` holds pending payloads. Default capacity is
  ``max_queue_size=10_000``. On overflow the oldest record is dropped with a
  rate-limited WARN log.
* A daemon background thread drains the queue in batches of up to ``100``
  records (capped by the API) and POSTs to ``/v1/actions/batch``. Default
  flush cadence is ``flush_interval=5`` seconds; an enqueue that fills the
  current batch wakes the worker immediately via a :class:`threading.Event`.
* Failed batches are classified per workstream A8: 4xx (other than 429) are
  permanently dropped with ERROR; 429 / 5xx / network errors are re-queued
  with exponential backoff plus jitter. A simple circuit breaker pauses
  flushing for an exponential cool-down after ``circuit_breaker_threshold``
  consecutive failures. Each record carries an internal ``_requeue_count``
  and is dropped after ``requeue_max_attempts`` re-queues to prevent
  infinite-loop CPU burn.

Supported runtimes
------------------
* CPython 3.10 / 3.11 / 3.12.
* Pre-fork servers — gunicorn (preload + post-fork), uvicorn workers, and
  Celery — are all supported. The client tracks ``os.getpid()`` and
  re-initialises queue + thread + lock on the first ``enqueue_action`` call
  in a forked child, and registers an ``os.register_at_fork`` handler to
  do the same proactively when available.
* :mod:`multiprocessing` worker pools work the same way — each worker
  starts a fresh background thread.

Unsupported runtimes
--------------------
* gevent / eventlet with monkey-patched threading. We emit a one-time
  WARN if we detect ``gevent.monkey`` has patched ``threading``. The
  background-thread model assumes preemptive scheduling; cooperative
  schedulers may starve the flush worker.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import random
import sys
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from .errors import (
    VeraAuthError,
    VeraError,
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
)
from .spool import Spool, SpoolDecryptionError, SpoolDiskFullError, SpoolError

if TYPE_CHECKING:
    from .redaction import Redactor

logger = logging.getLogger("vera.client")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5

# Maximum batch size the server accepts per /v1/actions/batch call.
_API_MAX_BATCH = 100


class ApprovalTimeoutError(Exception):
    """Raised when wait_for_approval times out before a human decides."""


class ApprovalRejectedError(Exception):
    """Raised when an approval is rejected, expired, or cancelled."""

    def __init__(self, approval: dict):
        self.approval = approval
        status = approval.get("status", "unknown")
        super().__init__(f"Approval {approval.get('id')} resolved as '{status}'")


# ---------------------------------------------------------------------------
# Helpers — exception classification (used by both sync + async clients).
# ---------------------------------------------------------------------------


def _request_id_from(exc: BaseException) -> str | None:
    """Best-effort extraction of ``X-Request-ID`` from an httpx error."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return response.headers.get("X-Request-ID") or response.headers.get(
            "x-request-id"
        )
    except Exception:  # pragma: no cover — defensive
        return None


def wrap_httpx_error(exc: Exception) -> Exception:
    """Translate an httpx error into the appropriate :mod:`vera.errors` type.

    Falls through (returns the original exception unchanged) for inputs that
    are not ``httpx`` errors so callers can re-raise without losing
    information about non-network bugs. All ``httpx.HTTPError`` descendants
    are guaranteed to map to a ``VeraError`` subclass — there's a catch-all
    branch at the bottom so we don't silently mis-classify new httpx error
    classes added in future releases.
    """
    rid = _request_id_from(exc)
    # 1) Status errors first — they carry the most-specific information.
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        message = f"HTTP {status} from {exc.request.method} {exc.request.url}"
        if status in (401, 403):
            return VeraAuthError(message, request_id=rid, status_code=status)
        if status == 429:
            return VeraRateLimitError(message, request_id=rid, status_code=status)
        if 500 <= status < 600:
            return VeraServerError(message, request_id=rid, status_code=status)
        if 400 <= status < 500:
            return VeraValidationError(message, request_id=rid, status_code=status)
        # Out-of-band status (1xx/2xx/3xx that raise_for_status flagged) —
        # fall through to the catch-all rather than returning raw httpx.
    # 2) Timeouts.
    if isinstance(exc, httpx.TimeoutException):
        return VeraTimeoutError(str(exc) or "request timed out", request_id=rid)
    # 3) Network / transport errors. Each of these classes shows up in the
    #    field; missing any of them leaks raw httpx out of the SDK.
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            httpx.LocalProtocolError,
            httpx.ProxyError,
            httpx.UnsupportedProtocol,
        ),
    ):
        return VeraNetworkError(str(exc) or "network failure", request_id=rid)
    # 4) Response decode failures — server returned junk we couldn't parse.
    if isinstance(exc, httpx.DecodingError):
        return VeraNetworkError(
            f"response decode failed: {exc}", request_id=rid
        )
    # 5) Redirect loops — surface as server error since we can't reach the
    #    final destination. status_code is unknown at this layer.
    if isinstance(exc, httpx.TooManyRedirects):
        return VeraServerError(str(exc), request_id=rid, status_code=None)
    # 6) Catch-all for any remaining httpx.HTTPError subclass. We'd rather
    #    map to a generic VeraError than leak raw httpx through the SDK.
    if isinstance(exc, httpx.HTTPError):
        return VeraError(f"unhandled httpx error: {exc}", request_id=rid)
    # 7) Not an httpx error — return unchanged so non-network bugs aren't
    #    masked by the SDK.
    return exc


def _gevent_threading_patched() -> bool:
    """Best-effort detection that gevent has monkey-patched threading."""
    gevent = sys.modules.get("gevent")
    if gevent is None:
        return False
    try:
        from gevent import monkey  # type: ignore[import-not-found]

        return bool(monkey.is_module_patched("threading"))
    except Exception:  # pragma: no cover — gevent absent or shape changed
        return False


_gevent_warned = False


def _warn_gevent_once() -> None:
    """Emit one WARN if gevent has patched threading."""
    global _gevent_warned
    if _gevent_warned:
        return
    _gevent_warned = True
    logger.warning(
        "vera.client: detected gevent.monkey-patched threading. The "
        "background flush worker assumes preemptive threads; cooperative "
        "schedulers may delay or starve flushes. Consider AsyncVeraClient."
    )


# Once-per-process ERROR log when the breaker has opened due to a permanent
# failure (e.g. bad API key) — used by ``VeraClient.enqueue_action`` so the
# customer notices their misconfiguration on the very next call instead of
# silently buffering then dropping records.
_permanent_breaker_warned = False


def _warn_breaker_permanent_once() -> None:
    """Emit one ERROR per process when the permanent-failure breaker opens."""
    global _permanent_breaker_warned
    if _permanent_breaker_warned:
        return
    _permanent_breaker_warned = True
    logger.error(
        "vera.client: circuit breaker open due to PERMANENT failure (4xx). "
        "Vera SDK is no longer accepting new audit records — the queue is "
        "being drained but new enqueue_action() calls will be refused until "
        "the underlying issue (likely bad API key or revoked credentials) is "
        "fixed. Verify VERA_API_KEY / api_url and reconstruct the client."
    )


def _reset_permanent_breaker_warning() -> None:
    """Reset the once-per-process flag. Intended for tests."""
    global _permanent_breaker_warned
    _permanent_breaker_warned = False


class VeraClient:
    """Synchronous client for the Vera API.

    Parameters mirror :class:`AsyncVeraClient` so they can be swapped in tests.

    Args:
        api_url: Base URL for the Vera API.
        api_key: Bearer token used as ``Authorization``.
        agent_name / agent_version / model_id / framework: Default identity
            metadata stamped onto every action.
        timeout: HTTP timeout in seconds. Default 5s.
        redactor: Optional :class:`Redactor` applied to user-supplied JSON
            blob fields at enqueue time.
        batch_size: Records per flush attempt. Default 50. The server accepts
            up to 100 per batch and the worker honours that hard cap.
        flush_interval: Seconds between periodic flushes. Default 5.
        max_queue_size: Maximum number of records held in memory. Default
            10,000. Drops oldest on overflow with rate-limited WARN.
        atexit_drain_timeout: Seconds to wait for the queue to drain at
            interpreter shutdown. Default 10.
        circuit_breaker_threshold: Consecutive flush failures before the
            worker pauses flushing. Default 5.
        requeue_max_attempts: Maximum number of times a record may be
            re-queued before being dropped with a WARN. Default 10.
        persistent_buffer_path: Optional filesystem path to a SQLite-backed
            durable spool (workstream A5). When set, queue overflow spills
            to the spool instead of dropping oldest, and queued records
            survive process restarts. Requires the ``VERA_SPOOL_KEY`` env
            var (used as the passphrase for AES-256-GCM encryption at rest).
        persistent_buffer_max_bytes: Optional cap on the spool size. Defaults
            to 100 MB. When exceeded, new spool writes raise
            ``SpoolDiskFullError`` and the client falls back to in-memory
            drop-oldest with a WARN.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str = "",
        agent_name: str = "default-agent",
        agent_version: str | None = None,
        model_id: str | None = None,
        framework: str | None = None,
        timeout: float = 5.0,
        redactor: "Redactor | None" = None,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
        atexit_drain_timeout: float = 10.0,
        circuit_breaker_threshold: int = 5,
        requeue_max_attempts: int = 10,
        persistent_buffer_path: str | None = None,
        persistent_buffer_max_bytes: int = 100_000_000,
    ):
        self.api_url = api_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.model_id = model_id
        self.framework = framework
        # Opt-in redaction. When set, record_action / record_action_batch /
        # enqueue_action route input_data, outcome, reasoning, and
        # error_message through the redactor before sending. Default None
        # preserves the current pass-through behaviour for direct callers
        # who construct their own payloads — opt-in by design (no surprises).
        self._redactor = redactor
        # Save the kwargs needed to recreate the httpx.Client after fork().
        # The child must NOT inherit the parent's TCP/TLS sockets — see
        # _after_in_child for the rebuild path.
        self._httpx_client_kwargs: dict[str, Any] = {
            "base_url": self.api_url,
            "headers": {"Authorization": f"Bearer {api_key}"},
            "timeout": timeout,
        }
        self._client = httpx.Client(**self._httpx_client_kwargs)

        # Background-flush configuration.
        self._batch_size = max(1, batch_size)
        self._flush_interval = float(flush_interval)
        self._max_queue_size = max(1, max_queue_size)
        self._atexit_drain_timeout = float(atexit_drain_timeout)
        self._circuit_breaker_threshold = max(1, circuit_breaker_threshold)
        self._requeue_max_attempts = max(1, requeue_max_attempts)

        # Queue + worker thread state.  All of this is reinitialised on fork
        # because pthread state cannot cross the fork boundary safely.
        self._owner_pid: int | None = None
        self._queue: queue.Queue | None = None
        self._wakeup: threading.Event | None = None
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._closed = False

        # Drop-oldest WARN throttling — a runaway producer can otherwise spam
        # logs once per overflowed enqueue.
        self._overflow_warn_lock = threading.Lock()
        self._overflow_drops_since_warn = 0
        self._overflow_last_warn_at: float = 0.0
        self._overflow_warn_min_interval = 1.0  # seconds

        # Circuit-breaker bookkeeping (read/written from worker thread only).
        self._consecutive_failures = 0
        self._breaker_open_until: float = 0.0
        # Why the breaker is open. ``"permanent"`` means the last failure was
        # a 4xx-other-than-429 — we should reject new enqueues to avoid
        # silently filling the queue while the customer's API key is bad.
        # ``"transient"`` means 429/5xx/network — keep accepting; the queue
        # is the buffer for retry. ``None`` means closed.
        self._breaker_cause: str | None = None
        # Lock for the overflow drop-oldest path. The get/put pair is racy
        # under threaded enqueue without this — two producers can both pop
        # an item and put their own, double-dropping a third item.
        self._overflow_get_put_lock = threading.Lock()

        # Register os.register_at_fork to reset state proactively in children.
        # Some platforms / interpreters (Windows, very old CPython) lack it.
        if hasattr(os, "register_at_fork"):
            try:
                os.register_at_fork(after_in_child=self._after_in_child)
            except Exception:  # pragma: no cover — extremely defensive
                pass

        # atexit drain is registered lazily on first ``enqueue_action`` call
        # (see ``_ensure_atexit_registered``). Constructing many clients
        # without using the queue path (e.g. notebooks, integration tests)
        # used to leak one atexit hook per instance — they're never garbage
        # collected because atexit holds a strong reference.
        self._atexit_registered = False
        # Idempotency: track once-per-process error logging for the
        # permanent-failure breaker so a stuck-bad-key process doesn't spam
        # ERRORs on every enqueue.
        self._enqueue_blocked_warned = False

        # Workstream A5 — durable on-disk spool. ``persistent_buffer_path``
        # is opt-in. When set, queue overflow spills to the spool instead of
        # dropping oldest. ``VERA_SPOOL_KEY`` is required (fail-closed) so
        # we never persist plaintext PHI to disk.
        self._persistent_buffer_path = persistent_buffer_path
        self._persistent_buffer_max_bytes = persistent_buffer_max_bytes
        self._spool: Spool | None = None
        # Maps in-memory queue items back to the spool row_id they were
        # rehydrated from. ``id(payload)`` is the dict identity — stable for
        # the lifetime of the object, unique while it's in our queue.
        self._spool_row_map: dict[int, int] = {}
        self._spool_map_lock = threading.Lock()
        # One-shot WARN when SpoolDiskFullError forces drop-oldest fallback.
        self._spool_full_warned = False
        # One-shot loud ERROR when a SpoolDecryptionError fires — see
        # ``_warn_spool_decrypt_once``. After firing, ``_spool_drain_disabled``
        # is set so subsequent flush ticks fall back to in-memory only.
        self._spool_decrypt_warned = False
        self._spool_drain_disabled = False
        if persistent_buffer_path is not None:
            passphrase = os.environ.get("VERA_SPOOL_KEY", "")
            if not passphrase:
                raise ValueError(
                    "VERA_SPOOL_KEY env var required when "
                    "persistent_buffer_path is set"
                )
            self._spool = Spool(
                persistent_buffer_path,
                passphrase=passphrase,
                max_bytes=persistent_buffer_max_bytes,
            )
            # Eagerly initialise the queue + worker so any records persisted
            # from a previous process run get rehydrated immediately rather
            # than waiting for the first enqueue_action call. Customers
            # configuring a spool care about recovery-on-startup semantics.
            if self._spool.size() > 0:
                self._init_runtime_state()

    # ------------------------------------------------------------------
    # Redaction
    # ------------------------------------------------------------------

    def _redact_payload_fields(self, payload: dict) -> dict:
        """Apply ``self._redactor`` (if set) to user-supplied JSON-blob fields.

        Redacted fields: ``input_data``, ``outcome``, ``reasoning``,
        ``error_message``. Identifying fields (``action_name``,
        ``agent_name``, ``model_id``, ``target_system`` etc.) are
        preserved as-is — those are operational metadata, not user data.
        """
        if self._redactor is None:
            return payload
        redacted = dict(payload)  # shallow copy — we replace values, not keys
        for k in ("input_data", "outcome", "reasoning"):
            if redacted.get(k) is not None:
                redacted[k] = self._redactor.serialize(redacted[k])
        if redacted.get("error_message") is not None:
            redacted["error_message"] = self._redactor.serialize(
                redacted["error_message"]
            )
        return redacted

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------

    def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with exponential backoff retry.

        Translates terminal failures into :mod:`vera.errors` types so callers
        can ``except VeraError`` without depending on httpx internals. The
        same Idempotency-Key (if supplied by the caller) is reused across
        retry attempts so the server can dedupe.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = getattr(self._client, method)(path, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code < 500 and e.response.status_code != 429:
                    # 4xx (except 429) are not retried — fail fast.
                    raise wrap_httpx_error(e) from e
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                    e,
                )
                time.sleep(wait)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                    e,
                )
                time.sleep(wait)
        # Retries exhausted — surface a branded error.
        assert last_exc is not None
        raise wrap_httpx_error(last_exc) from last_exc

    # ------------------------------------------------------------------
    # Public actions API
    # ------------------------------------------------------------------

    def record_action(
        self,
        action_name: str,
        action_type: str = "function_call",
        result: str = "success",
        input_data: dict | None = None,
        outcome: dict | None = None,
        reasoning: dict | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
        **kwargs,
    ) -> dict:
        """Record a single action synchronously.

        Blocks the caller until the server acknowledges or retries are
        exhausted. Raises a :class:`vera.errors.VeraError` subclass on
        terminal failure. This is the original (pre-async-by-default)
        behaviour and is preserved deliberately — direct callers who want
        an ack should keep using this method.

        For fire-and-forget recording from hot paths, use
        :meth:`enqueue_action` instead.
        """
        payload = {
            "action_name": action_name,
            "action_type": action_type,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "model_id": self.model_id,
            "framework": self.framework,
            "result": result,
            "input_data": input_data or {},
            "outcome": outcome or {},
            "reasoning": reasoning or {},
            "duration_ms": duration_ms,
            "error_message": error_message,
            **kwargs,
        }
        payload = self._redact_payload_fields(payload)
        # The retry loop in _request_with_retry passes the same kwargs on
        # every attempt, so the same Idempotency-Key is sent on retries —
        # which is exactly what the server-side dedupe wants.
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        resp = self._request_with_retry(
            "post", "/v1/actions", json=payload, headers=headers
        )
        return resp.json()

    def record_action_batch(self, records: list[dict]) -> list[dict]:
        """Record a batch of actions synchronously."""
        if self._redactor is not None:
            records = [self._redact_payload_fields(r) for r in records]
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        resp = self._request_with_retry(
            "post", "/v1/actions/batch", json={"records": records}, headers=headers
        )
        return resp.json()

    def enqueue_action(self, **kwargs: Any) -> None:
        """Add an action to the background queue (non-blocking).

        Mirrors :meth:`AsyncVeraClient.enqueue_action`. Returns immediately
        after stamping identity fields, applying redaction, and putting the
        payload on the in-memory queue. A daemon background thread drains
        the queue in batches and POSTs to ``/v1/actions/batch``.

        Failure handling is fully internal — Vera-side errors never raise
        out of this call. See workstream A8 for the poison-batch policy.

        Permanent-failure breaker: if the background worker has classified
        the previous batch failure as permanent (4xx other than 429 — most
        commonly a bad API key), this method refuses to enqueue further
        records and emits a single ERROR for the process. We'd otherwise
        silently fill the queue while every flush attempt was rejected.
        """
        # Fork-safety check first — cheap fast path when pid hasn't changed.
        if self._owner_pid != os.getpid():
            self._init_runtime_state()

        if _gevent_threading_patched():
            _warn_gevent_once()

        # Refuse to accept new records when the breaker is open due to a
        # permanent failure. Transient (429/5xx/network) breaker windows
        # leave the queue accepting — those are expected to recover and the
        # queue is the buffer for retry.
        if (
            self._breaker_cause == "permanent"
            and time.monotonic() < self._breaker_open_until
        ):
            self._warn_enqueue_blocked_permanent_failure_once()
            return

        payload = {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "model_id": self.model_id,
            "framework": self.framework,
            **kwargs,
        }
        # Redact at enqueue time so memory/disk dumps don't contain raw PHI
        # and the flush path doesn't repeat the work.
        if self._redactor is not None:
            payload = self._redact_payload_fields(payload)

        # Internal bookkeeping field — stripped before POST.
        payload.setdefault("_requeue_count", 0)
        # Idempotency-Key chosen at enqueue time so retries — including
        # re-queues across batch boundaries — reuse the same key. The
        # server's dedupe table then collapses duplicate inserts when a
        # network blip causes a retry of the same record.
        payload.setdefault("_idempotency_key", uuid.uuid4().hex)

        assert self._queue is not None  # set by _init_runtime_state

        # Lazy atexit registration — avoid one hook per VeraClient instance
        # in long-running processes that construct many clients (notebooks,
        # tests). The pid check inside _atexit_drain handles the case where
        # fork() duplicates the parent's atexit list into the child.
        self._ensure_atexit_registered()

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            # Overflow path. If a durable spool is configured, spill there
            # rather than dropping — that's the whole point of A5. The
            # in-memory queue stays full; the worker drains it normally,
            # and subsequent rehydrate / dequeue cycles will pull rows
            # back from disk.
            #
            # Skipped when ``_spool_drain_disabled`` is set — a previous
            # SpoolDecryptionError put us in fallback mode and writing new
            # records to a spool we can no longer read would just stack
            # undecryptable rows.
            if self._spool is not None and not self._spool_drain_disabled:
                try:
                    self._spool.enqueue(payload)
                    return
                except SpoolDiskFullError:
                    # Spool is full or disk is exhausted. Fall through to
                    # drop-oldest so the customer's process doesn't stall.
                    # Once-per-process WARN so we don't spam the log on
                    # every subsequent enqueue.
                    self._warn_spool_full_once()
                except SpoolError as exc:  # pragma: no cover — defensive
                    logger.error("vera.client: spool enqueue failed: %s", exc)
            # Drop oldest then retry once. The get/put pair is racy under
            # threaded enqueue without a lock — two producers can both pop
            # an item and put their own, double-dropping a third. Hold the
            # overflow lock across the pair to serialize.
            with self._overflow_get_put_lock:
                try:
                    dropped = self._queue.get_nowait()
                except queue.Empty:  # pragma: no cover — race
                    dropped = None
                self._record_overflow_drop(dropped)
                # If the dropped item was rehydrated from spool, drop the
                # mapping so we never ack a row that wasn't actually
                # delivered. The on-disk row stays; next rehydrate will
                # see it again.
                if dropped is not None:
                    with self._spool_map_lock:
                        self._spool_row_map.pop(id(dropped), None)
                try:
                    self._queue.put_nowait(payload)
                except queue.Full:  # pragma: no cover — pathological
                    self._record_overflow_drop(payload)
                    return

        # Wake the worker if a batch is full so we don't sit on it for the
        # full flush_interval.
        if (
            self._wakeup is not None
            and self._queue.qsize() >= self._batch_size
        ):
            self._wakeup.set()

    def _ensure_atexit_registered(self) -> None:
        """Register the atexit drain hook on first use, idempotently.

        Avoids the per-instance atexit leak that the eager registration in
        ``__init__`` caused. Long-running processes that construct many
        clients (notebooks, large test suites) used to accumulate one
        ``_atexit_drain`` callback per instance — none of which can be
        garbage-collected because atexit holds strong references.
        """
        if self._atexit_registered:
            return
        try:
            atexit.register(self._atexit_drain)
        except Exception:  # pragma: no cover — interpreter shutdown race
            return
        self._atexit_registered = True

    def _warn_enqueue_blocked_permanent_failure_once(self) -> None:
        """Emit one ERROR per client when the permanent breaker rejects an enqueue."""
        if self._enqueue_blocked_warned:
            return
        self._enqueue_blocked_warned = True
        _warn_breaker_permanent_once()

    def _warn_spool_full_once(self) -> None:
        """Emit one WARN per client when SpoolDiskFullError forces drop-oldest fallback."""
        if self._spool_full_warned:
            return
        self._spool_full_warned = True
        logger.warning(
            "vera.client: durable spool is full (max_bytes=%d) — falling "
            "back to in-memory drop-oldest. Audit chain will have gaps "
            "until disk pressure clears.",
            self._persistent_buffer_max_bytes,
        )

    # ------------------------------------------------------------------
    # Background-thread internals
    # ------------------------------------------------------------------

    def _record_overflow_drop(self, dropped: dict | None) -> None:
        """Throttled WARN log on queue overflow."""
        action_name = (dropped or {}).get("action_name", "unknown")
        with self._overflow_warn_lock:
            self._overflow_drops_since_warn += 1
            now = time.monotonic()
            if (
                now - self._overflow_last_warn_at
                >= self._overflow_warn_min_interval
            ):
                drops = self._overflow_drops_since_warn
                self._overflow_drops_since_warn = 0
                self._overflow_last_warn_at = now
                logger.warning(
                    "Vera queue full (max=%d). Dropped oldest record (%s); "
                    "%d total drops since last warn.",
                    self._max_queue_size,
                    action_name,
                    drops,
                )

    def _init_runtime_state(self) -> None:
        """Create or reset queue + lock + worker. Idempotent and fork-safe."""
        with self._state_lock:
            current_pid = os.getpid()
            if (
                self._queue is not None
                and self._owner_pid == current_pid
                and self._worker is not None
                and self._worker.is_alive()
            ):
                return
            # Fresh state — child after fork, or first call ever.
            # Belt-and-suspenders: if ``os.register_at_fork`` didn't fire
            # (older interpreters, raw ``os.fork()`` paths that bypass fork
            # hooks), we may still have the parent's ``httpx.Client`` here.
            # Detect by pid mismatch and rebuild proactively.
            if self._owner_pid is not None and self._owner_pid != current_pid:
                self._reset_httpx_client_for_fork()
                self._atexit_registered = False
            self._queue = queue.Queue(maxsize=self._max_queue_size)
            self._wakeup = threading.Event()
            self._stop_event = threading.Event()
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            self._breaker_cause = None
            self._owner_pid = current_pid
            self._closed = False
            # Rehydrate from durable spool before starting the worker so any
            # records persisted by a previous process run get re-delivered.
            # We fill up to ``max_queue_size`` from the spool; remaining rows
            # stay on disk and are pulled in by subsequent flush cycles via
            # the same dequeue_batch path.
            self._rehydrate_from_spool()
            t = threading.Thread(
                target=self._worker_loop,
                name="vera-flush",
                daemon=True,
            )
            self._worker = t
            t.start()

    def _rehydrate_from_spool(self) -> None:
        """Load persisted records from the spool back into the memory queue.

        Called once at queue init. Records are loaded oldest-first to
        preserve insertion order. We deliberately do NOT delete rows from
        the spool here — they stay until the worker flushes them and acks.
        That keeps the durability invariant: a crash between rehydrate and
        flush still leaves the records on disk.

        :class:`SpoolDecryptionError` (raised after rows have already been
        moved to quarantine by :meth:`Spool.dequeue_batch`) triggers a
        once-per-process loud ERROR and disables further spool drains for
        this process. We don't continue draining because the next batch
        would just quarantine more rows under the wrong key — better to
        let the operator stop the process and run the recovery procedure.
        """
        if self._spool is None or self._queue is None:
            return
        capacity = self._max_queue_size
        try:
            batch = self._spool.dequeue_batch(max_count=capacity)
        except SpoolDecryptionError as exc:
            self._warn_spool_decrypt_once(exc)
            self._spool_drain_disabled = True
            return
        except Exception as exc:  # pragma: no cover — defensive
            logger.error("vera.client: spool rehydrate failed: %s", exc)
            return
        with self._spool_map_lock:
            self._spool_row_map.clear()
            for row_id, record in batch:
                try:
                    self._queue.put_nowait(record)
                    self._spool_row_map[id(record)] = row_id
                except queue.Full:  # pragma: no cover — capacity sized for batch
                    break
        if batch:
            logger.info(
                "vera.client: rehydrated %d records from spool %s",
                len(batch),
                self._persistent_buffer_path,
            )

    def _warn_spool_decrypt_once(self, exc: SpoolDecryptionError) -> None:
        """Emit one loud ERROR per process when a spool decrypt fails."""
        if self._spool_decrypt_warned:
            return
        self._spool_decrypt_warned = True
        logger.error(
            "vera.client: SPOOL DECRYPTION FAILURE — %d row(s) moved to "
            "quarantine (possible VERA_SPOOL_KEY rotation without "
            "migration). Audit-chain rows are preserved on disk but require "
            "operator intervention to recover. See docs/spool-key-rotation.md. "
            "Spool drain disabled for this process; new records will be "
            "buffered in memory only until restart with the correct key. "
            "Underlying exception: %s",
            len(exc.quarantined_ids),
            exc,
        )

    def _after_in_child(self) -> None:
        """Run inside the child after :func:`os.fork`.

        Discard the parent's queue + thread (they don't exist here) and let
        :meth:`_init_runtime_state` recreate everything on next use.

        Also discard the parent's ``httpx.Client``. The child inherits the
        parent's TCP connections + TLS session state across ``fork()``; reusing
        them produces interleaved bytes on the wire (worst case) or hung
        sockets (best case). This is the production-fatal bug for customers
        using ``gunicorn --preload``, Celery prefork, or
        ``multiprocessing.Pool`` — the parent warms a connection pool, then
        every worker child silently corrupts requests on first POST.
        """
        # We deliberately do NOT take ``_state_lock`` here — fork() inside a
        # locked section is what creates the badness in the first place.
        self._reset_httpx_client_for_fork()
        self._queue = None
        self._wakeup = None
        self._stop_event = None
        self._worker = None
        self._owner_pid = None
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._breaker_cause = None
        self._closed = False
        # Reset the lock object — children don't inherit a useful state.
        self._state_lock = threading.Lock()
        self._overflow_warn_lock = threading.Lock()
        self._overflow_drops_since_warn = 0
        self._overflow_last_warn_at = 0.0
        # The parent's atexit registration is duplicated into the child's
        # atexit list by fork(); the pid check inside ``_atexit_drain``
        # short-circuits cross-pid drains, but we still want the child to
        # register its own (with its own _closed gate) once it actually
        # enqueues something.
        self._atexit_registered = False
        # Spool — the SQLite connection is not fork-safe. Drop the inherited
        # handle and open a fresh one. The on-disk WAL state is shared
        # safely across processes, so existing rows are still visible.
        if self._spool is not None:
            try:
                self._spool.reopen_after_fork()
            except Exception:  # pragma: no cover — defensive
                pass
        # The spool->queue mapping uses ``id(payload)`` of dicts in the
        # parent process. None of those dicts exist in the child, so the
        # mapping is meaningless and must be cleared.
        self._spool_row_map = {}
        self._spool_map_lock = threading.Lock()
        self._spool_full_warned = False

    def _reset_httpx_client_for_fork(self) -> None:
        """Close the inherited parent httpx.Client and create a fresh one.

        Closing is best-effort — the underlying sockets may already be in a
        corrupt state from ``fork()`` and ``close()`` itself can raise. We
        always swap in a fresh client, even if close fails.
        """
        try:
            self._client.close()
        except Exception:  # pragma: no cover — defensive: post-fork sockets
            pass
        self._client = httpx.Client(**self._httpx_client_kwargs)

    def _worker_loop(self) -> None:
        """Background thread: drain the queue, flush, classify failures."""
        assert self._wakeup is not None
        assert self._stop_event is not None
        while True:
            # Sleep until: (a) flush_interval elapses, (b) a batch is full
            # (wakeup), or (c) close() asked us to stop.
            self._wakeup.wait(timeout=self._flush_interval)
            self._wakeup.clear()

            # Circuit breaker — pause flushing for the cool-down window.
            if time.monotonic() < self._breaker_open_until:
                if self._stop_event.is_set():
                    break
                continue

            try:
                self._drain_once()
            except Exception:  # noqa: BLE001 — defensive isolation
                logger.exception("vera.client: unexpected error in flush worker")

            if self._stop_event.is_set() and self._queue is not None and self._queue.empty():
                break

    def _drain_once(self) -> None:
        """Pull one batch off the queue and attempt to flush it."""
        assert self._queue is not None
        # Pull additional records from the spool to top up the in-memory
        # queue. This is the "trickle-drain" path: when the spool has more
        # records than fit in the queue at rehydrate-time, subsequent flush
        # ticks pull them in batch-sized chunks. We do this BEFORE the
        # empty-check so a spool-only state (memory queue empty, spool
        # non-empty) still makes forward progress.
        self._pull_from_spool_into_queue()
        if self._queue.empty():
            return

        batch: list[dict] = []
        # Cap each flush at the API max (100). Worker keeps looping on
        # subsequent iterations if more items exist.
        cap = min(_API_MAX_BATCH, max(self._batch_size, 1))
        while len(batch) < cap:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return

        records = [self._strip_internal_fields(r) for r in batch]
        headers = {"Idempotency-Key": self._batch_idempotency_key(batch)}
        # Snapshot which records in this batch were rehydrated from the
        # spool. We must do this BEFORE the network call so a successful
        # flush can ack the rows. If the flush fails we re-queue the
        # records (still mapped to the same row_ids); the mapping is
        # restored as part of re-queue.
        spool_row_ids: list[int] = []
        if self._spool is not None:
            with self._spool_map_lock:
                for r in batch:
                    row_id = self._spool_row_map.pop(id(r), None)
                    if row_id is not None:
                        spool_row_ids.append(row_id)
        try:
            self._request_with_retry(
                "post",
                "/v1/actions/batch",
                json={"records": records},
                headers=headers,
            )
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            self._breaker_cause = None
            # Ack the spool rows now that the batch is durably accepted.
            if spool_row_ids and self._spool is not None:
                try:
                    self._spool.ack(spool_row_ids)
                except Exception as exc:  # pragma: no cover — defensive
                    logger.error(
                        "vera.client: spool ack failed for %d rows: %s",
                        len(spool_row_ids),
                        exc,
                    )
            logger.debug("Flushed %d queued actions", len(batch))
        except Exception as exc:  # noqa: BLE001 — we classify below
            # On failure, re-establish the spool row mapping so a later
            # successful flush can still ack.
            if spool_row_ids and self._spool is not None:
                with self._spool_map_lock:
                    for r, rid in zip(batch, spool_row_ids):
                        self._spool_row_map[id(r)] = rid
            self._handle_flush_failure(batch, exc)

    def _pull_from_spool_into_queue(self) -> None:
        """Top up the in-memory queue from the spool when both are non-empty.

        Only meaningful when a spool is configured AND there's free capacity
        in the queue. Cheap fast-path checks avoid the SQLite hit on every
        flush tick when there's nothing to do.

        Skipped after a :class:`SpoolDecryptionError` has fired — see
        ``_spool_drain_disabled``.
        """
        if self._spool is None or self._queue is None or self._spool_drain_disabled:
            return
        free = self._max_queue_size - self._queue.qsize()
        if free <= 0:
            return
        # Don't re-pull rows we already have in memory. Anything in
        # ``_spool_row_map`` is currently queued (or in-flight) so we
        # exclude those row_ids from the next pull. We pull a bit more
        # than the free slot count so the next-flush batch is sized well.
        with self._spool_map_lock:
            held = set(self._spool_row_map.values())
        try:
            batch = self._spool.dequeue_batch(max_count=min(free, _API_MAX_BATCH))
        except SpoolDecryptionError as exc:
            self._warn_spool_decrypt_once(exc)
            self._spool_drain_disabled = True
            return
        except Exception as exc:  # pragma: no cover — defensive
            logger.error("vera.client: spool pull failed: %s", exc)
            return
        if not batch:
            return
        with self._spool_map_lock:
            for row_id, record in batch:
                if row_id in held:
                    continue
                try:
                    self._queue.put_nowait(record)
                    self._spool_row_map[id(record)] = row_id
                except queue.Full:
                    break

    @staticmethod
    def _strip_internal_fields(payload: dict) -> dict:
        """Return a copy of ``payload`` with internal bookkeeping removed.

        The per-record ``_idempotency_key`` is PROMOTED into
        ``metadata.record_idempotency_key`` before stripping so it survives
        the wire. This lets the server (or any downstream auditor) dedupe
        per record even when batch composition shifts across restarts.

        Before this change the only idempotency signal on the wire was the
        batch-level ``Idempotency-Key`` header, which uses the FIRST
        record's key. If the process was SIGKILLed between server-200 and
        spool-ack, the next start would re-POST the same records but the
        batch composition could be different (e.g. mixed with fresh
        records) — different "first" record, different header, so the
        server's per-batch dedupe wouldn't fire and duplicates landed.

        Storing the key in ``metadata`` keeps the change additive: the
        backend's ``ActionRecordCreate`` schema already accepts arbitrary
        keys inside ``metadata: dict``, so we don't need a backend release
        for this fix to be useful (existing per-record idempotency is
        documented; per-record dedupe lands when the backend gains a
        unique-index pass on the metadata key).
        """
        out = {k: v for k, v in payload.items() if not k.startswith("_")}
        idem = payload.get("_idempotency_key")
        if isinstance(idem, str) and idem:
            # Embed under metadata (a dict the server already accepts) so
            # we don't widen the schema. ``setdefault`` for the dict and
            # for the key — the caller may have set their own
            # ``record_idempotency_key`` already, in which case we keep
            # theirs (it's their data subject's idempotency, not ours).
            metadata = dict(out.get("metadata") or {})
            metadata.setdefault("record_idempotency_key", idem)
            out["metadata"] = metadata
        return out

    @staticmethod
    def _batch_idempotency_key(batch: list[dict]) -> str:
        """Stable Idempotency-Key for a batch.

        Uses the first record's per-record key so that a batch which is
        re-queued and re-sent later carries the same key — server-side
        dedupe collapses duplicate inserts after a network blip retry.
        Falls back to a fresh uuid for legacy callers that put items on
        the queue without an ``_idempotency_key`` (e.g. tests).
        """
        if batch:
            key = batch[0].get("_idempotency_key")
            if isinstance(key, str) and key:
                return key
        return uuid.uuid4().hex

    def _handle_flush_failure(self, batch: list[dict], exc: BaseException) -> None:
        """Apply the A8 poison-batch classification to a failed batch."""
        permanent = self._is_permanent_failure(exc)
        if permanent:
            # 4xx (other than 429): drop with ERROR. Preserves the branded
            # class name so customers can grep their logs.
            cls_name = type(exc).__name__
            logger.error(
                "vera.client: dropping %d records due to %s: %s. Records WILL NOT be retried.",
                len(batch),
                cls_name,
                exc,
            )
            # Permanent failures still count toward the breaker — auth
            # errors and config errors should pause us from hammering.
            self._consecutive_failures += 1
            # Latest cause is permanent — preserved for the breaker check
            # in ``enqueue_action``. A subsequent transient or successful
            # flush will overwrite this.
            last_cause = "permanent"
        else:
            # 429 / 5xx / network / timeout — re-queue with backoff.
            self._consecutive_failures += 1
            requeued = 0
            dropped_for_age = 0
            for record in batch:
                count = int(record.get("_requeue_count", 0)) + 1
                if count > self._requeue_max_attempts:
                    dropped_for_age += 1
                    continue
                record["_requeue_count"] = count
                try:
                    assert self._queue is not None
                    self._queue.put_nowait(record)
                    requeued += 1
                except queue.Full:
                    self._record_overflow_drop(record)
            if dropped_for_age:
                logger.warning(
                    "vera.client: dropped %d records after %d re-queue attempts (poison-record cap).",
                    dropped_for_age,
                    self._requeue_max_attempts,
                )
            logger.warning(
                "vera.client: flush failed (%s). Re-queued %d records; %d dropped at cap.",
                exc,
                requeued,
                dropped_for_age,
            )
            last_cause = "transient"

        # Open the breaker after threshold consecutive failures. Backoff
        # grows exponentially up to 60s.
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            over = self._consecutive_failures - self._circuit_breaker_threshold
            cooldown = min(60.0, RETRY_BACKOFF_BASE * (2 ** over))
            jitter = cooldown * 0.1 * random.random()
            self._breaker_open_until = time.monotonic() + cooldown + jitter
            self._breaker_cause = last_cause
            logger.warning(
                "vera.client: circuit breaker open for %.2fs after %d consecutive failures (cause=%s).",
                cooldown + jitter,
                self._consecutive_failures,
                last_cause,
            )
            if last_cause == "permanent":
                # One ERROR per process so the customer's misconfiguration
                # is impossible to miss. The next ``enqueue_action`` will
                # short-circuit and re-emit the same ERROR (also gated to
                # once-per-process) so customer code paths surface it too.
                _warn_breaker_permanent_once()

    @staticmethod
    def _is_permanent_failure(exc: BaseException) -> bool:
        """Return True if the failure should not be retried."""
        if isinstance(exc, (VeraAuthError, VeraValidationError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return 400 <= status < 500 and status != 429
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Flush the queue, stop the background thread, close the HTTP client."""
        self._closed = True
        self._drain_and_stop(timeout=self._atexit_drain_timeout)
        try:
            self._client.close()
        except Exception:  # pragma: no cover — defensive
            pass
        # The spool stays on disk — closing the handle does NOT delete
        # records. Any rows still present here will be rehydrated on the
        # next process startup with the same persistent_buffer_path.
        if self._spool is not None:
            try:
                self._spool.close()
            except Exception:  # pragma: no cover — defensive
                pass

    def _atexit_drain(self) -> None:
        """Process-exit hook — best-effort drain bounded by configured timeout."""
        if self._closed:
            return
        if self._owner_pid is None or self._owner_pid != os.getpid():
            # Either we never started a worker or we forked into a child
            # whose worker was reset. Nothing to drain.
            return
        try:
            self._drain_and_stop(timeout=self._atexit_drain_timeout)
        except Exception:  # pragma: no cover — defensive
            pass
        try:
            self._client.close()
        except Exception:  # pragma: no cover — defensive
            pass

    def _drain_and_stop(self, timeout: float) -> None:
        """Wake the worker, ask it to drain remaining items, then join it.

        If the worker can't keep up within ``timeout`` we synchronously
        flush whatever's left from the calling thread (still bounded by
        the overall ``timeout``) so the user's ``close()`` doesn't lose
        records silently when the worker happens to be parked in
        ``wait()``.
        """
        if self._worker is None or not self._worker.is_alive():
            return
        if self._stop_event is not None:
            self._stop_event.set()
        if self._wakeup is not None:
            self._wakeup.set()
        deadline = time.monotonic() + timeout
        # Encourage the worker to drain promptly.
        while (
            self._queue is not None
            and not self._queue.empty()
            and time.monotonic() < deadline
        ):
            if self._wakeup is not None:
                self._wakeup.set()
            time.sleep(0.05)
        remaining = max(0.0, deadline - time.monotonic())
        self._worker.join(timeout=remaining)

        # If we have time left and the queue is still non-empty, do a final
        # best-effort synchronous flush from the caller's thread. We
        # tolerate any error here — close() must not raise — and we honour
        # the overall deadline so a hanging server can't pin the caller.
        if (
            self._queue is not None
            and not self._queue.empty()
            and time.monotonic() < deadline
        ):
            self._flush_from_calling_thread(deadline=deadline)

    def _flush_from_calling_thread(self, deadline: float) -> None:
        """Synchronously drain the queue from the caller, bounded by ``deadline``.

        Acquires the state lock for the get/post pair so a still-running
        background worker (the daemon thread can't be force-killed) doesn't
        race us into double-popping or double-posting the same record.
        """
        if self._queue is None:
            return
        while not self._queue.empty() and time.monotonic() < deadline:
            with self._state_lock:
                if self._queue is None:
                    return
                batch: list[dict] = []
                cap = min(_API_MAX_BATCH, max(self._batch_size, 1))
                while len(batch) < cap:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if not batch:
                    break
                records = [self._strip_internal_fields(r) for r in batch]
                headers = {"Idempotency-Key": self._batch_idempotency_key(batch)}
            try:
                self._request_with_retry(
                    "post",
                    "/v1/actions/batch",
                    json={"records": records},
                    headers=headers,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "vera.client: final close-time flush failed for %d records: %s",
                    len(batch),
                    exc,
                )
                # Don't loop forever — bail.
                return

    # ------------------------------------------------------------------
    # Other endpoints (unchanged from pre-A1 behaviour)
    # ------------------------------------------------------------------

    def query_actions(self, **filters) -> dict:
        """Query action records with filters."""
        resp = self._request_with_retry("get", "/v1/actions", params=filters)
        return resp.json()

    def verify_chain(self) -> dict:
        """Verify the integrity of the action chain."""
        resp = self._request_with_retry("get", "/v1/verify")
        return resp.json()

    def register_agent(
        self,
        name: str,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Register an agent."""
        payload = {"name": name, "description": description, "metadata": metadata or {}}
        resp = self._request_with_retry("post", "/v1/agents", json=payload)
        return resp.json()

    def list_agents(self) -> list[dict]:
        """List all agents."""
        resp = self._request_with_retry("get", "/v1/agents")
        return resp.json()

    def create_checkpoint(self) -> dict:
        """Create a signed checkpoint of the current chain state."""
        resp = self._request_with_retry("post", "/v1/verify/checkpoints")
        return resp.json()

    def list_checkpoints(self) -> dict:
        """List all checkpoints for the organization."""
        resp = self._request_with_retry("get", "/v1/verify/checkpoints")
        return resp.json()

    def verify_checkpoints(self) -> dict:
        """Verify all checkpoints for the organization."""
        resp = self._request_with_retry("post", "/v1/verify/checkpoints/verify")
        return resp.json()

    # ── Human-in-the-Loop approvals ───────────────────────────────────────

    def request_approval(
        self,
        action_name: str,
        risk_tier: str = "high",
        action_summary: str | None = None,
        data_subject_id: str | None = None,
        context: dict | None = None,
        approvers_required: int = 1,
        expires_in_seconds: int | None = None,
    ) -> dict:
        """Ask a human to approve an action before the agent takes it.

        Writes a pending record to the audit chain and returns the approval row.
        Use `wait_for_approval()` or `get_approval()` to poll for the decision.

        Required for EU AI Act Article 14 (human oversight of high-risk AI).
        """
        payload = {
            "agent_name": self.agent_name,
            "action_name": action_name,
            "action_summary": action_summary,
            "data_subject_id": data_subject_id,
            "context": context or {},
            "risk_tier": risk_tier,
            "approvers_required": approvers_required,
            "expires_in_seconds": expires_in_seconds,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        resp = self._request_with_retry("post", "/v1/approvals", json=payload)
        return resp.json()

    def get_approval(self, approval_id: str) -> dict:
        """Fetch an approval's current status."""
        resp = self._request_with_retry("get", f"/v1/approvals/{approval_id}")
        return resp.json()

    def list_approvals(
        self,
        status: str | None = None,
        risk_tier: str | None = None,
        data_subject_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List approvals with optional filters."""
        params = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if risk_tier is not None:
            params["risk_tier"] = risk_tier
        if data_subject_id is not None:
            params["data_subject_id"] = data_subject_id
        resp = self._request_with_retry("get", "/v1/approvals", params=params)
        return resp.json()

    def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        raise_on_reject: bool = True,
    ) -> dict:
        """Block until an approval resolves or timeout elapses.

        Polls GET /v1/approvals/{id} every `poll_interval` seconds.
        Returns the approval dict once status is terminal.

        Raises:
          ApprovalTimeoutError: if no decision is made within `timeout` seconds.
          ApprovalRejectedError: if the approval is rejected/expired/cancelled
            and `raise_on_reject` is True.
        """
        deadline = time.time() + timeout
        while True:
            approval = self.get_approval(approval_id)
            status = approval.get("status")
            if status in ("approved", "rejected", "expired", "cancelled"):
                if status != "approved" and raise_on_reject:
                    raise ApprovalRejectedError(approval)
                return approval
            if time.time() >= deadline:
                raise ApprovalTimeoutError(
                    f"Approval {approval_id} did not resolve within {timeout}s "
                    f"(still {status!r})"
                )
            time.sleep(poll_interval)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
