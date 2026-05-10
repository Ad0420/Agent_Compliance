"""Tests for decorator exception isolation (A2) and empty-client WARN (DX-I).

These cover the contract that:
1. Vera-side failures (network errors, HTTP errors, timeouts, generic
   exceptions raised inside ``record_action`` / ``enqueue_action``) must
   NEVER propagate out of the ``@audit`` / ``@async_audit`` wrapper.
2. Customer-function failures still propagate. When BOTH the customer
   function AND the audit call raise, the customer's exception wins.
3. With no client configured, the decorator emits a single WARNING per
   process (not once per call) and continues to run the wrapped function.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from vera import async_decorator as async_decorator_mod
from vera import decorator as decorator_mod
from vera.async_decorator import async_audit, set_default_async_client
from vera.decorator import audit, set_default_client


# Common audit-side exceptions a real client could raise.
AUDIT_SIDE_EXCEPTIONS = [
    httpx.ConnectError("could not connect"),
    httpx.HTTPStatusError(
        "server error",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(500),
    ),
    httpx.HTTPStatusError(
        "unauthorized",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(401),
    ),
    httpx.TimeoutException("timed out"),
    Exception("generic boom"),
]


# ---------------------------------------------------------------------------
# Sync decorator: A2 — exception isolation
# ---------------------------------------------------------------------------


class TestSyncDecoratorIsolatesAuditExceptions:
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    def test_success_branch_swallows_audit_exception(self, audit_exc, caplog):
        """enqueue_action raising on success must not break the wrapped function."""
        mock_client = MagicMock()
        mock_client.enqueue_action.side_effect = audit_exc

        @audit(action_name="will_succeed", client=mock_client)
        def add(a, b):
            return a + b

        with caplog.at_level(logging.WARNING, logger="vera.decorator"):
            result = add(2, 3)

        assert result == 5
        mock_client.enqueue_action.assert_called_once()
        # Audit failure logged at WARNING.
        assert any(
            record.levelno == logging.WARNING and "will_succeed" in record.getMessage()
            for record in caplog.records
        )

    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    def test_failure_branch_swallows_audit_exception(self, audit_exc, caplog):
        """enqueue_action raising on failure must not mask the customer exception."""
        mock_client = MagicMock()
        mock_client.enqueue_action.side_effect = audit_exc

        @audit(action_name="will_fail", client=mock_client)
        def fail():
            raise ValueError("customer error")

        with caplog.at_level(logging.WARNING, logger="vera.decorator"):
            with pytest.raises(ValueError, match="customer error"):
                fail()

        mock_client.enqueue_action.assert_called_once()
        assert any(
            record.levelno == logging.WARNING and "will_fail" in record.getMessage()
            for record in caplog.records
        )

    def test_customer_exception_wins_over_audit_exception(self):
        """If both raise, the customer's exception is what propagates."""
        mock_client = MagicMock()
        mock_client.enqueue_action.side_effect = httpx.ConnectError("audit broke")

        @audit(action_name="both_raise", client=mock_client)
        def fail():
            raise ValueError("customer error")

        with pytest.raises(ValueError, match="customer error"):
            fail()


# ---------------------------------------------------------------------------
# Sync decorator: DX-I — empty-client WARN (once per process)
# ---------------------------------------------------------------------------


class TestSyncEmptyClientWarning:
    def setup_method(self):
        set_default_client(None)
        decorator_mod._reset_empty_client_warning()

    def teardown_method(self):
        set_default_client(None)
        decorator_mod._reset_empty_client_warning()

    def test_first_call_emits_warning_and_runs_function(self, caplog):
        @audit(action_name="no_client_op")
        def compute():
            return 42

        with caplog.at_level(logging.WARNING, logger="vera.decorator"):
            result = compute()

        assert result == 42
        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1

    def test_subsequent_calls_do_not_spam(self, caplog):
        @audit(action_name="no_client_op")
        def compute():
            return 42

        with caplog.at_level(logging.WARNING, logger="vera.decorator"):
            for _ in range(5):
                compute()

        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1


# ---------------------------------------------------------------------------
# Async decorator: A2 — exception isolation (async wrapper)
# ---------------------------------------------------------------------------


class TestAsyncDecoratorIsolatesAuditExceptions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    async def test_async_success_blocking_swallows(self, audit_exc, caplog):
        """blocking=True path: record_action raises, wrapper still returns value."""
        mock_client = MagicMock()
        mock_client.record_action = AsyncMock(side_effect=audit_exc)

        @async_audit(action_name="async_succ", client=mock_client, blocking=True)
        async def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            result = await work()

        assert result == "ok"
        mock_client.record_action.assert_awaited_once()
        assert any(
            r.levelno == logging.WARNING and "async_succ" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    async def test_async_success_nonblocking_swallows(self, audit_exc, caplog):
        """blocking=False path: enqueue_action raises, wrapper still returns value."""
        mock_client = MagicMock()
        mock_client.enqueue_action = MagicMock(side_effect=audit_exc)

        @async_audit(action_name="async_succ_nb", client=mock_client, blocking=False)
        async def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            result = await work()

        assert result == "ok"
        mock_client.enqueue_action.assert_called_once()
        assert any(
            r.levelno == logging.WARNING and "async_succ_nb" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    async def test_async_failure_blocking_swallows_audit(self, audit_exc, caplog):
        mock_client = MagicMock()
        mock_client.record_action = AsyncMock(side_effect=audit_exc)

        @async_audit(action_name="async_fail", client=mock_client, blocking=True)
        async def fail():
            raise ValueError("customer error")

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            with pytest.raises(ValueError, match="customer error"):
                await fail()

        mock_client.record_action.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    async def test_async_failure_nonblocking_swallows_audit(self, audit_exc, caplog):
        mock_client = MagicMock()
        mock_client.enqueue_action = MagicMock(side_effect=audit_exc)

        @async_audit(action_name="async_fail_nb", client=mock_client, blocking=False)
        async def fail():
            raise ValueError("customer error")

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            with pytest.raises(ValueError, match="customer error"):
                await fail()

        mock_client.enqueue_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_customer_exception_wins(self):
        mock_client = MagicMock()
        mock_client.record_action = AsyncMock(side_effect=httpx.ConnectError("audit broke"))

        @async_audit(action_name="async_both", client=mock_client, blocking=True)
        async def fail():
            raise ValueError("customer error")

        with pytest.raises(ValueError, match="customer error"):
            await fail()


# ---------------------------------------------------------------------------
# Async decorator wrapping a SYNC function (sync_wrapper path)
# ---------------------------------------------------------------------------


class TestAsyncDecoratorSyncWrapperIsolatesAuditExceptions:
    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    def test_sync_wrapper_success_swallows(self, audit_exc, caplog):
        mock_client = MagicMock()
        mock_client.enqueue_action = MagicMock(side_effect=audit_exc)

        @async_audit(action_name="sync_wrap_succ", client=mock_client)
        def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            result = work()

        assert result == "ok"
        mock_client.enqueue_action.assert_called_once()
        assert any(
            r.levelno == logging.WARNING and "sync_wrap_succ" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.parametrize("audit_exc", AUDIT_SIDE_EXCEPTIONS)
    def test_sync_wrapper_failure_swallows(self, audit_exc, caplog):
        mock_client = MagicMock()
        mock_client.enqueue_action = MagicMock(side_effect=audit_exc)

        @async_audit(action_name="sync_wrap_fail", client=mock_client)
        def fail():
            raise ValueError("customer error")

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            with pytest.raises(ValueError, match="customer error"):
                fail()

        mock_client.enqueue_action.assert_called_once()

    def test_sync_wrapper_customer_exception_wins(self):
        mock_client = MagicMock()
        mock_client.enqueue_action = MagicMock(side_effect=httpx.ConnectError("audit broke"))

        @async_audit(action_name="sync_wrap_both", client=mock_client)
        def fail():
            raise ValueError("customer error")

        with pytest.raises(ValueError, match="customer error"):
            fail()


# ---------------------------------------------------------------------------
# Async decorator: DX-I — empty-client WARN (once per process)
# ---------------------------------------------------------------------------


class TestAsyncEmptyClientWarning:
    def setup_method(self):
        set_default_async_client(None)
        async_decorator_mod._reset_empty_client_warning()

    def teardown_method(self):
        set_default_async_client(None)
        async_decorator_mod._reset_empty_client_warning()

    @pytest.mark.asyncio
    async def test_async_first_call_warns_and_runs(self, caplog):
        @async_audit(action_name="async_no_client")
        async def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            result = await work()

        assert result == "ok"
        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1

    @pytest.mark.asyncio
    async def test_async_subsequent_calls_do_not_spam(self, caplog):
        @async_audit(action_name="async_no_client")
        async def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            for _ in range(5):
                await work()

        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1

    def test_sync_wrapper_first_call_warns_and_runs(self, caplog):
        @async_audit(action_name="sync_wrap_no_client")
        def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            result = work()

        assert result == "ok"
        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1

    def test_sync_wrapper_subsequent_calls_do_not_spam(self, caplog):
        @async_audit(action_name="sync_wrap_no_client")
        def work():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="vera.async_decorator"):
            for _ in range(5):
                work()

        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "no Vera client is configured" in r.getMessage()
        ]
        assert len(warns) == 1
