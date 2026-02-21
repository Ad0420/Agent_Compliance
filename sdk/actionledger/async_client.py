"""Async client for the Action Ledger API.

Provides non-blocking HTTP calls via httpx.AsyncClient and a background
queue that batches records and sends them without blocking the caller.
"""

import asyncio
import atexit
import logging
import time
from collections import deque

import httpx

logger = logging.getLogger("actionledger.async_client")

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry


class AsyncActionLedgerClient:
    """Async client for the Action Ledger API."""

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str = "",
        agent_name: str = "default-agent",
        agent_version: str | None = None,
        model_id: str | None = None,
        framework: str | None = None,
        timeout: float = 30.0,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
    ):
        self.api_url = api_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.model_id = model_id
        self.framework = framework
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_queue_size = max_queue_size
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._queue: deque[dict] = deque()
        self._flush_task: asyncio.Task | None = None

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
        resp = await self._request_with_retry("post", "/v1/actions", json=payload)
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

        try:
            await self._request_with_retry(
                "post", "/v1/actions/batch", json={"records": batch}
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
        resp = await self._request_with_retry(
            "post", "/v1/actions/batch", json={"records": records}
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

    async def close(self):
        await self.stop_background_flush()
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
