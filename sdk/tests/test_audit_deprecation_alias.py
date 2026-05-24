"""Tests for the ``@vera.audit`` deprecation alias (Phase 1 PR 8 / Stream D6).

The legacy ``@vera.audit`` decorator continues to capture records with
unchanged runtime semantics — but the first time each call site is
invoked, it emits a ``DeprecationWarning`` pointing the operator at
``@vera.gate``.

Tests assert:
* Existing behaviour preserved (records still flow, function still runs).
* DeprecationWarning fires on call, not on decoration.
* Dedupe is per ``(filename, lineno)``: tight loop warns once.
* Distinct call sites each get their own warning.
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from vera.decorator import (
    _reset_audit_deprecation_warnings,
    audit,
    set_default_client,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Per-test reset of the per-call-site dedupe + client global."""
    _reset_audit_deprecation_warnings()
    previous = None
    from vera import decorator as _decorator_mod

    previous = _decorator_mod._default_client
    set_default_client(None)
    try:
        yield
    finally:
        set_default_client(previous)


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


def test_audit_still_captures_record():
    mock_client = MagicMock()

    @audit(action_name="x", client=mock_client)
    def add(a, b):
        return a + b

    with warnings.catch_warnings():
        # Suppress the deprecation warning for this assertion — separate
        # test below asserts it fires.
        warnings.simplefilter("ignore", DeprecationWarning)
        assert add(2, 3) == 5

    mock_client.enqueue_action.assert_called_once()
    call_kwargs = mock_client.enqueue_action.call_args[1]
    assert call_kwargs["action_name"] == "x"
    assert call_kwargs["result"] == "success"


def test_audit_still_records_failure():
    mock_client = MagicMock()

    @audit(action_name="x", client=mock_client)
    def fail():
        raise ValueError("boom")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ValueError):
            fail()

    mock_client.enqueue_action.assert_called_once()
    call_kwargs = mock_client.enqueue_action.call_args[1]
    assert call_kwargs["result"] == "failure"


# ---------------------------------------------------------------------------
# DeprecationWarning fires
# ---------------------------------------------------------------------------


def test_deprecation_warning_fires_on_call():
    mock_client = MagicMock()

    @audit(action_name="x", client=mock_client)
    def wrapped():
        return "ok"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wrapped()

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) == 1
    msg = str(deps[0].message)
    assert "@vera.audit" in msg
    assert "@vera.gate" in msg
    assert "2.0.0" in msg


def test_deprecation_warning_dedupes_per_call_site():
    """Tight loop calling one decorated function warns ONCE."""
    mock_client = MagicMock()

    @audit(action_name="x", client=mock_client)
    def wrapped():
        return "ok"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(100):
            wrapped()

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) == 1  # ONE warning, not 100.


def test_deprecation_warning_fires_per_distinct_call_site():
    """Two separate @audit decorators each get their own warning."""
    mock_client = MagicMock()

    @audit(action_name="a", client=mock_client)
    def func_a():
        return "a"

    @audit(action_name="b", client=mock_client)
    def func_b():
        return "b"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        func_a()
        func_b()
        func_a()  # already-warned site — no additional warning
        func_b()  # already-warned site — no additional warning

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) == 2  # one per call site


def test_deprecation_warning_does_not_fire_at_decoration_time():
    mock_client = MagicMock()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        @audit(action_name="x", client=mock_client)
        def wrapped():
            return "ok"

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deps == []  # Decoration alone must not warn.
