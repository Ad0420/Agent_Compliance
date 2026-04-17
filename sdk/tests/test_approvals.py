"""Tests for the HITL approval SDK methods (sync and async)."""

from unittest.mock import MagicMock, AsyncMock

import pytest

from actionledger import (
    ActionLedgerClient,
    AsyncActionLedgerClient,
    ApprovalRejectedError,
    ApprovalTimeoutError,
)


def _make_resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ── Sync client ───────────────────────────────────────────────────────────


class TestSyncApprovals:
    def test_request_approval_sends_correct_payload(self):
        client = ActionLedgerClient(api_key="test", agent_name="dpo-agent")
        client._client = MagicMock()
        client._client.post.return_value = _make_resp(
            {"id": "app_1", "status": "pending"}
        )

        result = client.request_approval(
            action_name="delete_user",
            risk_tier="critical",
            action_summary="Hard-delete user record",
            data_subject_id="user_42",
            context={"table": "users"},
            approvers_required=2,
            expires_in_seconds=3600,
        )

        assert result == {"id": "app_1", "status": "pending"}
        client._client.post.assert_called_once()
        _, kwargs = client._client.post.call_args
        body = kwargs["json"]
        assert body["agent_name"] == "dpo-agent"
        assert body["action_name"] == "delete_user"
        assert body["risk_tier"] == "critical"
        assert body["approvers_required"] == 2
        assert body["expires_in_seconds"] == 3600
        assert body["context"] == {"table": "users"}

    def test_request_approval_strips_none_fields(self):
        client = ActionLedgerClient(api_key="test", agent_name="a")
        client._client = MagicMock()
        client._client.post.return_value = _make_resp({"id": "a1", "status": "pending"})

        client.request_approval(action_name="act")

        _, kwargs = client._client.post.call_args
        body = kwargs["json"]
        # None values should not be serialized
        assert "action_summary" not in body
        assert "data_subject_id" not in body
        assert "expires_in_seconds" not in body

    def test_get_approval(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.return_value = _make_resp(
            {"id": "a1", "status": "approved"}
        )

        result = client.get_approval("a1")
        assert result["status"] == "approved"
        client._client.get.assert_called_with("/v1/approvals/a1")

    def test_list_approvals_passes_filters(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.return_value = _make_resp({"approvals": [], "total": 0})

        client.list_approvals(status="pending", risk_tier="high", limit=10)

        _, kwargs = client._client.get.call_args
        params = kwargs["params"]
        assert params["status"] == "pending"
        assert params["risk_tier"] == "high"
        assert params["limit"] == 10

    def test_wait_for_approval_returns_on_approved(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.side_effect = [
            _make_resp({"id": "a1", "status": "pending"}),
            _make_resp({"id": "a1", "status": "approved"}),
        ]

        result = client.wait_for_approval("a1", timeout=5, poll_interval=0)
        assert result["status"] == "approved"
        assert client._client.get.call_count == 2

    def test_wait_for_approval_raises_on_reject(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.return_value = _make_resp(
            {"id": "a1", "status": "rejected"}
        )

        with pytest.raises(ApprovalRejectedError) as exc_info:
            client.wait_for_approval("a1", timeout=1, poll_interval=0)
        assert exc_info.value.approval["status"] == "rejected"

    def test_wait_for_approval_returns_rejection_when_raise_disabled(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.return_value = _make_resp(
            {"id": "a1", "status": "rejected"}
        )

        result = client.wait_for_approval(
            "a1", timeout=1, poll_interval=0, raise_on_reject=False
        )
        assert result["status"] == "rejected"

    def test_wait_for_approval_timeout(self):
        client = ActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get.return_value = _make_resp(
            {"id": "a1", "status": "pending"}
        )

        with pytest.raises(ApprovalTimeoutError):
            client.wait_for_approval("a1", timeout=0.01, poll_interval=0.005)


# ── Async client ──────────────────────────────────────────────────────────


class TestAsyncApprovals:
    @pytest.mark.asyncio
    async def test_request_approval(self):
        client = AsyncActionLedgerClient(api_key="test", agent_name="async-agent")
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=_make_resp(
            {"id": "a1", "status": "pending"}
        ))

        result = await client.request_approval(
            action_name="export_data", risk_tier="high"
        )
        assert result["id"] == "a1"
        _, kwargs = client._client.post.call_args
        assert kwargs["json"]["action_name"] == "export_data"
        assert kwargs["json"]["risk_tier"] == "high"
        assert kwargs["json"]["agent_name"] == "async-agent"

    @pytest.mark.asyncio
    async def test_wait_for_approval_async_approved(self):
        client = AsyncActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get = AsyncMock(
            side_effect=[
                _make_resp({"id": "a1", "status": "pending"}),
                _make_resp({"id": "a1", "status": "approved"}),
            ]
        )

        result = await client.wait_for_approval("a1", timeout=5, poll_interval=0)
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_wait_for_approval_async_rejected(self):
        client = AsyncActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get = AsyncMock(
            return_value=_make_resp({"id": "a1", "status": "rejected"})
        )

        with pytest.raises(ApprovalRejectedError):
            await client.wait_for_approval("a1", timeout=1, poll_interval=0)

    @pytest.mark.asyncio
    async def test_wait_for_approval_async_timeout(self):
        client = AsyncActionLedgerClient(api_key="test")
        client._client = MagicMock()
        client._client.get = AsyncMock(
            return_value=_make_resp({"id": "a1", "status": "pending"})
        )

        with pytest.raises(ApprovalTimeoutError):
            await client.wait_for_approval("a1", timeout=0.01, poll_interval=0.005)
