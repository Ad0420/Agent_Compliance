"""Tests for opt-in redaction on direct ``client.record_action()`` calls.

The ``@audit`` / ``@async_audit`` decorators already redact via the
default ``Redactor`` (PR #82). Direct callers — i.e., users who construct
their own ``input_data`` and call ``client.record_action(...)`` —
historically did not benefit, since the redactor was scoped to the
decorators only.

This change adds an opt-in ``redactor=`` constructor kwarg on both
``VeraClient`` and ``AsyncVeraClient``. When set, every
``record_action`` / ``record_action_batch`` / (async) ``enqueue_action``
call routes the user-supplied JSON-blob fields through the redactor
before sending. Default ``None`` preserves the current pass-through
behaviour — direct callers don't get a silently changed shape.

Redacted fields (user-supplied data):
    input_data, outcome, reasoning, error_message

Preserved fields (operational metadata):
    action_name, action_type, agent_name, agent_version, model_id,
    framework, target_system, target_resource, duration_ms, result, ...
"""

from unittest.mock import MagicMock, AsyncMock

import pytest

from vera import AsyncVeraClient, Redactor, VeraClient


def _make_resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _post_body(client_mock: MagicMock) -> dict:
    """Pull the ``json=`` body out of the most recent post call."""
    _, kwargs = client_mock.post.call_args
    return kwargs["json"]


def _post_headers(client_mock: MagicMock) -> dict:
    _, kwargs = client_mock.post.call_args
    return kwargs["headers"]


# ── Sync: VeraClient.record_action ────────────────────────────────────────


class TestSyncRecordActionNoRedactor:
    def test_no_redactor_sends_raw_input_data(self):
        """Back-compat: no redactor means pass-through verbatim."""
        client = VeraClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="lookup",
            input_data={"ssn": "123-45-6789"},
        )

        body = _post_body(client._client)
        # Raw SSN passes through — no redactor, no redaction.
        assert body["input_data"] == {"ssn": "123-45-6789"}

    def test_no_redactor_sends_raw_error_message(self):
        client = VeraClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="failed_lookup",
            error_message="failed for SSN 123-45-6789",
        )

        body = _post_body(client._client)
        assert body["error_message"] == "failed for SSN 123-45-6789"


class TestSyncRecordActionWithRedactor:
    def test_redactor_redacts_input_data_ssn(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="lookup",
            input_data={"ssn": "123-45-6789"},
        )

        body = _post_body(client._client)
        # The dict key "ssn" hits block_keys and is replaced wholesale.
        assert body["input_data"]["ssn"] == "[REDACTED]"

    def test_redactor_redacts_outcome(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="approve",
            outcome={"summary": "user a@b.co approved"},
        )

        body = _post_body(client._client)
        assert "[REDACTED:email]" in body["outcome"]["summary"]
        assert "a@b.co" not in body["outcome"]["summary"]

    def test_redactor_redacts_reasoning(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="decide",
            reasoning={"note": "subject SSN 123-45-6789 matched watchlist"},
        )

        body = _post_body(client._client)
        assert "[REDACTED:ssn]" in body["reasoning"]["note"]
        assert "123-45-6789" not in body["reasoning"]["note"]

    def test_redactor_redacts_error_message(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="failed_lookup",
            error_message="failed for SSN 123-45-6789",
        )

        body = _post_body(client._client)
        assert "[REDACTED:ssn]" in body["error_message"]
        assert "123-45-6789" not in body["error_message"]

    def test_identifying_fields_preserved(self):
        """Operational metadata must NOT be redacted."""
        client = VeraClient(
            api_key="test",
            agent_name="finance-agent",
            agent_version="1.2.3",
            model_id="gpt-4o",
            framework="custom",
            redactor=Redactor(),
        )
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="transfer_funds",
            action_type="api_call",
            target_system="stripe",
            target_resource="charge:ch_abc",
            duration_ms=42,
            input_data={"amount": 100},
        )

        body = _post_body(client._client)
        # Identifying / operational fields pass through verbatim.
        assert body["action_name"] == "transfer_funds"
        assert body["action_type"] == "api_call"
        assert body["agent_name"] == "finance-agent"
        assert body["agent_version"] == "1.2.3"
        assert body["model_id"] == "gpt-4o"
        assert body["framework"] == "custom"
        assert body["target_system"] == "stripe"
        assert body["target_resource"] == "charge:ch_abc"
        assert body["duration_ms"] == 42

    def test_idempotency_key_present_with_redactor(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="lookup", input_data={"ssn": "123-45-6789"}
        )

        headers = _post_headers(client._client)
        assert "Idempotency-Key" in headers
        # Hex UUID -> 32 chars
        assert len(headers["Idempotency-Key"]) == 32

    def test_custom_block_keys(self):
        """A user-provided block_keys set is honoured for input_data."""
        redactor = Redactor(block_keys={"loan_amount"})
        client = VeraClient(api_key="test", agent_name="a", redactor=redactor)
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "act_1"})

        client.record_action(
            action_name="loan_decision",
            input_data={"loan_amount": 50000, "purpose": "home"},
        )

        body = _post_body(client._client)
        assert body["input_data"]["loan_amount"] == "[REDACTED]"
        # purpose is not in block_keys and has no PII pattern -> passes through
        assert body["input_data"]["purpose"] == "home"


# ── Sync: VeraClient.record_action_batch ──────────────────────────────────


class TestSyncRecordActionBatch:
    def test_batch_no_redactor_sends_raw(self):
        """Back-compat: batch without redactor sends records verbatim."""
        client = VeraClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post.return_value = _make_resp([{"id": "1"}])

        records = [
            {"action_name": "a1", "input_data": {"ssn": "123-45-6789"}},
            {"action_name": "a2", "input_data": {"email": "x@y.com"}},
        ]
        client.record_action_batch(records)

        body = _post_body(client._client)
        assert body["records"][0]["input_data"]["ssn"] == "123-45-6789"
        assert body["records"][1]["input_data"]["email"] == "x@y.com"

    def test_batch_with_redactor_redacts_each_record(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp([{"id": "1"}])

        records = [
            {"action_name": "a1", "input_data": {"ssn": "123-45-6789"}},
            {
                "action_name": "a2",
                "outcome": {"text": "contact x@y.com"},
                "error_message": "lookup failed for 555-12-3456",
            },
        ]
        client.record_action_batch(records)

        body = _post_body(client._client)
        # Per-record redaction.
        assert body["records"][0]["input_data"]["ssn"] == "[REDACTED]"
        assert "[REDACTED:email]" in body["records"][1]["outcome"]["text"]
        assert "x@y.com" not in body["records"][1]["outcome"]["text"]
        # action_name preserved.
        assert body["records"][0]["action_name"] == "a1"
        assert body["records"][1]["action_name"] == "a2"

    def test_batch_idempotency_key_with_redactor(self):
        client = VeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post.return_value = _make_resp([{"id": "1"}])

        client.record_action_batch([{"action_name": "a1"}])
        headers = _post_headers(client._client)
        assert "Idempotency-Key" in headers


# ── Async: AsyncVeraClient.record_action ──────────────────────────────────


class TestAsyncRecordAction:
    @pytest.mark.asyncio
    async def test_no_redactor_sends_raw(self):
        client = AsyncVeraClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp({"id": "act_1"}))

        await client.record_action(
            action_name="lookup", input_data={"ssn": "123-45-6789"}
        )

        body = _post_body(client._client)
        assert body["input_data"] == {"ssn": "123-45-6789"}

    @pytest.mark.asyncio
    async def test_with_redactor_redacts_input_data(self):
        client = AsyncVeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp({"id": "act_1"}))

        await client.record_action(
            action_name="lookup", input_data={"ssn": "123-45-6789"}
        )

        body = _post_body(client._client)
        assert body["input_data"]["ssn"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_with_redactor_redacts_error_message(self):
        client = AsyncVeraClient(api_key="test", agent_name="a", redactor=Redactor())
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp({"id": "act_1"}))

        await client.record_action(
            action_name="failed_lookup",
            error_message="failed for SSN 123-45-6789",
        )

        body = _post_body(client._client)
        assert "[REDACTED:ssn]" in body["error_message"]


# ── Async: AsyncVeraClient.enqueue_action ─────────────────────────────────


class TestAsyncEnqueueAction:
    def test_enqueue_no_redactor_keeps_raw(self):
        """Back-compat: enqueue without a redactor stores the raw payload."""
        client = AsyncVeraClient(api_key="test", agent_name="a")
        client.enqueue_action(
            action_name="lookup", input_data={"ssn": "123-45-6789"}
        )
        queued = client._queue[-1]
        assert queued["input_data"] == {"ssn": "123-45-6789"}
        assert queued["agent_name"] == "a"

    def test_enqueue_with_redactor_redacts_before_queueing(self):
        """Redaction happens at enqueue time so _flush is unchanged."""
        client = AsyncVeraClient(
            api_key="test", agent_name="a", redactor=Redactor()
        )
        client.enqueue_action(
            action_name="lookup",
            input_data={"ssn": "123-45-6789"},
            error_message="contact x@y.com",
        )
        queued = client._queue[-1]
        assert queued["input_data"]["ssn"] == "[REDACTED]"
        assert "[REDACTED:email]" in queued["error_message"]
        # Identifying fields preserved on the queued payload too.
        assert queued["action_name"] == "lookup"
        assert queued["agent_name"] == "a"


# ── Async: AsyncVeraClient.record_action_batch ────────────────────────────


class TestAsyncRecordActionBatch:
    @pytest.mark.asyncio
    async def test_batch_with_redactor(self):
        client = AsyncVeraClient(
            api_key="test", agent_name="a", redactor=Redactor()
        )
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp([{"id": "1"}]))

        await client.record_action_batch(
            [{"action_name": "a1", "input_data": {"ssn": "123-45-6789"}}]
        )

        body = _post_body(client._client)
        assert body["records"][0]["input_data"]["ssn"] == "[REDACTED]"
        assert body["records"][0]["action_name"] == "a1"

    @pytest.mark.asyncio
    async def test_batch_no_redactor_back_compat(self):
        client = AsyncVeraClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp([{"id": "1"}]))

        await client.record_action_batch(
            [{"action_name": "a1", "input_data": {"ssn": "123-45-6789"}}]
        )

        body = _post_body(client._client)
        assert body["records"][0]["input_data"]["ssn"] == "123-45-6789"
