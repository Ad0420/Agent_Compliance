"""Shared pytest fixtures for the SDK test suite.

Phase 1 PR 7 follow-up: ``vera.init(default_tenant=...)`` mutates a
module-level global in :mod:`vera._context`. Tests that don't already
use the per-file ``_reset_state`` fixture from
``test_tenant_payload_stamping.py`` saw cross-test pollution — a test
ordering issue where one file's ``default_tenant`` leaked into a
later file's expectations.

The autouse fixtures below clear every process-level global the SDK
exposes after each test, so adding new tests doesn't require
remembering to drag the reset machinery along. They are no-ops for
tests that never touched the underlying state.

Phase 1 PR 8 adds three more globals to reset:
* ``vera._context._default_agent_type`` — ``vera.init(agent_type=)``.
* ``vera.gate._evaluate_404_warned`` — once-per-process WARN flag
  for the ``/v1/gates/evaluate`` 404 fallback.
* ``vera.decorator._audit_warned_sites`` — per-call-site dedupe set
  for the ``@vera.audit`` deprecation warning.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_default_tenant():
    yield
    from vera._context import set_default_tenant

    set_default_tenant(None)


@pytest.fixture(autouse=True)
def _reset_default_agent_type():
    """Phase 1 PR 8: reset the ``agent_type`` global after every test.

    Mirrors ``_reset_default_tenant`` so tests calling
    ``vera.init(agent_type='x')`` don't leak the global into the next
    test's expectations.
    """
    yield
    from vera._context import set_default_agent_type

    set_default_agent_type(None)


@pytest.fixture(autouse=True)
def _reset_gate_state():
    """Phase 1 PR 8: reset once-per-process gate warnings between tests.

    The 404-fallback ``UserWarning`` and the unknown-ruling
    ``UserWarning`` dedupe sets would otherwise hide warnings on the
    second test that exercises the same path.
    """
    yield
    from vera.gate import (
        _reset_evaluate_404_warning,
        _reset_unknown_ruling_warnings,
    )

    _reset_evaluate_404_warning()
    _reset_unknown_ruling_warnings()


@pytest.fixture(autouse=True)
def _reset_audit_deprecation():
    """Phase 1 PR 8: reset the ``@vera.audit`` per-call-site dedupe set.

    The dedupe key is ``(filename, lineno)`` of each decoration site.
    Tests that decorate inline at the same file:line across multiple
    test runs would otherwise only see the warning fire on the first
    test.
    """
    yield
    from vera.decorator import _reset_audit_deprecation_warnings

    _reset_audit_deprecation_warnings()
