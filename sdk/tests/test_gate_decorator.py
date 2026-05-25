"""Tests for the ``@vera.gate`` decorator (Phase 1 PR 8 / Stream D5).

Covers the ALLOW / REQUIRE_HITL / BLOCK routing, the 404 Phase 1 / Phase 2
bridge fallback, tenant + agent_type stamping precedence, async-function
wrapping, bypass-via-ContextVar, and the audit-trail invariant that
capture happens regardless of ruling effect.

Backend ``/v1/gates/evaluate`` is mocked with ``httpx.MockTransport`` so
the SDK code path runs end-to-end without a real server.
"""

from __future__ import annotations

import asyncio
import json
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
    TenantMissingOrInvalid,
    VeraClientError,
)
from vera.gate import (
    GATE_EVALUATE_PATH,
    _reset_evaluate_404_warning,
    _reset_unknown_ruling_warnings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> VeraClient:
    """A real ``VeraClient`` we can monkeypatch the transport on."""
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
    """Return an httpx handler that responds to the evaluate POST only.

    Action capture goes to ``/v1/actions/batch`` via the background
    worker thread — we ignore that here (the worker flushes lazily on
    its own cadence; the queue contents are checked directly).
    """
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(status, json=response_body)
        # Any other path (the batch flush) — pretend it succeeded so
        # the worker doesn't loop.
        return httpx.Response(200, json={"records": []})

    return _h


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    """Clean per-test slate: clear tenant context, default client, warnings."""
    # Reset env / state captured at module load time.
    monkeypatch.delenv("VERA_API_KEY", raising=False)
    monkeypatch.delenv("VERA_API_URL", raising=False)
    monkeypatch.delenv("VERA_AGENT_NAME", raising=False)
    set_default_tenant(None)
    token = _current_tenant.set(None)
    _reset_evaluate_404_warning()
    _reset_unknown_ruling_warnings()

    # Snapshot + clear the default client; restored after each test.
    from vera import decorator as _decorator_mod

    previous = _decorator_mod._default_client
    set_default_client(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_client(previous)


# ---------------------------------------------------------------------------
# ALLOW path
# ---------------------------------------------------------------------------


def test_allow_invokes_and_returns(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    spy = MagicMock(return_value=42)

    @vera.gate(action_class="my_action", tenant="acme")
    def wrapped(x):
        return spy(x)

    result = wrapped("hello")
    assert result == 42
    spy.assert_called_once_with("hello")

    # ActionRecord should be on the queue (background worker hasn't
    # necessarily flushed — that's fine; we just want to verify capture).
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["action_name"] == "my_action"
    assert items[0]["result"] == "success"
    assert items[0]["tenant_id"] == "acme"
    client.close()


def test_allow_uses_function_name_when_action_class_empty(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(tenant="acme")
    def my_func():
        return "ok"

    assert my_func() == "ok"
    items = list(client._queue.queue)
    assert items[0]["action_name"] == "my_func"
    client.close()


# ---------------------------------------------------------------------------
# REQUIRE_HITL path
# ---------------------------------------------------------------------------


def test_require_hitl_captures_draft_then_raises(monkeypatch):
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_123",
            "required_role": "attending_physician",
            "expected_resolution": "2025-12-01T00:00:00Z",
            "webhook_url": "https://example.test/hook",
        }),
    )
    set_default_client(client)

    spy = MagicMock(return_value="draft_chart_note")

    @vera.gate(action_class="commit_chart_note", tenant="acme")
    def commit():
        return spy()

    with pytest.raises(PendingReview) as ei:
        commit()

    # Wrapped function IS invoked for the draft.
    spy.assert_called_once()
    # PendingReview carries all the fields the backend supplied.
    assert ei.value.review_id == "rev_123"
    assert ei.value.required_role == "attending_physician"
    assert ei.value.expected_resolution == "2025-12-01T00:00:00Z"
    assert ei.value.webhook_url == "https://example.test/hook"
    # Capture invariant: draft was captured BEFORE the raise.
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["action_name"] == "commit_chart_note"
    assert items[0]["result"] == "pending_review"
    client.close()


def test_require_hitl_captures_failure_when_wrapped_raises(monkeypatch):
    """If the wrapped function raises during the draft, we still capture."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_456",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="commit", tenant="acme")
    def fail():
        raise RuntimeError("downstream fail")

    with pytest.raises(RuntimeError):
        fail()

    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "failure"
    assert items[0]["error_message"] == "downstream fail"
    client.close()


# ---------------------------------------------------------------------------
# BLOCK path
# ---------------------------------------------------------------------------


def test_block_does_not_invoke_wrapped_and_raises(monkeypatch):
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "BLOCK",
            "reason": "BAA required",
            "citation": "HIPAA 164.504(e)",
            "fix_url": "https://app.usevera.xyz/baa",
        }),
    )
    set_default_client(client)

    spy = MagicMock()

    @vera.gate(action_class="commit", tenant="acme")
    def wrapped():
        spy()

    with pytest.raises(PolicyBlock) as ei:
        wrapped()

    spy.assert_not_called()  # Wrapped function MUST NOT run.
    assert ei.value.reason == "BAA required"
    assert ei.value.citation == "HIPAA 164.504(e)"
    assert ei.value.fix_url == "https://app.usevera.xyz/baa"

    # Capture invariant: a "blocked" record is still emitted so the
    # audit trail records the attempt.
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "blocked"
    client.close()


# ---------------------------------------------------------------------------
# 404 fallback (Phase 1 / Phase 2 bridge)
# ---------------------------------------------------------------------------


def test_404_falls_back_to_audit_only_capture_with_warning(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({}, status=404))
    set_default_client(client)

    spy = MagicMock(return_value="ok")

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return spy()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert wrapped() == "ok"

    spy.assert_called_once()
    # One UserWarning per process (this is the first call).
    user_warns = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warns) == 1
    assert "404" in str(user_warns[0].message)

    # ActionRecord still captured.
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "success"
    client.close()


def test_404_warning_only_fires_once_per_process(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({}, status=404))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wrapped()
        wrapped()
    user_warns = [w for w in caught if issubclass(w.category, UserWarning)]
    # Already fired in the first call — subsequent calls suppress it.
    assert len(user_warns) == 0
    client.close()


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------


def test_explicit_tenant_kwarg_wins(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    set_default_tenant("default_t")

    @vera.gate(action_class="x", tenant="explicit_t")
    def wrapped():
        return "ok"

    with vera.tenant("ctx_t"):
        wrapped()
    items = list(client._queue.queue)
    assert items[0]["tenant_id"] == "explicit_t"
    client.close()


def test_context_manager_beats_default(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    set_default_tenant("default_t")

    @vera.gate(action_class="x")
    def wrapped():
        return "ok"

    with vera.tenant("ctx_t"):
        wrapped()
    items = list(client._queue.queue)
    assert items[0]["tenant_id"] == "ctx_t"
    client.close()


def test_default_tenant_used_when_no_other(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)
    set_default_tenant("default_t")

    @vera.gate(action_class="x")
    def wrapped():
        return "ok"

    wrapped()
    items = list(client._queue.queue)
    assert items[0]["tenant_id"] == "default_t"
    client.close()


def test_missing_tenant_raises_tenant_missing_or_invalid(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x")
    def wrapped():
        return "ok"

    with pytest.raises(TenantMissingOrInvalid):
        wrapped()
    client.close()


# ---------------------------------------------------------------------------
# agent_type stamping
# ---------------------------------------------------------------------------


def test_agent_type_per_call_overrides_global(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)
    from vera._context import set_default_agent_type

    set_default_agent_type("global_type")

    @vera.gate(action_class="x", tenant="acme", agent_type="per_call_type")
    def wrapped():
        return "ok"

    wrapped()
    items = list(client._queue.queue)
    assert items[0]["metadata"]["agent_type"] == "per_call_type"
    client.close()


def test_agent_type_falls_back_to_global(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)
    from vera._context import set_default_agent_type

    set_default_agent_type("global_type")

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    items = list(client._queue.queue)
    assert items[0]["metadata"]["agent_type"] == "global_type"
    client.close()


def test_agent_type_absent_when_neither_set(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    items = list(client._queue.queue)
    # No agent_type → key absent from metadata (no empty stub).
    assert "agent_type" not in (items[0].get("metadata") or {})
    client.close()


def test_init_with_agent_type_registers_global(monkeypatch):
    vera.init(
        api_key="al_test_xxx",
        api_url="http://x.test",
        agent_type="my_agent_type",
    )
    assert vera.get_default_agent_type() == "my_agent_type"
    assert vera.resolve_agent_type() == "my_agent_type"
    # Per-call kwarg still wins.
    assert vera.resolve_agent_type(explicit="overridden") == "overridden"


# ---------------------------------------------------------------------------
# Bypass fixture
# ---------------------------------------------------------------------------


def test_bypass_skips_evaluate_call(monkeypatch):
    from vera.testing import bypass_gates_cm

    client = _make_client()
    captured_paths: list[str] = []

    def handler(request):
        captured_paths.append(request.url.path)
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(500, json={"detail": "should not be called"})
        return httpx.Response(200, json={"records": []})

    _install_transport(client, handler)
    set_default_client(client)

    spy = MagicMock(return_value="ok")

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return spy()

    with bypass_gates_cm():
        result = wrapped()

    assert result == "ok"
    spy.assert_called_once()
    # No evaluate call was made (the only path the worker may have hit
    # is /v1/actions/batch — verify the evaluate path was NOT touched).
    assert GATE_EVALUATE_PATH not in captured_paths
    # Capture invariant: bypass still records the action.
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "success"
    client.close()


def test_bypass_via_pytest_fixture_works(monkeypatch, bypass_gates):
    """Demonstrates the actual fixture is wired through pytest_plugin."""
    client = _make_client()

    def handler(request):
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(500)
        return httpx.Response(200, json={"records": []})

    _install_transport(client, handler)
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    # Should not raise even though the mock 500s — bypass skips the call.
    assert wrapped() == "ok"
    client.close()


def test_bypass_clears_after_context_exits(monkeypatch):
    from vera.testing import bypass_gates_cm

    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "BLOCK", "reason": "no"}),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with bypass_gates_cm():
        assert wrapped() == "ok"
    # After exit, the BLOCK ruling should fire normally.
    with pytest.raises(PolicyBlock):
        wrapped()
    client.close()


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------


def test_async_allow_path(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    async def wrapped(x):
        return x * 2

    result = asyncio.run(wrapped(5))
    assert result == 10
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


def test_async_block_path(monkeypatch):
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({"effect": "BLOCK", "reason": "no"}),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    async def wrapped():
        return "should not run"

    with pytest.raises(PolicyBlock):
        asyncio.run(wrapped())
    client.close()


def test_async_require_hitl_captures_then_raises(monkeypatch):
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "REQUIRE_HITL",
            "review_id": "rev_async_1",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    async def wrapped():
        return "draft"

    with pytest.raises(PendingReview) as ei:
        asyncio.run(wrapped())
    assert ei.value.review_id == "rev_async_1"
    items = list(client._queue.queue)
    assert items[0]["result"] == "pending_review"
    client.close()


# ---------------------------------------------------------------------------
# realtime=True kwarg accepted on ALLOW (Wave 2C PR B2 — full coverage in
# tests/test_gate_realtime.py; smoke test here so the legacy decorator
# suite catches any regression that removes the kwarg).
# ---------------------------------------------------------------------------


def test_realtime_kwarg_accepted_on_allow_path(monkeypatch):
    """B2 — realtime=True is no longer NotImplementedError; ALLOW is unchanged."""
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme", realtime=True)
    def wrapped():
        return "ok"

    # ALLOW path is identical regardless of realtime — invoke + capture +
    # return. The deferred-review routing only fires on REQUIRE_HITL.
    assert wrapped() == "ok"
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


# ---------------------------------------------------------------------------
# Capture invariant: failure record always captures even if customer raises
# ---------------------------------------------------------------------------


def test_allow_path_captures_failure(monkeypatch):
    client = _make_client()
    _install_transport(client, _evaluate_handler({"effect": "ALLOW"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        raise ValueError("downstream")

    with pytest.raises(ValueError):
        wrapped()
    items = list(client._queue.queue)
    assert items[0]["result"] == "failure"
    assert items[0]["error_message"] == "downstream"
    client.close()


# ---------------------------------------------------------------------------
# No client configured — exactly mirrors @vera.audit's behavior
# ---------------------------------------------------------------------------


def test_no_client_runs_wrapped_function_without_capturing(monkeypatch):
    set_default_client(None)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return 42

    # No client + no tenant resolver — function still runs (warn-once
    # contract from @vera.audit applies here too).
    assert wrapped() == 42


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — Wire-shape (GateEvaluateRequest) capture
# ---------------------------------------------------------------------------


def _capture_evaluate_handler(
    response_body: dict, status: int = 200, captured: dict | None = None
):
    """Variant of ``_evaluate_handler`` that captures the POST body.

    The ``captured`` dict (caller-provided) is mutated in place with
    the JSON body the SDK sent — lets assertions inspect every key
    the wire shape carries.
    """
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == GATE_EVALUATE_PATH and captured is not None:
            try:
                captured.update(json.loads(request.content))
            except ValueError:
                pass
            return httpx.Response(status, json=response_body)
        if request.url.path == GATE_EVALUATE_PATH:
            return httpx.Response(status, json=response_body)
        return httpx.Response(200, json={"records": []})

    return _h


def test_wire_shape_contains_required_fields():
    """B1 — POST body MUST carry agent_name/action_type/action_name/authorized_by."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": "", "gate_name": "test_gate"},
            captured=captured,
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="commit_chart_note", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    # The four required fields per backend GateEvaluateRequest.
    assert captured["agent_name"] == "test-agent"
    assert captured["action_type"] == "function_call"
    assert captured["action_name"] == "commit_chart_note"
    assert captured["authorized_by"] == "api_key:al_test_…"
    assert captured["tenant_id"] == "acme"
    assert captured["metadata"]["tenant_source"] == "explicit_kwarg"
    # Sanity: legacy field MUST be gone (otherwise the backend 422s on
    # ``extra`` if it ever flips ``extra="forbid"``).
    assert "action_class" not in captured
    client.close()


def test_wire_shape_authorized_by_hint_format():
    """B1 — authorized_by is the API-key tier prefix + ellipsis, never the full key."""
    client = _make_client()  # api_key="al_test_xxx"
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    # 8-char hint + ellipsis with the ``api_key:`` namespace prefix;
    # the full key is NEVER on the wire.
    assert captured["authorized_by"] == "api_key:al_test_…"
    assert "xxx" not in captured["authorized_by"]
    client.close()


def test_wire_shape_authorized_by_sdk_fallback_when_no_key():
    """B1 — authorized_by falls back to the sentinel 'sdk' when no key configured."""
    # Build a client with no api_key (mimics a misconfigured-but-running
    # SDK; the client itself only logs a warning rather than refusing).
    client = VeraClient(
        api_url="http://example.test",
        api_key="",
        agent_name="test-agent",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    assert captured["authorized_by"] == "sdk"
    client.close()


def test_wire_shape_omits_optional_fields_when_unset():
    """B1 — optional kwargs default to absence, not null."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    wrapped()
    # Optional fields must be absent (not None) so the backend's
    # ``Optional[str]`` defaults take over instead of carrying ``null``.
    assert "agent_id" not in captured
    assert "data_subject_id" not in captured
    assert "target_system" not in captured
    assert "target_resource" not in captured
    assert "action_description" not in captured
    client.close()


def test_wire_shape_propagates_new_decorator_kwargs():
    """B1 — new optional kwargs surface on the wire when supplied."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(
        action_class="x",
        tenant="acme",
        agent_id="ag_123",
        data_subject_id="patient_abc",
        target_system="EHR",
        target_resource="encounter:789",
        action_description="commit chart note draft",
    )
    def wrapped():
        return "ok"

    wrapped()
    assert captured["agent_id"] == "ag_123"
    assert captured["data_subject_id"] == "patient_abc"
    assert captured["target_system"] == "EHR"
    assert captured["target_resource"] == "encounter:789"
    assert captured["action_description"] == "commit chart note draft"
    client.close()


def test_wire_shape_agent_type_rides_in_metadata():
    """B1 — legacy agent_type stays nested in metadata (no top-level slot)."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(
        action_class="x",
        tenant="acme",
        agent_type="clinical_summarizer",
    )
    def wrapped():
        return "ok"

    wrapped()
    # Backend GateEvaluateRequest has no top-level agent_type — it
    # rides in metadata (and would be dropped by ``extra="ignore"``
    # if we tried to top-level it).
    assert "agent_type" not in captured
    assert captured["metadata"]["agent_type"] == "clinical_summarizer"
    client.close()


def test_wire_shape_async_path_matches_sync():
    """B1 — async decorator sends the same wire shape as sync."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler(
            {"effect": "allow", "reason": ""}, captured=captured
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    async def wrapped():
        return "ok"

    asyncio.run(wrapped())
    assert captured["agent_name"] == "test-agent"
    assert captured["action_type"] == "function_call"
    assert captured["action_name"] == "x"
    assert captured["authorized_by"] == "api_key:al_test_…"
    client.close()


def test_missing_agent_name_raises_actionable_error():
    """B1 — empty client.agent_name raises with actionable copy (not a 422)."""
    client = VeraClient(
        api_url="http://example.test",
        api_key="al_test_xxx",
        agent_name="",  # explicit empty — the failure case.
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )
    _install_transport(client, _evaluate_handler({"effect": "allow"}))
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with pytest.raises(VeraClientError) as ei:
        wrapped()
    assert "agent_name" in str(ei.value)
    client.close()


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — 404 fallback regression (new wire shape still sent)
# ---------------------------------------------------------------------------


def test_404_fallback_still_sends_new_wire_shape():
    """B1 — 404 fallback fires regardless of body shape; new keys still sent."""
    client = _make_client()
    captured: dict = {}
    _install_transport(
        client,
        _capture_evaluate_handler({}, status=404, captured=captured),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        assert wrapped() == "ok"

    # Wire shape regression guard: even though the backend 404s, the
    # request the SDK SENT must carry the new keys (so the moment a
    # post-#212 backend lands, the same code path produces a valid body).
    assert "agent_name" in captured
    assert "action_type" in captured
    assert "action_name" in captured
    assert "authorized_by" in captured
    client.close()


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — Ruling routing end-to-end (new exception attrs)
# ---------------------------------------------------------------------------


def test_lowercase_effect_allow_routes_correctly():
    """B1 — #212 ships effect=allow (lowercase); the SDK normalises and routes."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "allow",
            "reason": "",
            "gate_name": "stub_allow",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return 99

    assert wrapped() == 99
    items = list(client._queue.queue)
    assert items[0]["result"] == "success"
    client.close()


def test_require_hitl_carries_full_ruling_attrs():
    """B1 — PendingReview exposes gate_name/reason/reason_detail/citation."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "require_hitl",
            "review_id": "rev_123",
            "required_role": "attending_physician",
            "reason": "sensitive_change_attending_required",
            "reason_detail": (
                "Final HPI section edited by non-attending agent"
            ),
            "citation": "HIPAA § 164.524",
            "gate_name": "chart_note_commit_attending_required",
            "fix_url": "https://app.usevera.xyz/reviews/rev_123",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="commit", tenant="acme")
    def commit():
        return "draft"

    with pytest.raises(PendingReview) as ei:
        commit()
    assert ei.value.review_id == "rev_123"
    assert ei.value.required_role == "attending_physician"
    assert ei.value.reason == "sensitive_change_attending_required"
    assert ei.value.reason_detail == (
        "Final HPI section edited by non-attending agent"
    )
    assert ei.value.citation == "HIPAA § 164.524"
    assert ei.value.gate_name == "chart_note_commit_attending_required"
    assert ei.value.fix_url == "https://app.usevera.xyz/reviews/rev_123"
    client.close()


def test_block_carries_full_ruling_attrs():
    """B1 — PolicyBlock exposes gate_name/reason_detail/required_role."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "block",
            "reason": "controlled_substance_detected",
            "reason_detail": (
                "Schedule II opioid detected in prescription draft"
            ),
            "citation": "21 CFR § 1306.05",
            "gate_name": "controlled_substance_block",
            "required_role": "dea_authorized",
            "fix_url": "https://app.usevera.xyz/policy/cs",
            "retryable": False,
        }),
    )
    set_default_client(client)

    spy = MagicMock()

    @vera.gate(action_class="prescribe", tenant="acme")
    def prescribe():
        spy()

    with pytest.raises(PolicyBlock) as ei:
        prescribe()
    spy.assert_not_called()
    assert ei.value.reason == "controlled_substance_detected"
    assert ei.value.reason_detail == (
        "Schedule II opioid detected in prescription draft"
    )
    assert ei.value.citation == "21 CFR § 1306.05"
    assert ei.value.gate_name == "controlled_substance_block"
    assert ei.value.required_role == "dea_authorized"
    assert ei.value.fix_url == "https://app.usevera.xyz/policy/cs"
    assert ei.value.retryable is False
    client.close()


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — Defensive PHI redaction on reason_detail
# ---------------------------------------------------------------------------


def test_reason_detail_phi_shape_redacted_on_pending_review():
    """B1 — backend leaking PHI-shaped reason_detail must NOT reach the customer."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "require_hitl",
            "review_id": "rev_x",
            "reason": "sensitive_edit",
            # Whitespace + digits → likely PHI (defensive heuristic trips).
            "reason_detail": "John Doe 1972-03-14",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "draft"

    with pytest.raises(PendingReview) as ei:
        wrapped()
    assert ei.value.reason_detail == (
        "(redacted: reason_detail matched PHI-shape heuristic)"
    )
    assert "John Doe" not in str(ei.value)
    assert "1972-03-14" not in str(ei.value)
    client.close()


def test_reason_detail_phi_shape_redacted_on_policy_block():
    """B1 — PHI redaction also runs on BLOCK rulings."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "block",
            "reason": "policy_violation",
            "reason_detail": "Patient 12345 admitted",  # whitespace + digits
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with pytest.raises(PolicyBlock) as ei:
        wrapped()
    assert ei.value.reason_detail == (
        "(redacted: reason_detail matched PHI-shape heuristic)"
    )
    assert "12345" not in str(ei.value)
    client.close()


def test_reason_detail_safe_value_kept_verbatim():
    """B1 — diagnostic strings without PHI shape survive the redactor."""
    client = _make_client()
    safe_detail = "Outbound payload exceeded the size cap"
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "block",
            "reason": "payload_too_large",
            "reason_detail": safe_detail,
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with pytest.raises(PolicyBlock) as ei:
        wrapped()
    # No digits in the string, so the defensive whitespace+digit
    # heuristic does NOT trip. Diagnostic info is preserved.
    assert ei.value.reason_detail == safe_detail
    client.close()


def test_reason_detail_none_handled():
    """B1 — when the backend omits reason_detail, the attr is None (not redacted)."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler({
            "effect": "block",
            "reason": "no_detail",
        }),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with pytest.raises(PolicyBlock) as ei:
        wrapped()
    assert ei.value.reason_detail is None
    client.close()


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — 422 wire-shape mismatch handling
# ---------------------------------------------------------------------------


def test_422_with_pydantic_validation_envelope_raises_version_skew():
    """B1 — pydantic 422 with no recognised `code` raises actionable version-skew error."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler(
            {
                "detail": [
                    {
                        "loc": ["body", "agent_name"],
                        "msg": "field required",
                        "type": "value_error.missing",
                    },
                ]
            },
            status=422,
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    with pytest.raises(VeraClientError) as ei:
        wrapped()
    # Operator-friendly: the error message must point at the
    # version skew root cause (not the generic VeraValidationError copy).
    msg = str(ei.value).lower()
    assert "version skew" in msg or "pin the sdk" in msg
    assert ei.value.status_code == 422
    client.close()


def test_422_with_known_code_routes_to_domain_exception():
    """B1 — 422 carrying a known `code` keeps routing to its domain class."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler(
            {
                "code": "tenant_malformed",
                "detail": "tenant_id failed regex",
            },
            status=422,
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return "ok"

    # The existing wrap_httpx_error path dispatches on the `code` and
    # raises TenantMissingOrInvalid — must NOT be intercepted by the
    # B1 version-skew path.
    with pytest.raises(TenantMissingOrInvalid):
        wrapped()
    client.close()


def test_422_async_version_skew_raises():
    """B1 — async path also surfaces the version-skew error."""
    client = _make_client()
    _install_transport(
        client,
        _evaluate_handler(
            {
                "detail": [
                    {
                        "loc": ["body", "agent_name"],
                        "msg": "field required",
                        "type": "value_error.missing",
                    },
                ]
            },
            status=422,
        ),
    )
    set_default_client(client)

    @vera.gate(action_class="x", tenant="acme")
    async def wrapped():
        return "ok"

    with pytest.raises(VeraClientError) as ei:
        asyncio.run(wrapped())
    assert ei.value.status_code == 422
    client.close()


# ---------------------------------------------------------------------------
# Wave 2B PR B1 — bypass_gates short-circuits BEFORE the new wire-shape builder
# ---------------------------------------------------------------------------


def test_bypass_skips_new_wire_shape_builder():
    """B1 regression — bypass must short-circuit before _build_evaluate_request.

    Risk we guard against: if the order of operations in _sync_call
    were ever reorganised (e.g. moving _build_evaluate_request above
    the bypass check for input validation reasons), a bypass-active
    test would start sending requests AND the new wire-shape builder
    would run even when policy enforcement is off. Assert that under
    `bypass_gates`, the MockTransport sees NO POST to
    /v1/gates/evaluate.
    """
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

    @vera.gate(action_class="x", tenant="acme")
    def wrapped():
        return spy()

    with bypass_gates_cm():
        result = wrapped()

    assert result == "ok"
    spy.assert_called_once()
    # The bypass MUST short-circuit BEFORE the new wire-shape builder
    # runs — no /v1/gates/evaluate POST should have been issued.
    assert GATE_EVALUATE_PATH not in paths_hit
    # Capture invariant still holds: bypass records the action.
    items = list(client._queue.queue)
    assert len(items) == 1
    assert items[0]["result"] == "success"
    client.close()
