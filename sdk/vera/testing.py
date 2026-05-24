"""Testing utilities for the Vera SDK (Phase 1 PR 8 / Stream D10).

This module exposes :func:`bypass_gates` in two forms:

* **Context manager** — ``with vera.testing.bypass_gates_cm(): ...``.
  Useful inside individual test bodies, scripts, or notebooks.
  Works with or without pytest installed.
* **Pytest fixture** — ``def test_x(bypass_gates): ...``. Available
  whenever ``pytest`` is importable (true for any environment that
  actually runs tests). Imported from a customer ``conftest.py`` as::

      from vera.testing import bypass_gates  # noqa: F401  # re-export as fixture

  When the fixture is active, ``@vera.gate`` skips the
  ``/v1/gates/evaluate`` HTTP call and routes every ruling as ALLOW.
  The wrapped function is still invoked and the call is still captured
  as an :class:`ActionRecord` — only the policy lookup is short-circuited.

NOT FOR PRODUCTION USE. The whole point is to make pilot test suites
shippable before backend ``/v1/gates/evaluate`` lands; using this in
production would silently disable policy enforcement.

Optional pytest import
----------------------

``import pytest`` is intentionally guarded so that production-adjacent
code (notebooks, scripts, the latency-regression suite running outside
a normal pytest tree, a fresh ``pip install vera-sdk`` venv without
the dev extras) can use ``bypass_gates_cm`` without dragging the
``pytest`` runtime in.

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
from typing import Any, Iterator

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:  # pragma: no cover — covered indirectly by the
    # build-artifact sanity test, which installs the wheel into a
    # fresh venv with no pytest available.
    pytest = None  # type: ignore[assignment]
    _HAS_PYTEST = False

from .gate import _reset_bypass, _set_bypass


@contextmanager
def bypass_gates_cm() -> Iterator[None]:
    """Context-manager form of :func:`bypass_gates`.

    Exposed as a separate symbol so callers who want the context
    manager directly (not a pytest fixture) can use it without
    pulling in the pytest fixture machinery. Works WITHOUT pytest
    installed — the optional ``import pytest`` at the top of this
    module guards the fixture form below, not the context manager.
    """
    token = _set_bypass(True)
    try:
        yield
    finally:
        _reset_bypass(token)


def _bypass_gates_fixture_impl() -> Iterator[None]:
    """Body shared between the pytest-fixture and unwrapped forms.

    Centralised so the fixture wrapper below is a one-line decoration
    over an actual implementation we can unit-test directly.
    """
    token = _set_bypass(True)
    try:
        yield
    finally:
        _reset_bypass(token)


if _HAS_PYTEST:
    bypass_gates: Any = pytest.fixture(_bypass_gates_fixture_impl)
    bypass_gates.__doc__ = (
        "Pytest fixture: ``@vera.gate`` calls skip the backend for this test.\n"
        "\n"
        "The wrapped function is still invoked, the call is still captured\n"
        "as an ActionRecord, and the audit-trail invariant holds. Only the\n"
        "``/v1/gates/evaluate`` POST is skipped.\n"
        "\n"
        "Implemented via a contextvars.ContextVar so concurrent asyncio\n"
        "tasks inside the test body each see the active bypass state\n"
        "independently — and so the bypass is automatically cleared on\n"
        "test teardown via the reset token, even if the test raised.\n"
    )
else:  # pragma: no cover — exercised by the build-artifact sanity test
    # No pytest available: expose a callable that raises if anyone tries
    # to use it as a fixture. Importing the symbol still succeeds so
    # ``from vera.testing import bypass_gates_cm, bypass_gates`` doesn't
    # fail at import time in non-pytest environments.
    def bypass_gates(*args: Any, **kwargs: Any) -> Iterator[None]:  # type: ignore[misc]
        """Pytest fixture stub — install ``pytest`` to use this fixture.

        Without pytest, only ``bypass_gates_cm`` (the context-manager
        form) is functional. Call it directly:
        ``with vera.testing.bypass_gates_cm(): ...``.
        """
        raise RuntimeError(
            "vera.testing.bypass_gates requires pytest. "
            "Install pytest (`pip install pytest`) or use the "
            "context-manager form: `with vera.testing.bypass_gates_cm(): ...`."
        )


__all__ = [
    "bypass_gates",
    "bypass_gates_cm",
]
