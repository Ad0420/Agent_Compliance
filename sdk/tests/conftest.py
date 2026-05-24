"""Shared pytest fixtures for the SDK test suite.

Phase 1 PR 7 follow-up: ``vera.init(default_tenant=...)`` mutates a
module-level global in :mod:`vera._context`. Tests that don't already
use the per-file ``_reset_state`` fixture from
``test_tenant_payload_stamping.py`` saw cross-test pollution — a test
ordering issue where one file's ``default_tenant`` leaked into a
later file's expectations.

This autouse fixture clears the global default after every test in
the suite, so adding new tests doesn't require remembering to drag
the reset machinery along. It's a no-op for tests that never touched
the default.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_default_tenant():
    yield
    from vera._context import set_default_tenant

    set_default_tenant(None)
