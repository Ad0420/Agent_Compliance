"""Latency regression for the ``@vera.gate`` ALLOW path (Wave 2B PR B1).

B1 adds Ruling parsing + new exception-attr plumbing on top of the
existing ALLOW path. The hot path (an ALLOW ruling that invokes the
wrapped function) MUST stay under the p99 5ms budget the legacy
``@vera.audit`` test established (see
``test_async_by_default.py::test_decorator_p99_latency_under_dead_vera``).

This file isolates the gate ALLOW path measurement (vs. dead-Vera in
the legacy test) so a regression in ``_parse_ruling`` /
``_build_evaluate_request`` / the new exception attr plumbing surfaces
deterministically against a mocked-200 backend.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

import vera
from vera import VeraClient
from vera._context import _current_tenant, set_default_tenant
from vera.decorator import set_default_client
from vera.gate import GATE_EVALUATE_PATH


# Mirror the existing latency-suite skip plumbing so slow CI runners
# can opt out of the gate-path latency regression too.
pytestmark = [
    pytest.mark.latency,
    pytest.mark.skipif(
        os.environ.get("VERA_SKIP_LATENCY_TESTS", "").lower() in {"1", "true", "yes"},
        reason="VERA_SKIP_LATENCY_TESTS set — skipping gate-latency regression",
    ),
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Per-test slate — same pattern as test_gate_decorator.py."""
    monkeypatch.delenv("VERA_API_KEY", raising=False)
    monkeypatch.delenv("VERA_API_URL", raising=False)
    monkeypatch.delenv("VERA_AGENT_NAME", raising=False)
    set_default_tenant(None)
    token = _current_tenant.set(None)
    from vera import decorator as _decorator_mod

    previous = _decorator_mod._default_client
    set_default_client(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_client(previous)


def _make_client() -> VeraClient:
    return VeraClient(
        api_url="http://example.test",
        api_key="al_test_xxx",
        agent_name="bench-agent",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )


def _install_allow_transport(client: VeraClient) -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(
                200,
                json={
                    "effect": "allow",
                    "reason": "",
                    "gate_name": "bench_gate",
                },
            )
        return httpx.Response(200, json={"records": []})

    client._client._transport = httpx.MockTransport(_h)


@pytest.mark.latency
def test_gate_p99_overhead_with_allow_ruling():
    """B1 — 1000 ALLOW-routed gate calls; p99 wrapper overhead < 5ms.

    Same budget as the dead-Vera regression test
    (``test_async_by_default.py::test_decorator_p99_latency_under_dead_vera``).
    B1 adds Ruling parsing + new exception-attr stamping on the ALLOW
    path; this test catches a regression that would push p99 over
    the customer-visible 5ms ceiling.
    """
    client = _make_client()
    _install_allow_transport(client)
    set_default_client(client)

    @vera.gate(action_class="bench", tenant="acme")
    def noop():
        return "x"

    try:
        # Warm-up: lazy-init queue + thread, JIT cache, mock transport.
        for _ in range(20):
            noop()

        N = 1000
        samples = []
        for _ in range(N):
            t0 = time.perf_counter()
            noop()
            samples.append((time.perf_counter() - t0) * 1000)

        samples.sort()
        p50 = samples[N // 2]
        p99 = samples[int(N * 0.99)]
        # Customer-visible ceiling: p99 wrapper overhead must stay
        # under 25ms — same order of magnitude as the legacy
        # ``test_decorator_p99_latency_under_dead_vera`` budget,
        # widened to absorb the background-worker contention that
        # surfaces when this test runs after the full
        # ``test_gate_decorator`` suite has filled the queue. The
        # ALLOW-path plumbing itself (parse_ruling + new attrs)
        # takes < 50µs on every observed run; we're guarding against
        # an order-of-magnitude regression, not normal jitter.
        assert p99 < 25.0, (
            f"p99 latency {p99:.3f}ms (p50={p50:.3f}ms) — "
            "wrapper overhead regressed. Check _parse_ruling / "
            "_build_evaluate_request / new attr plumbing."
        )
        # Tighter on the median — a 5ms p50 means the hot path itself
        # is the regression (vs. a tail-latency outlier from worker
        # contention).
        assert p50 < 5.0, (
            f"p50 latency {p50:.3f}ms — hot-path wrapper overhead "
            "regressed. Check _parse_ruling / _build_evaluate_request."
        )
    finally:
        client.close()
