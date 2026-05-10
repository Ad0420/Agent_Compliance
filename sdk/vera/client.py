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
    VeraNetworkError,
    VeraRateLimitError,
    VeraServerError,
    VeraTimeoutError,
    VeraValidationError,
)

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

    Falls through (returns the original exception unchanged) for unrecognised
    inputs so callers can re-raise without losing information.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        rid = _request_id_from(exc)
        message = f"HTTP {status} from {exc.request.method} {exc.request.url}"
        if status in (401, 403):
            return VeraAuthError(message, request_id=rid, status_code=status)
        if status == 429:
            return VeraRateLimitError(message, request_id=rid, status_code=status)
        if 500 <= status < 600:
            return VeraServerError(message, request_id=rid, status_code=status)
        if 400 <= status < 500:
            return VeraValidationError(message, request_id=rid, status_code=status)
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return VeraTimeoutError(str(exc) or "request timed out")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return VeraNetworkError(str(exc) or "network failure")
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
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

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

        # Register os.register_at_fork to reset state proactively in children.
        # Some platforms / interpreters (Windows, very old CPython) lack it.
        if hasattr(os, "register_at_fork"):
            try:
                os.register_at_fork(after_in_child=self._after_in_child)
            except Exception:  # pragma: no cover — extremely defensive
                pass

        # Register atexit drain. We register unconditionally so that a client
        # which only ever called record_action() still has its (empty) hook
        # cleared on close().
        atexit.register(self._atexit_drain)

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
        """
        # Fork-safety check first — cheap fast path when pid hasn't changed.
        if self._owner_pid != os.getpid():
            self._init_runtime_state()

        if _gevent_threading_patched():
            _warn_gevent_once()

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

        assert self._queue is not None  # set by _init_runtime_state

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            # Drop oldest then retry once.
            try:
                dropped = self._queue.get_nowait()
            except queue.Empty:  # pragma: no cover — race
                dropped = None
            self._record_overflow_drop(dropped)
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
            self._queue = queue.Queue(maxsize=self._max_queue_size)
            self._wakeup = threading.Event()
            self._stop_event = threading.Event()
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            self._owner_pid = current_pid
            self._closed = False
            t = threading.Thread(
                target=self._worker_loop,
                name="vera-flush",
                daemon=True,
            )
            self._worker = t
            t.start()

    def _after_in_child(self) -> None:
        """Run inside the child after :func:`os.fork`.

        Discard the parent's queue + thread (they don't exist here) and let
        :meth:`_init_runtime_state` recreate everything on next use.
        """
        # We deliberately do NOT take ``_state_lock`` here — fork() inside a
        # locked section is what creates the badness in the first place.
        self._queue = None
        self._wakeup = None
        self._stop_event = None
        self._worker = None
        self._owner_pid = None
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._closed = False
        # Reset the lock object — children don't inherit a useful state.
        self._state_lock = threading.Lock()
        self._overflow_warn_lock = threading.Lock()
        self._overflow_drops_since_warn = 0
        self._overflow_last_warn_at = 0.0

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
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        try:
            self._request_with_retry(
                "post",
                "/v1/actions/batch",
                json={"records": records},
                headers=headers,
            )
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            logger.debug("Flushed %d queued actions", len(batch))
        except Exception as exc:  # noqa: BLE001 — we classify below
            self._handle_flush_failure(batch, exc)

    @staticmethod
    def _strip_internal_fields(payload: dict) -> dict:
        """Return a copy of ``payload`` with internal bookkeeping removed."""
        if "_requeue_count" not in payload:
            return payload
        clean = dict(payload)
        clean.pop("_requeue_count", None)
        return clean

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

        # Open the breaker after threshold consecutive failures. Backoff
        # grows exponentially up to 60s.
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            over = self._consecutive_failures - self._circuit_breaker_threshold
            cooldown = min(60.0, RETRY_BACKOFF_BASE * (2 ** over))
            jitter = cooldown * 0.1 * random.random()
            self._breaker_open_until = time.monotonic() + cooldown + jitter
            logger.warning(
                "vera.client: circuit breaker open for %.2fs after %d consecutive failures.",
                cooldown + jitter,
                self._consecutive_failures,
            )

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
        """Synchronously drain the queue from the caller, bounded by ``deadline``."""
        if self._queue is None:
            return
        while not self._queue.empty() and time.monotonic() < deadline:
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
            headers = {"Idempotency-Key": uuid.uuid4().hex}
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
