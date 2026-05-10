"""Tests for the internal `vera._deprecation` utility module."""

from __future__ import annotations

import warnings

import pytest

from vera._deprecation import deprecated, deprecated_once, _warned_once


@pytest.fixture(autouse=True)
def _clear_warned_once_state():
    """Ensure the process-global de-dupe set doesn't leak across tests."""
    _warned_once.clear()
    yield
    _warned_once.clear()


def test_deprecated_emits_deprecation_warning():
    @deprecated(reason="testing", removed_in="0.5.0")
    def old_func():
        return 42

    with pytest.warns(DeprecationWarning) as record:
        result = old_func()

    assert result == 42
    assert len(record) == 1
    msg = str(record[0].message)
    assert "old_func" in msg
    assert "testing" in msg
    assert "0.5.0" in msg


def test_deprecated_includes_replacement_in_message():
    @deprecated(
        reason="legacy path",
        removed_in="0.6.0",
        replacement="new_func()",
    )
    def stale_func():
        return "ok"

    with pytest.warns(DeprecationWarning) as record:
        stale_func()

    msg = str(record[0].message)
    assert "stale_func" in msg
    assert "legacy path" in msg
    assert "0.6.0" in msg
    assert "new_func()" in msg


def test_deprecated_omits_replacement_when_not_supplied():
    @deprecated(reason="just gone", removed_in="0.7.0")
    def gone_func():
        return None

    with pytest.warns(DeprecationWarning) as record:
        gone_func()

    msg = str(record[0].message)
    assert "Use " not in msg
    assert "instead" not in msg


def test_deprecated_preserves_function_metadata():
    @deprecated(reason="x", removed_in="0.5.0")
    def documented():
        """Original docstring."""
        return 1

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Original docstring."


def test_deprecated_once_emits_once_for_same_key():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        deprecated_once("flag.x", "flag.x is deprecated")
        deprecated_once("flag.x", "flag.x is deprecated")
        deprecated_once("flag.x", "flag.x is deprecated")

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1
    assert "flag.x is deprecated" in str(deprecation_warnings[0].message)


def test_deprecated_once_emits_for_different_keys():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        deprecated_once("flag.a", "a deprecated")
        deprecated_once("flag.b", "b deprecated")

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 2
    messages = {str(w.message) for w in deprecation_warnings}
    assert "a deprecated" in messages
    assert "b deprecated" in messages


def test_deprecated_emits_on_every_call():
    @deprecated(reason="hot path", removed_in="0.5.0")
    def chatty():
        return None

    with pytest.warns(DeprecationWarning) as record:
        chatty()
        chatty()
        chatty()

    assert len(record) == 3
