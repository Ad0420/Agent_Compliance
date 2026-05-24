"""pytest plugin: provides the ``vera_sdk_recording`` fixture.

Auto-loaded when ``vera-sdk`` is installed (via the ``pytest11`` entry
point in ``pyproject.toml``). Tests can request the fixture to assert on
audit records without mocking httpx or running a real HTTP server.

Example::

    def test_loan_decision(vera_sdk_recording):
        approve_loan(applicant_id="x", amount=10000)
        assert len(vera_sdk_recording.records) == 1
        assert vera_sdk_recording.records[0]["action_name"] == "approve_loan"

The fixture yields the underlying :class:`vera.dev._StderrSink`. Records
are echoed with ``echo=False`` (no stderr noise during a test run). The
previous default ``@audit`` client is restored on teardown — but ONLY if
the test body didn't replace it itself. Tests that call
``vera.init(...)`` mid-test keep their explicitly-installed client.

The fixture was renamed from ``vera_recording`` to ``vera_sdk_recording``
in PR #170 to reduce collision risk with customer fixtures named
``recording``.
"""

from __future__ import annotations

import pytest

from .decorator import set_default_client
from .dev import _StderrSink, build_dev_client
# Re-export the Phase 1 PR 8 / Stream D10 ``bypass_gates`` fixture
# through the pytest11 entry point so customer test suites get it
# automatically without an explicit ``from vera.testing import ...``
# in their conftest. Pattern matches ``vera_sdk_recording`` above —
# the auto-registered plugin is the discovery surface; ``vera.testing``
# stays available for callers who want to import the context-manager
# form (``bypass_gates_cm``) directly.
from .testing import bypass_gates  # noqa: F401 — re-export as pytest fixture


@pytest.fixture
def vera_sdk_recording():
    """Yield a :class:`vera.dev._StderrSink` capturing all audit events.

    The sink is wired into a fresh :class:`vera.dev.DevClient` registered
    as the default Vera client for the duration of the test. After the
    test, the previous default (if any) is restored — UNLESS the test
    body itself replaced the default (e.g. by calling ``vera.init(...)``),
    in which case the test's explicit choice wins. ``echo=False`` so
    test output stays clean.
    """
    # Snapshot the previous default by reading the module attribute fresh —
    # the value bound at import time would be stale by the time the
    # fixture fires.
    from . import decorator as _decorator_mod

    previous = _decorator_mod._default_client

    sink = _StderrSink(echo=False)
    dev_client = build_dev_client(sink=sink)
    set_default_client(dev_client)

    try:
        yield sink
    finally:
        # Only restore the entry-default if the test didn't replace the
        # default itself. If the test called ``vera.init(...)`` or
        # ``set_default_client(...)`` mid-test, the current default is no
        # longer our dev_client — that's an explicit choice we should
        # respect, not clobber.
        current = _decorator_mod._default_client
        if current is dev_client:
            set_default_client(previous)
