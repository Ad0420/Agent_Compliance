"""pytest plugin: provides the ``vera_recording`` fixture.

Auto-loaded when ``vera-sdk`` is installed (via the ``pytest11`` entry
point in ``pyproject.toml``). Tests can request the fixture to assert on
audit records without mocking httpx or running a real HTTP server.

Example::

    def test_loan_decision(vera_recording):
        approve_loan(applicant_id="x", amount=10000)
        assert len(vera_recording.records) == 1
        assert vera_recording.records[0]["action_name"] == "approve_loan"

The fixture yields the underlying :class:`vera.dev._StderrSink`. Records
are echoed with ``echo=False`` (no stderr noise during a test run). The
previous default ``@audit`` client is restored on teardown so fixture use
doesn't leak state across tests.
"""

from __future__ import annotations

import pytest

from .decorator import _default_client as _read_default_client  # noqa: F401 — referenced via getattr
from .decorator import set_default_client
from .dev import _StderrSink, build_dev_client


@pytest.fixture
def vera_recording():
    """Yield a :class:`vera.dev._StderrSink` capturing all audit events.

    The sink is wired into a fresh :class:`vera.dev.DevClient` registered
    as the default Vera client for the duration of the test. After the
    test, the previous default (if any) is restored. ``echo=False`` so
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
        set_default_client(previous)
