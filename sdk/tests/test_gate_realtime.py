"""Tests for ``@vera.gate(realtime=True)`` — Wave 2C PR B2.

Covers the realtime decorator's routing:

* ALLOW + ``realtime=True`` — unchanged (invoke + capture + return).
* BLOCK + ``realtime=True`` — unchanged (no invoke, raise ``PolicyBlock``).
* REQUIRE_HITL + ``realtime=True`` — do NOT invoke, capture as
  ``pending_review`` with realtime provenance, raise
  ``RequiresDeferredReview`` (not ``PendingReview``).
* REQUIRE_HITL + ``realtime=False`` (default) — back-compat regression
  (still raises ``PendingReview``, still invokes for draft).
* Wire-level ``REQUIRE_DEFERRED_REVIEW`` effect — always raises
  ``RequiresDeferredReview`` regardless of ``realtime`` flag (the
  backend's policy is asserting deferred-review by design).
* All Ruling metadata (review_id / fix_url / required_role / gate_name /
  reason / reason_detail / citation / expected_resolution / webhook_url)
  surfaces on the new exception.
* ``bypass_gates`` short-circuits realtime calls too (treats as ALLOW).
* Async sibling routing matches the sync path.
* ``RequiresDeferredReview`` is distinct from ``PendingReview`` —
  ``except PendingReview`` MUST NOT catch the new exception.
* Defensive PHI redaction on ``reason_detail`` runs on the new
  exception (re-uses the B1 helper).
"""

from __future__ import annotations

import asyncio
import warnings
from unittest.mock import MagicMock

import httpx
import pytest

import vera
from vera import VeraClient
from vera._context import _current_tenant, set_default_tenant
from vera.decorator import set_default_client
from vera.errors import (
    PendingReview,
    PolicyBlock,
    RequiresDeferredReview,
)
from vera.gate import (
    GATE_EVALUATE_PATH,
    _reset_evaluate_404_warning,
    _reset_unknown_ruling_warnings,
)


# ---------------------------------------------------------------------------
# Helpers (mirror the layout of test_gate_decorator.py so the suites stay
# readable side-by-side; intentionally NOT a shared conftest to keep B2's
# new tests self-contained for future revert-ability).
# ---------------------------------------------------------------------------


def _make_client() -> VeraClient:
    """A real VeraClient we can monkeypatch the transport on."""
    return VeraClient(
        api_url="http://example.test",
        api_key="al_test_xxx",
        agent_name="test-agent",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )


def _install_transport(client: VeraClient, handler):
    """Patch the sync httpx transport so calls don't hit the network."""
    client._client._transport = httpx.MockTransport(handler)


def _evaluate_handler(response_body: dict, status: int = 200):
    """Return an httpx handler that responds to the evaluate POST only."""
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(status, json=response_body)
        # The background worker flushes ActionRecords to /v1/actions/batch.
        # Pretend it succeeded so the worker thread doesn't loop on 4xx/5xx.
        return httpx.Response(200, json={"records": []})

    return _h


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    """Clean per-test slate — mirrors test_gate_decorator.py's fixture.

    Resets env vars, tenant context, default client, and the
    once-per-process warning flags so tests don't bleed state into
    each other regardless of order.
    """
    monkeypatch.delenv("VERA_API_KEY", raising=False)
    monkeypatch.delenv("VERA_API_URL", raising=False)
    monkeypatch.delenv("VERA_AGENT_NAME", raising=False)
    set_default_tenant(None)
    token = _current_tenant.set(None)
    _reset_evaluate_404_warning()
    _reset_unknown_ruling_warnings()

    from vera import decorator as _decorator_mod

    previous = _decorator_mod._default_client
    set_default_client(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_client(previous)


# ---------------------------------------------------------------------------
# Back-compat regressions — default (realtime=False) routing unchanged.
# ---------------------------------------------------------------------------


def test_default_require_hitl_still_raises_pending_review():
    """Back-compat — without realtime= kwarg, REQUIRE_HITL → PendingReview."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "REQUIRE_HITL", "review_id": "rev_1"}),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "draft"

    with pytest.raises(PendingReview) as ei:
        wrapped()
    assert ei.value.review_id == "rev_1"
    # Default branch still invokes for the draft and records as pending_review.
    items = list(client._queue.queue)
    assert items[0]["result"] == "pending_review"
    client.close()


def test_explicit_realtime_false_matches_default():
    """Back-compat — realtime=False is identical to no kwarg at all."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "REQUIRE_HITL", "review_id": "rev_2"}),
    )
    set_default_client(client)

    spy = MagicMock(return_value="draft_value")

    @vera.gate(action_class="x", tenant="acme", realtime=False)
    def wrapped():
        return spy()

    with pytest.raises(PendingReview):
        wrapped()
    # Wrapped function IS invoked (default sync semantics).
    spy.assert_called_once()
    client.close()


# ---------------------------------------------------------------------------
# realtime=True + REQUIRE_HITL — the new branch.
# ---------------------------------------------------------------------------


def test_realtime_require_hitl_raises_requires_deferred_review():
    """B2 — realtime=True + REQUIRE_HITL routes to RequiresDeferredReview."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_realtime_1",
            "required_role": "attending_physician",
            "fix_url": "https://app.usevera.xyz/reviews/rev_realtime_1",
            "reason": "sensitive_change",
            "reason_detail": "Final HPI section edited by scribe",
            "citation": "HIPAA § 164.524",
            "gate_name": "chart_note_attending_required",
            "expected_resolution": "2026-05-25T00:00:00Z",
            "webhook_url": "https://customer.test/hook",
        }),
    )
    set_default_client(client)

    spy = MagicMock(return_value="should not run")

    @vera.gate(action_class="commit_chart_note", tenant="acme", realtime=True)
    def commit():
        return spy()

    with pytest.raises(RequiresDeferredReview) as ei:
        commit()

    # Critical invariant: wrapped function is NOT invoked — customer-side
    # deferred-execution store will run it after webhook resolution.
    spy.assert_not_called()

    # All Ruling metadata surfaces on the new exception (mirror of the
    # B1 contract for PendingReview).
    assert ei.value.review_id == "rev_realtime_1"
    assert ei.value.required_role == "attending_physician"
    assert ei.value.fix_url == "https://app.usevera.xyz/reviews/rev_realtime_1"
    assert ei.value.reason == "sensitive_change"
    assert ei.value.reason_detail == "Final HPI section edited by scribe"
    assert ei.value.citation == "HIPAA § 164.524"
    assert ei.value.gate_name == "chart_note_attending_required"
    assert ei.value.expected_resolution == "2026-05-25T00:00:00Z"
    assert ei.value.webhook_url == "https://customer.test/hook"
    client.close()


def test_realtime_require_hitl_captures_with_realtime_provenance():
    """B2 — realtime path still captures the action; metadata names the path."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_capture_1",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return "should not run"

    with pytest.raises(RequiresDeferredReview):
        wrapped()

    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "pending_review"
    assert items[0]["metadata"]["review_id"] == "rev_capture_1"
    # Audit ledger must distinguish realtime-deferred from sync-pending
    # so retrospective reporting can separate the two patterns.
    assert items[0]["outcome"]["realtime"] is True
    client.close()


# ---------------------------------------------------------------------------
# realtime=True + ALLOW / BLOCK — unchanged.
# ---------------------------------------------------------------------------


def test_realtime_allow_invokes_and_returns():
    """B2 — ALLOW + realtime=True still invokes and returns."""
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    spy = MagicMock(return_value=99)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped(arg):
        return spy(arg)

    assert wrapped("payload") == 99
    spy.assert_called_once_with("payload")
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


def test_realtime_block_still_raises_policy_block():
    """B2 — BLOCK + realtime=True still raises PolicyBlock (immediate).

    BLOCK is terminal regardless of realtime — the customer cannot
    "queue and continue" a forbidden action. The behaviour MUST mirror
    the default decorator exactly.
    """
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "BLOCK",
            "reason": "BAA required",
            "fix_url": "https://app.usevera.xyz/baa",
        }),
    )
    set_default_client(client)

    spy = MagicMock()

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        spy()

    with pytest.raises(PolicyBlock) as ei:
        wrapped()
    spy.assert_not_called()
    assert ei.value.reason == "BAA required"
    client.close()


# ---------------------------------------------------------------------------
# Exception hierarchy — RequiresDeferredReview must be distinct.
# ---------------------------------------------------------------------------


def test_requires_deferred_review_not_caught_by_pending_review():
    """B2 — RequiresDeferredReview MUST NOT be a subclass of PendingReview.

    Customer code routing on ``except PendingReview`` MUST NOT
    accidentally swallow the new exception — the two represent
    different patterns and a customer who hasn't opted into realtime
    semantics MUST see the new exception bubble up.
    """
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "REQUIRE_HITL", "review_id": "rev_xy"}),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return "draft"

    caught = None
    try:
        wrapped()
    except PendingReview as e:
        # Should NOT land here — PendingReview MUST NOT catch the new
        # exception. If it does, the test fails loudly.
        caught = ("pending_review", e)
    except RequiresDeferredReview as e:
        caught = ("requires_deferred_review", e)

    assert caught is not None
    assert caught[0] == "requires_deferred_review"
    client.close()


def test_requires_deferred_review_is_vera_error():
    """B2 — RequiresDeferredReview inherits from VeraError (catalog invariant)."""
    err = RequiresDeferredReview("msg", review_id="rev_x")
    from vera.errors import VeraError

    assert isinstance(err, VeraError)
    # to_dict() carries the four-field error-discipline template plus the
    # Ruling metadata so structured logs / dashboard renderers can route
    # uniformly on this exception.
    d = err.to_dict()
    assert d["code"] == "requires_deferred_review"
    assert d["review_id"] == "rev_x"
    assert "user_facing_reason" in d
    assert "developer_reason" in d
    assert "fix_url" in d
    assert "docs_url" in d


# ---------------------------------------------------------------------------
# Wire-level REQUIRE_DEFERRED_REVIEW effect — fires regardless of realtime
# flag because the backend is asserting policy intent.
# ---------------------------------------------------------------------------


def test_wire_require_deferred_review_routes_regardless_of_realtime_flag():
    """B2 — REQUIRE_DEFERRED_REVIEW wire effect → RequiresDeferredReview always."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_DEFERRED_REVIEW",
            "review_id": "rev_wire_1",
            "gate_name": "deferred_by_policy",
        }),
    )
    set_default_client(client)

    spy = MagicMock(return_value="should not run")

    # Note: realtime=False — but the backend's wire effect overrides the
    # call site's preference because the policy itself asserts deferred.
    @vera.gate(action_class="x", tenant="acme", realtime=False)
    def wrapped():
        return spy()

    with pytest.raises(RequiresDeferredReview) as ei:
        wrapped()
    spy.assert_not_called()
    assert ei.value.review_id == "rev_wire_1"
    assert ei.value.gate_name == "deferred_by_policy"
    items = list(client._queue.queue)
    assert items[0]["result"] == "pending_review"
    assert items[0]["outcome"]["deferred_review_wire_effect"] is True
    client.close()


# ---------------------------------------------------------------------------
# bypass_gates short-circuit works with realtime decorators too.
# ---------------------------------------------------------------------------


def test_bypass_skips_realtime_evaluate_call():
    """B2 — bypass_gates fixture short-circuits realtime decorators as ALLOW."""
    from vera.testing import bypass_gates_cm

    client = _make_client()
    paths_hit: list[str] = []

    def handler(request):
        paths_hit.append(request.url.path)
        if request.url.path == GATE_EVALUATE_PATH:
            # Fail loudly if bypass didn't short-circuit.
            return httpx.Response(500, json={"detail": "bypass leaked"})
        return httpx.Response(200, json={"records": []})

    _install_transport(client, handler)
    set_default_client(client)

    spy = MagicMock(return_value="ok")

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return spy()

    with bypass_gates_cm():
        result = wrapped()

    # Bypass treats every ruling as ALLOW — even on realtime decorators,
    # so the wrapped function IS invoked (this is the test-mode contract).
    assert result == "ok"
    spy.assert_called_once()
    assert GATE_EVALUATE_PATH not in paths_hit
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


# ---------------------------------------------------------------------------
# Async path — realtime routing must mirror sync exactly.
# ---------------------------------------------------------------------------


def test_async_realtime_require_hitl_raises_requires_deferred_review():
    """B2 — async + realtime=True + REQUIRE_HITL → RequiresDeferredReview."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_async_b2",
            "required_role": "attending_physician",
        }),
    )
    set_default_client(client)

    invoked = {"called": False}

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    async def wrapped():
        invoked["called"] = True
        return "should not run"

    with pytest.raises(RequiresDeferredReview) as ei:
        asyncio.run(wrapped())

    assert invoked["called"] is False
    assert ei.value.review_id == "rev_async_b2"
    assert ei.value.required_role == "attending_physician"
    items = list(client._queue.queue)
    assert items[0]["result"] == "pending_review"
    assert items[0]["outcome"]["realtime"] is True
    client.close()


def test_async_realtime_allow_unchanged():
    """B2 — async + realtime=True + ALLOW invokes + captures like sync."""
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    async def wrapped(x):
        return x * 3

    assert asyncio.run(wrapped(7)) == 21
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


# ---------------------------------------------------------------------------
# Defensive PHI redaction (mirrors B1 invariant — applies on the new exc too).
# ---------------------------------------------------------------------------


def test_realtime_redacts_phi_shape_reason_detail():
    """B2 — backend leaking PHI in reason_detail must NOT reach customer."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_phi_1",
            "reason": "sensitive_edit",
            # Whitespace + digits → likely PHI (defensive heuristic trips).
            "reason_detail": "Patient John Doe 1972-03-14 admitted",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return "should not run"

    with pytest.raises(RequiresDeferredReview) as ei:
        wrapped()
    assert ei.value.reason_detail == (
        "(redacted: reason_detail matched PHI-shape heuristic)"
    )
    # Defense-in-depth: assert the rendered str() also doesn't leak.
    assert "John Doe" not in str(ei.value)
    assert "1972-03-14" not in str(ei.value)
    client.close()


# ---------------------------------------------------------------------------
# Backward-compat — existing v1.0.x decorators without realtime kwarg.
# ---------------------------------------------------------------------------


def test_existing_callers_without_realtime_kwarg_unaffected():
    """B2 — call sites that don't pass realtime= keep their v1.0.x behaviour.

    The risk we guard against: a refactor that defaults ``realtime`` to
    ``True`` (e.g. ``realtime: bool = True``) would silently break every
    existing ``@vera.gate`` caller by switching HITL semantics under
    them. This test asserts the default is sync-PendingReview semantics
    by exercising a REQUIRE_HITL ruling with no realtime= kwarg and
    confirming the wrapped function IS invoked (the v1.0.x contract).
    """
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "REQUIRE_HITL", "review_id": "rev_bc"}),
    )
    set_default_client(client)

    spy = MagicMock(return_value="draft_payload")

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return spy()

    with pytest.raises(PendingReview):
        wrapped()
    spy.assert_called_once()  # v1.0.x: wrapped IS invoked for the draft.
    client.close()


def test_realtime_404_fallback_still_audit_only():
    """B2 — 404 fallback (Phase 1 bridge) ignores realtime= and runs the function."""
    client = _make_client()
    _install_transport(client, _evaluate_handler({}, status=404))
    set_default_client(client)

    spy = MagicMock(return_value="ok")

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return spy()

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        assert wrapped() == "ok"

    # 404 → audit-only fallback runs the function regardless of realtime
    # flag (no ruling means there's no HITL to defer).
    spy.assert_called_once()
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


def test_realtime_exported_from_vera_namespace():
    """B2 — vera.RequiresDeferredReview is importable from the top-level package."""
    assert vera.RequiresDeferredReview is RequiresDeferredReview
    # Sanity: it appears in the public __all__ so star-imports pick it up.
    assert "RequiresDeferredReview" in vera.__all__
