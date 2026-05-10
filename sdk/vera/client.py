import logging
import time
import uuid
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .redaction import Redactor

logger = logging.getLogger("vera.client")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5


class ApprovalTimeoutError(Exception):
    """Raised when wait_for_approval times out before a human decides."""


class ApprovalRejectedError(Exception):
    """Raised when an approval is rejected, expired, or cancelled."""

    def __init__(self, approval: dict):
        self.approval = approval
        status = approval.get("status", "unknown")
        super().__init__(f"Approval {approval.get('id')} resolved as '{status}'")


class VeraClient:
    """Synchronous client for the Vera API."""

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
    ):
        self.api_url = api_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.model_id = model_id
        self.framework = framework
        # Opt-in redaction. When set, record_action / record_action_batch
        # routes input_data, outcome, reasoning, and error_message through
        # the redactor before sending. Default None preserves the current
        # pass-through behaviour for direct callers who construct their
        # own payloads — opt-in by design (no surprises).
        self._redactor = redactor
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

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

    def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with exponential backoff retry."""
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = getattr(self._client, method)(path, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise  # Don't retry client errors (4xx)
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait}s: {e}")
                time.sleep(wait)
        raise last_exc

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
        """Record a single action."""
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
        """Record a batch of actions."""
        if self._redactor is not None:
            records = [self._redact_payload_fields(r) for r in records]
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        resp = self._request_with_retry(
            "post", "/v1/actions/batch", json={"records": records}, headers=headers
        )
        return resp.json()

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

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
