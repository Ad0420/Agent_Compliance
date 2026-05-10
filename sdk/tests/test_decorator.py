"""Unit tests for the @audit decorator."""

from unittest.mock import MagicMock

from vera.decorator import audit, set_default_client


class TestAuditDecorator:
    def test_records_successful_call(self):
        mock_client = MagicMock()

        @audit(action_name="my_action", action_type="computation", client=mock_client)
        def add(a, b):
            return a + b

        result = add(2, 3)
        assert result == 5

        mock_client.enqueue_action.assert_called_once()
        call_kwargs = mock_client.enqueue_action.call_args[1]
        assert call_kwargs["action_name"] == "my_action"
        assert call_kwargs["action_type"] == "computation"
        assert call_kwargs["result"] == "success"
        assert call_kwargs["duration_ms"] is not None
        assert "return_value" in call_kwargs["outcome"]

    def test_records_failure_with_error_message(self):
        mock_client = MagicMock()

        @audit(action_name="failing_op", client=mock_client)
        def fail():
            raise ValueError("test error")

        try:
            fail()
        except ValueError:
            pass

        mock_client.enqueue_action.assert_called_once()
        call_kwargs = mock_client.enqueue_action.call_args[1]
        assert call_kwargs["result"] == "failure"
        assert call_kwargs["error_message"] == "test error"

    def test_no_client_runs_normally(self):
        # Reset global client
        set_default_client(None)

        @audit(action_name="no_client_op")
        def compute():
            return 42

        result = compute()
        assert result == 42

    def test_uses_function_name_as_default(self):
        mock_client = MagicMock()

        @audit(client=mock_client)
        def my_custom_function():
            return "ok"

        my_custom_function()
        call_kwargs = mock_client.enqueue_action.call_args[1]
        assert call_kwargs["action_name"] == "my_custom_function"

    def test_captures_inputs(self):
        mock_client = MagicMock()

        @audit(action_name="input_test", client=mock_client)
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        greet("world", greeting="hi")
        call_kwargs = mock_client.enqueue_action.call_args[1]
        assert "world" in str(call_kwargs["input_data"]["args"])
        assert "hi" in str(call_kwargs["input_data"]["kwargs"])

    def test_default_client(self):
        mock_client = MagicMock()
        set_default_client(mock_client)

        @audit(action_name="default_test")
        def do_work():
            return True

        do_work()
        mock_client.enqueue_action.assert_called_once()

        # Cleanup
        set_default_client(None)
