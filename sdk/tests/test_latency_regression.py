"""Latency regression baselines for key SDK paths (Codex X1).

These tests assert that critical SDK call paths complete within an
order-of-magnitude budget. They are **intentionally loose** — the goal
is to catch catastrophic regressions (3x+ slowdown), not to police
micro-optimizations.

Baselines were captured on commodity CI hardware (GitHub Actions
``ubuntu-latest``, Python 3.10, single-shard run, no other process
load) on 2026-05-24. They cover the four hottest decorator-internal
code paths:

* ``@vera.gate`` decorator, cold call (first invocation under
  ``bypass_gates_cm`` — exercises decorator setup, ContextVar lookup,
  payload build).
* ``@vera.gate`` decorator, warm call (subsequent calls — exercises
  the steady-state bookkeeping).
* ``resolve_tenant`` with an explicit kwarg (fastest path).
* ``resolve_tenant`` from a context manager (ContextVar lookup +
  source attribution).

All four run with the gate ``bypass_gates_cm()`` context active so
the ``/v1/gates/evaluate`` HTTP call is skipped — the goal is to
measure the SDK's own bookkeeping overhead, not a backend round
trip.

Skip mechanisms
---------------

* ``pytest -m 'not latency'`` — skip the whole suite (the ``latency``
  marker is registered in ``sdk/pyproject.toml::tool.pytest.ini_options``).
* ``VERA_SKIP_LATENCY_TESTS=1`` — env-var skip for CI environments
  that can't reliably hit the budget (under load, slow shared
  hardware, etc.). Per-test ``pytest.mark.skipif`` so it applies even
  when callers run the suite without ``-m`` filtering.

If the baselines need to move (legitimately slower CI hardware, or a
new fast path that moves a baseline DOWN), update the constants in
``BASELINES_US`` and add a note to
``sdk/MIGRATION.md::Latency expectations``.
"""

from __future__ import annotations

import os
import time

import pytest

import vera
from vera._context import resolve_tenant, set_default_tenant
from vera.testing import bypass_gates_cm


# ---------------------------------------------------------------------------
# Baselines (in microseconds) + global knobs.
# ---------------------------------------------------------------------------

# Baselines in microseconds. Loose by design — anything within 3x is
# acceptable. These are SDK-only overhead numbers (HTTP is bypassed).
BASELINES_US: dict[str, float] = {
    "gate_decorator_bypass_cold": 5000.0,
    "gate_decorator_bypass_warm": 500.0,
    "tenant_resolve_explicit": 50.0,
    "tenant_resolve_context_var": 100.0,
}

# Multiplier above baseline that counts as a regression. 3x is
# "catastrophic" — anything below that is noise on shared CI hardware.
REGRESSION_THRESHOLD: float = 3.0

WARMUP_ITERATIONS: int = 10
MEASURE_ITERATIONS: int = 100


# ---------------------------------------------------------------------------
# Markers + skip plumbing.
# ---------------------------------------------------------------------------

# Apply the ``latency`` marker to every test in this module — registered
# in pyproject.toml::tool.pytest.ini_options.markers so it doesn't raise
# PytestUnknownMarkWarning.
pytestmark = [
    pytest.mark.latency,
    pytest.mark.skipif(
        os.environ.get("VERA_SKIP_LATENCY_TESTS", "").lower() in {"1", "true", "yes"},
        reason="VERA_SKIP_LATENCY_TESTS set — skipping latency regression suite",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def configured_sdk(monkeypatch):
    """Initialise the SDK with a process-level tenant + agent_type.

    Yields the configured client so individual tests can monkeypatch its
    transport if they need to (we don't, but the hook is here for future
    expansion). Cleans up on teardown so the default client doesn't
    leak between tests.
    """
    # Strip env vars that would otherwise leak across tests run in
    # parallel (or interfere with the default ``vera.init`` resolution).
    for env_var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_AGENT_NAME",
        "VERA_DEV",
    ):
        monkeypatch.delenv(env_var, raising=False)

    set_default_tenant(None)

    client = vera.init(
        api_key="al_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        api_url="http://example.test",
        agent_name="latency-regression",
        default_tenant="latency_test_tenant",
        agent_type="benchmark",
        # Don't try to flush during the test — the budget is for the
        # decorator's hot-path bookkeeping, not the worker thread.
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )

    yield client

    try:
        client.close()
    except Exception:  # noqa: BLE001 — teardown best-effort
        pass
    set_default_tenant(None)


# ---------------------------------------------------------------------------
# Measurement helper.
# ---------------------------------------------------------------------------


def _measure_us(fn, iterations: int = MEASURE_ITERATIONS) -> float:
    """Return the mean per-call latency of ``fn`` in microseconds.

    Performs ``WARMUP_ITERATIONS`` warmup runs first so import-time
    caches and the CPython inline-cache machinery are primed before
    the measurement loop.
    """
    for _ in range(WARMUP_ITERATIONS):
        fn()
    start_ns = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    elapsed_ns = time.perf_counter_ns() - start_ns
    return (elapsed_ns / iterations) / 1000.0  # ns → µs


def _assert_within_budget(name: str, observed_us: float) -> None:
    baseline = BASELINES_US[name]
    budget = baseline * REGRESSION_THRESHOLD
    assert observed_us < budget, (
        f"{name}: observed {observed_us:.1f}µs/call exceeds "
        f"{budget:.1f}µs threshold (baseline {baseline:.1f}µs, "
        f"threshold = {REGRESSION_THRESHOLD}x baseline). "
        f"If this is a legitimate baseline shift, update "
        f"BASELINES_US in this file and add a note to "
        f"sdk/MIGRATION.md::Latency expectations."
    )


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_gate_decorator_bypass_cold_call(configured_sdk):
    """Cold @vera.gate decorator call under bypass.

    "Cold" = first invocation per decorated function. The decoration
    site captures the function module + line for the per-site
    DeprecationWarning dedupe; the first call has to walk that
    bookkeeping, while warm calls skip it.

    We measure this by re-creating the decorated function inside the
    timed loop so each iteration is a fresh decoration. Cost = decorate
    + first-call bookkeeping + ContextVar lookup + bypass-short-circuit
    + payload build.
    """
    def cold_call() -> int:
        @vera.gate("benchmark.cold_action")
        def f(x: int) -> int:
            return x * 2

        return f(42)

    with bypass_gates_cm():
        elapsed_us = _measure_us(cold_call, iterations=MEASURE_ITERATIONS)

    _assert_within_budget("gate_decorator_bypass_cold", elapsed_us)


def test_gate_decorator_bypass_warm_call(configured_sdk):
    """Warm @vera.gate decorator call under bypass.

    "Warm" = the decorator has been called at least once for this
    function (the cold-path bookkeeping is amortised). This is the
    steady-state per-call cost agents actually pay in production.
    """
    @vera.gate("benchmark.warm_action")
    def f(x: int) -> int:
        return x * 2

    with bypass_gates_cm():
        # warmup is implicit in _measure_us, plus the function is
        # already constructed so iteration cost is purely the gate
        # decorator's bookkeeping + the function body (which is
        # trivial).
        elapsed_us = _measure_us(lambda: f(42), iterations=MEASURE_ITERATIONS)

    _assert_within_budget("gate_decorator_bypass_warm", elapsed_us)


def test_tenant_resolve_explicit_kwarg(configured_sdk):
    """resolve_tenant() with an explicit value — the fastest path.

    The resolver short-circuits to the explicit value after validating
    it against the regex. No ContextVar lookup, no default lookup.
    """
    elapsed_us = _measure_us(
        lambda: resolve_tenant(explicit="tenant_explicit"),
        iterations=MEASURE_ITERATIONS,
    )
    _assert_within_budget("tenant_resolve_explicit", elapsed_us)


def test_tenant_resolve_from_context_manager(configured_sdk):
    """resolve_tenant() reading from the vera.tenant() context manager.

    Walks the ContextVar, finds the binding, returns the (tenant_id,
    source) tuple. Slower than the explicit-kwarg path because of the
    ContextVar lookup, but still well under a millisecond.
    """
    with vera.tenant("tenant_ctxvar"):
        elapsed_us = _measure_us(
            lambda: resolve_tenant(),
            iterations=MEASURE_ITERATIONS,
        )
    _assert_within_budget("tenant_resolve_context_var", elapsed_us)
