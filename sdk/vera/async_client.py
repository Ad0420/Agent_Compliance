"""Async client for the Vera API.

Provides non-blocking HTTP calls via httpx.AsyncClient and a background
queue that batches records and sends them without blocking the caller.

Failure classification (workstream A8) and branded exception wrapping are
shared with the synchronous :class:`vera.client.VeraClient` — see
:func:`vera.client.wrap_httpx_error` and
:meth:`vera.client.VeraClient._is_permanent_failure`.
"""

import asyncio
import atexit
import logging
import random
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING

import httpx

from .client import wrap_httpx_error
from .errors import (
    VeraAuthError,
    VeraValidationError,
)

if TYPE_CHECKING:
    from .redaction import Redactor

logger = logging.getLogger("vera.async_client")

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry

# Maximum batch size the server accepts per /v1/actions/batch call.
_API_MAX_BATCH = 100


class AsyncVeraClient:
    """Async client for the Vera API."""

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str = "",
        agent_name: str = "default-agent",
        agent_version: str | None = None,
        model_id: str | None = None,
        framework: str | None = None,
        timeout: float = 5.0,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
        redactor: "Redactor | None" = None,
        circuit_breaker_threshold: int = 5,
        requeue_max_attempts: int = 10,
    ):
        self.api_url = api_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.model_id = model_id
        self.framework = framework
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_queue_size = max_queue_size
        self._circuit_breaker_threshold = max(1, circuit_breaker_threshold)
        self._requeue_max_attempts = max(1, requeue_max_attempts)
        # Opt-in redaction. When set, record_action / record_action_batch /
        # enqueue_action route input_data, outcome, reasoning, and
        # error_message through the redactor before sending. Default None
        # preserves the current pass-through behaviour for direct callers.
        self._redactor = redactor
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._queue: deque[dict] = deque()
        self._flush_task: asyncio.Task | None = None
        # Drop-oldest WARN throttling — a runaway producer can otherwise spam
        # logs once per overflowed enqueue.
        self._overflow_drops_since_warn = 0
        self._overflow_last_warn_at: float = 0.0
        self._overflow_warn_min_interval = 1.0  # seconds
        # Circuit-breaker bookkeeping (workstream A8).
        self._consecutive_failures = 0
        self._breaker_open_until: float = 0.0
        # Serialize ``_flush`` calls. Both the periodic flush_loop and the
        # on-overflow ``create_task`` from ``enqueue_action`` can race into
        # ``_flush`` concurrently and double-popleft from the deque, sending
        # interleaved batches and losing records. The lock is constructed
        # lazily because ``asyncio.Lock()`` binds to the current loop —
        # constructing it in __init__ when no loop is running raises in
        # certain pytest-asyncio fixture flows.
        self._flush_lock: asyncio.Lock | None = None
        # Once-per-process WARN flag for the sync-context-no-loop branch in
        # ``enqueue_action``.
        self._sync_no_loop_warned = False

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

    async def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with exponential backoff retry.

        Translates terminal failures into :mod:`vera.errors` types so callers
        can ``except VeraError`` without depending on httpx internals.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await getattr(self._client, method)(path, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code < 500 and e.response.status_code != 429:
                    raise wrap_httpx_error(e) from e
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                    e,
                )
                await asyncio.sleep(wait)
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
                await asyncio.sleep(wait)
        assert last_exc is not None
        raise wrap_httpx_error(last_exc) from last_exc

    async def record_action(
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
        """Record a single action (makes HTTP call immediately)."""
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
        # The retry loop reuses kwargs across attempts so the same
        # Idempotency-Key is sent on retries.
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        resp = await self._request_with_retry(
            "post", "/v1/actions", json=payload, headers=headers
        )
        return resp.json()

    def enqueue_action(self, **kwargs) -> None:
        """Add an action to the background queue (non-blocking).

        Actions are batched and sent periodically. Call
        :meth:`start_background_flush` to begin the flush loop, and
        :meth:`stop_background_flush` to drain and stop.

        Sync-context-no-loop behavior
        ------------------------------
        When called from a sync context with no running event loop (e.g.
        from a plain function, or from
        :func:`vera.async_decorator.async_audit`'s sync-wrapper branch),
        records are buffered in memory but **no flush is scheduled** —
        ``asyncio.create_task`` requires a running loop. Records remain on
        the queue and will be sent by the next flush triggered from an
        async caller, by ``start_background_flush``, or by an explicit
        ``await client.stop_background_flush()`` / ``await client.close()``.

        Callers should ensure a running event loop exists at flush time, or
        use :class:`vera.client.VeraClient` (sync) for fully sync codepaths.
        Prior to this change, the no-loop path raised ``RuntimeError``,
        which the decorator's broad exception handler swallowed silently —
        records never made it to the queue **or** to the wire.
        """
        payload = {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "model_id": self.model_id,
            "framework": self.framework,
            **kwargs,
        }
        # Redact at enqueue time so _flush sends already-redacted payloads
        # — no double work on the flush path.
        if self._redactor is not None:
            payload = self._redact_payload_fields(payload)
        # Internal bookkeeping field — stripped before POST.
        payload.setdefault("_requeue_count", 0)
        # Idempotency: stable per-record key, reused across re-queues so the
        # server can dedupe a record that survived a network blip.
        payload.setdefault("_idempotency_key", uuid.uuid4().hex)
        # Drop oldest if queue is at capacity
        if len(self._queue) >= self._max_queue_size:
            dropped = self._queue.popleft()
            self._record_overflow_drop(dropped)

        self._queue.append(payload)

        # Flush immediately if batch is full. ``asyncio.create_task`` raises
        # ``RuntimeError`` when no loop is running — the original
        # implementation hit this when called from sync code (the
        # ``async_audit`` sync-wrapper branch) and the decorator's broad
        # ``except Exception`` swallowed it, silently dropping every audit
        # record. Now we buffer in the queue regardless; the next flush
        # from an async caller will pick the records up.
        if len(self._queue) >= self._batch_size:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Sync caller, no loop — keep records queued. Warn once
                # per process so customers notice the misuse without log
                # spam on every audited call.
                if not self._sync_no_loop_warned:
                    self._sync_no_loop_warned = True
                    logger.warning(
                        "AsyncVeraClient.enqueue_action called from sync "
                        "context with no running event loop — %d records "
                        "queued, awaiting next async caller. Consider "
                        "using vera.VeraClient (sync) for sync codepaths.",
                        len(self._queue),
                    )
            else:
                loop.create_task(self._flush())

    def _record_overflow_drop(self, dropped: dict | None) -> None:
        """Throttled WARN log on queue overflow."""
        action_name = (dropped or {}).get("action_name", "unknown")
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

    @staticmethod
    def _strip_internal_fields(payload: dict) -> dict:
        """Return a copy of ``payload`` with internal bookkeeping removed.

        Strips every leading-underscore key so private fields (e.g.
        ``_requeue_count``, ``_idempotency_key``) never reach the wire.
        """
        if not any(k.startswith("_") for k in payload):
            return payload
        return {k: v for k, v in payload.items() if not k.startswith("_")}

    @staticmethod
    def _is_permanent_failure(exc: BaseException) -> bool:
        """Return True if the failure should not be retried (workstream A8)."""
        if isinstance(exc, (VeraAuthError, VeraValidationError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return 400 <= status < 500 and status != 429
        return False

    async def _flush(self) -> None:
        """Send queued records as a batch with poison-batch handling.

        Serialised by ``self._flush_lock`` — the periodic flush_loop and
        the on-overflow ``create_task`` from ``enqueue_action`` can both
        race into this method concurrently. Without the lock, both tasks
        ``popleft`` from the same deque, splitting the batch, double-POSTing
        records (because each task sends what it popped), and risking lost
        records if one task fails and the other succeeds.
        """
        # Lazily construct the lock so we bind it to the running loop. Done
        # inside the method (not __init__) because pytest-asyncio creates
        # one loop per test and an asyncio.Lock built against an old loop
        # raises ``RuntimeError: ... bound to a different event loop``.
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()

        async with self._flush_lock:
            if not self._queue:
                return

            # Circuit breaker — pause flushing for the cool-down window.
            if time.monotonic() < self._breaker_open_until:
                return

            batch: list[dict] = []
            while self._queue and len(batch) < _API_MAX_BATCH:
                batch.append(self._queue.popleft())

            records = [self._strip_internal_fields(r) for r in batch]

            # Use the first record's idempotency key (set at enqueue time).
            # The key survives re-queues across batch boundaries, so a
            # network-blip retry of the same record dedupes server-side.
            # Falls back to a fresh uuid for legacy items that lack the
            # private key (e.g. tests that hand-build queue items).
            headers = {"Idempotency-Key": self._batch_idempotency_key(batch)}
            try:
                await self._request_with_retry(
                    "post",
                    "/v1/actions/batch",
                    json={"records": records},
                    headers=headers,
                )
                self._consecutive_failures = 0
                self._breaker_open_until = 0.0
                logger.debug("Flushed %d queued actions", len(batch))
            except Exception as exc:  # noqa: BLE001 — classified below
                self._handle_flush_failure(batch, exc)

    @staticmethod
    def _batch_idempotency_key(batch: list[dict]) -> str:
        """Return a stable Idempotency-Key for ``batch``.

        Uses the first record's ``_idempotency_key`` so a re-queued record
        keeps its key across the batch boundary. Falls back to a fresh uuid
        for legacy items.
        """
        if batch:
            key = batch[0].get("_idempotency_key")
            if isinstance(key, str) and key:
                return key
        return uuid.uuid4().hex

    def _handle_flush_failure(self, batch: list[dict], exc: BaseException) -> None:
        """Apply A8 poison-batch classification to a failed batch."""
        permanent = self._is_permanent_failure(exc)
        if permanent:
            cls_name = type(exc).__name__
            logger.error(
                "vera.async_client: dropping %d records due to %s: %s. "
                "Records WILL NOT be retried.",
                len(batch),
                cls_name,
                exc,
            )
            self._consecutive_failures += 1
        else:
            self._consecutive_failures += 1
            requeued = 0
            dropped_for_age = 0
            # Re-queue at the front so retried items come out before fresh
            # ones — same ordering as the previous implementation.
            for item in reversed(batch):
                count = int(item.get("_requeue_count", 0)) + 1
                if count > self._requeue_max_attempts:
                    dropped_for_age += 1
                    continue
                item["_requeue_count"] = count
                if len(self._queue) >= self._max_queue_size:
                    self._record_overflow_drop(item)
                    continue
                self._queue.appendleft(item)
                requeued += 1
            if dropped_for_age:
                logger.warning(
                    "vera.async_client: dropped %d records after %d "
                    "re-queue attempts (poison-record cap).",
                    dropped_for_age,
                    self._requeue_max_attempts,
                )
            logger.warning(
                "vera.async_client: flush failed (%s). Re-queued %d records; %d dropped at cap.",
                exc,
                requeued,
                dropped_for_age,
            )

        if self._consecutive_failures >= self._circuit_breaker_threshold:
            over = self._consecutive_failures - self._circuit_breaker_threshold
            cooldown = min(60.0, RETRY_BACKOFF_BASE * (2 ** over))
            jitter = cooldown * 0.1 * random.random()
            self._breaker_open_until = time.monotonic() + cooldown + jitter
            logger.warning(
                "vera.async_client: circuit breaker open for %.2fs after %d consecutive failures.",
                cooldown + jitter,
                self._consecutive_failures,
            )

    async def _flush_loop(self) -> None:
        """Periodically flush the queue."""
        while True:
            await asyncio.sleep(self._flush_interval)
            await self._flush()

    def start_background_flush(self) -> None:
        """Start the background flush loop."""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())
            atexit.register(self._atexit_warning)

    def _atexit_warning(self) -> None:
        """Warn at process exit if unflushed items remain."""
        pending = len(self._queue)
        if pending > 0:
            logger.warning(
                f"Process exiting with {pending} unflushed actions in queue. "
                f"Call 'await client.stop_background_flush()' before shutdown."
            )

    async def stop_background_flush(self) -> None:
        """Stop the flush loop and drain remaining items."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final drain
        while self._queue:
            await self._flush()

    async def flush(self, timeout: float = 30.0) -> None:
        """Block until the queue is empty, or ``timeout`` seconds elapse.

        Async parity with :meth:`vera.client.VeraClient.flush`. Useful in
        test / script / serverless contexts where you must ensure records
        reach Vera before the caller proceeds. The background flush task
        is left running — call :meth:`close` for full teardown.

        Times out silently with a WARN if records remain.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(0.0, timeout)
        while loop.time() < deadline:
            if not self._queue:
                return
            await self._flush()
            if not self._queue:
                return
            await asyncio.sleep(0.05)
        if self._queue:
            logger.warning(
                "vera.async_client: flush() timed out after %.1fs with %d records still queued.",
                timeout,
                len(self._queue),
            )

    async def record_action_batch(self, records: list[dict]) -> list[dict]:
        if self._redactor is not None:
            records = [self._redact_payload_fields(r) for r in records]
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        resp = await self._request_with_retry(
            "post", "/v1/actions/batch", json={"records": records}, headers=headers
        )
        return resp.json()

    async def query_actions(self, **filters) -> dict:
        resp = await self._request_with_retry("get", "/v1/actions", params=filters)
        return resp.json()

    async def verify_chain(self) -> dict:
        resp = await self._request_with_retry("get", "/v1/verify")
        return resp.json()

    async def register_agent(self, name: str, description: str | None = None, metadata: dict | None = None) -> dict:
        payload = {"name": name, "description": description, "metadata": metadata or {}}
        resp = await self._request_with_retry("post", "/v1/agents", json=payload)
        return resp.json()

    async def create_checkpoint(self) -> dict:
        resp = await self._request_with_retry("post", "/v1/verify/checkpoints")
        return resp.json()

    async def verify_checkpoints(self) -> dict:
        resp = await self._request_with_retry("post", "/v1/verify/checkpoints/verify")
        return resp.json()

    # ── Human-in-the-Loop approvals ───────────────────────────────────────

    async def request_approval(
        self,
        action_name: str,
        risk_tier: str = "high",
        action_summary: str | None = None,
        data_subject_id: str | None = None,
        context: dict | None = None,
        approvers_required: int = 1,
        expires_in_seconds: int | None = None,
    ) -> dict:
        """Ask a human to approve an action before the agent takes it."""
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
        resp = await self._request_with_retry("post", "/v1/approvals", json=payload)
        return resp.json()

    async def get_approval(self, approval_id: str) -> dict:
        resp = await self._request_with_retry("get", f"/v1/approvals/{approval_id}")
        return resp.json()

    async def list_approvals(
        self,
        status: str | None = None,
        risk_tier: str | None = None,
        data_subject_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        params = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if risk_tier is not None:
            params["risk_tier"] = risk_tier
        if data_subject_id is not None:
            params["data_subject_id"] = data_subject_id
        resp = await self._request_with_retry("get", "/v1/approvals", params=params)
        return resp.json()

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        raise_on_reject: bool = True,
    ) -> dict:
        """Await approval resolution. Raises ApprovalTimeoutError on timeout."""
        from .client import ApprovalRejectedError, ApprovalTimeoutError

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            approval = await self.get_approval(approval_id)
            status = approval.get("status")
            if status in ("approved", "rejected", "expired", "cancelled"):
                if status != "approved" and raise_on_reject:
                    raise ApprovalRejectedError(approval)
                return approval
            if loop.time() >= deadline:
                raise ApprovalTimeoutError(
                    f"Approval {approval_id} did not resolve within {timeout}s "
                    f"(still {status!r})"
                )
            await asyncio.sleep(poll_interval)

    async def close(self):
        """Drain the queue, stop the flush task, close the HTTP client.

        MUST be awaited explicitly before process exit. ``atexit`` cannot
        reliably run async cleanup — ``asyncio.run(self.close())`` from an
        atexit hook fights the running loop and may hang or no-op
        depending on the runtime. Records remaining in the queue at process
        exit are logged via the ``_atexit_warning`` hook but are **not**
        flushed. If you can't guarantee an explicit close (e.g. AWS Lambda
        cold-start path), use :class:`vera.client.VeraClient` (sync)
        instead — the sync client's atexit drain is reliable.
        """
        await self.stop_background_flush()
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
