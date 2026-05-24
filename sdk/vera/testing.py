"""Testing utilities for the Vera SDK (Phase 1 PR 8 / Stream D10).

This module exposes :func:`bypass_gates` in two forms:

* **Context manager** — ``with vera.testing.bypass_gates(): ...``.
  Useful inside individual test bodies or scripts.
* **Pytest fixture** — ``def test_x(bypass_gates): ...``. Imported
  from a customer ``conftest.py`` as::

      from vera.testing import bypass_gates  # noqa: F401  # re-export as fixture

  When the fixture is active, ``@vera.gate`` skips the
  ``/v1/gates/evaluate`` HTTP call and routes every ruling as ALLOW.
  The wrapped function is still invoked and the call is still captured
  as an :class:`ActionRecord` — only the policy lookup is short-circuited.

NOT FOR PRODUCTION USE. The whole point is to make pilot test suites
shippable before backend ``/v1/gates/evaluate`` lands; using this in
production would silently disable policy enforcement.

Implementation
--------------

The bypass flag lives on a :class:`contextvars.ContextVar` so it
isolates correctly across concurrent asyncio tasks and threads. See
:mod:`vera._context`'s ``copy_context_to_thread`` for the propagation
gotcha (Codex F4) when work is submitted to a thread pool the SDK
doesn't control — the same caveat applies here: the bypass state
travels with the context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest

from .gate import _reset_bypass, _set_bypass


@contextmanager
def bypass_gates_cm() -> Iterator[None]:
    """Context-manager form of :func:`bypass_gates`.

    Exposed as a separate symbol so callers who want the context
    manager directly (not a pytest fixture) can use it without
    pulling in the pytest fixture machinery.
    """
    token = _set_bypass(True)
    try:
        yield
    finally:
        _reset_bypass(token)


@pytest.fixture
def bypass_gates() -> Iterator[None]:
    """Pytest fixture: ``@vera.gate`` calls skip the backend for this test.

    The wrapped function is still invoked, the call is still captured
    as an :class:`ActionRecord`, and the audit-trail invariant holds.
    Only the ``/v1/gates/evaluate`` POST is skipped.

    Usage::

        def test_loan_decision(bypass_gates, vera_sdk_recording):
            approve_loan(applicant_id='x', amount=10000)
            assert vera_sdk_recording.records[0]['action_name'] == 'approve_loan'

    Implemented via a :class:`contextvars.ContextVar` so concurrent
    asyncio tasks inside the test body each see the active bypass
    state independently — and so the bypass is automatically cleared
    on test teardown via the reset token, even if the test raised.
    """
    token = _set_bypass(True)
    try:
        yield
    finally:
        _reset_bypass(token)


__all__ = [
    "bypass_gates",
    "bypass_gates_cm",
]
