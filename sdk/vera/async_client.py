"""Async client for the Vera API.

Provides non-blocking HTTP calls via httpx.AsyncClient and a background
queue that batches records and sends them without blocking the caller.
"""

import asyncio
import atexit
import logging
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .redaction import Redactor

logger = logging.getLogger("vera.async_client")

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry


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
    ):
        self.api_url = api_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.model_id = model_id
        self.framework = framework
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_queue_size = max_queue_size
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
        """Make an HTTP request with exponential backoff retry."""
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await getattr(self._client, method)(path, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise  # Don't retry client errors (4xx)
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait}s: {e}")
                await asyncio.sleep(wait)
        raise last_exc

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

        Actions are batched and sent periodically. Call start_background_flush()
        to begin the flush loop, and stop_background_flush() to drain and stop.
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
        # Drop oldest if queue is at capacity
        if len(self._queue) >= self._max_queue_size:
            dropped = self._queue.popleft()
            logger.warning(
                f"Queue full ({self._max_queue_size}), dropped oldest action: "
                f"{dropped.get('action_name', 'unknown')}"
            )

        self._queue.append(payload)

        # Flush immediately if batch is full
        if len(self._queue) >= self._batch_size:
            asyncio.create_task(self._flush())

    async def _flush(self) -> None:
        """Send all queued records as a batch."""
        if not self._queue:
            return

        batch = []
        while self._queue and len(batch) < 100:  # API max batch size
            batch.append(self._queue.popleft())

        # Generate one Idempotency-Key per flush call. The same key is
        # reused across the 3-attempt retry loop inside _request_with_retry
        # (so a network-blip retry of THIS batch dedupes server-side).
        # When the batch is re-queued and a later _flush() picks it up,
        # a fresh key is generated — duplicate writes are still possible
        # across that batch boundary, which is the right tradeoff for a
        # fire-and-forget queue.
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        try:
            await self._request_with_retry(
                "post", "/v1/actions/batch", json={"records": batch}, headers=headers
            )
            logger.debug(f"Flushed {len(batch)} queued actions")
        except Exception:
            # Re-queue on failure (prepend to front)
            for item in reversed(batch):
                self._queue.appendleft(item)
            logger.warning(f"Failed to flush {len(batch)} actions, re-queued", exc_info=True)

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
        await self.stop_background_flush()
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
