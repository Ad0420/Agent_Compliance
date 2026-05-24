"""Integration tests: tenant resolution stamps tenant_id + tenant_source.

Phase 1 PR 7 / Stream D3 test plan row:
"Backend payload stamping — outgoing JSON includes tenant_id; the
source is logged/spooled."

Also covers backward-compat for ``vera.init(default_tenant=...)``:
* ``vera.init(api_key='...')`` (no default_tenant) still works.
* ``vera.init(api_key='...', default_tenant='x')`` registers the default.
"""

from __future__ import annotations

import pytest

import vera
from vera import VeraClient
from vera._context import _current_tenant, set_default_tenant
from vera.errors import TenantMissingOrInvalid


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    # Match the env-pollution clearing from test_init.py so each test
    # starts from a known baseline.
    for var in (
        "VERA_API_KEY",
        "VERA_API_URL",
        "VERA_AGENT_NAME",
        "VERA_AGENT_VERSION",
        "VERA_MODEL_ID",
        "VERA_FRAMEWORK",
        "VERA_DEV",
        "VERA_SPOOL_PATH",
        "VERA_SPOOL_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    vera._initialized_client = None
    vera._initialized_async_client = None
    from vera import decorator as _decorator_mod

    _decorator_mod._default_client = None
    set_default_tenant(None)
    token = _current_tenant.set(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_tenant(None)
        client = vera.get_client()
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        vera._initialized_client = None
        _decorator_mod._default_client = None


def _build_client():
    return VeraClient(
        api_key="al_test_xxx",
        api_url="http://example.test",
        agent_name="test-agent",
    )


# ---------------------------------------------------------------------------
# _build_payload — tenant precedence + provenance on the wire.
# ---------------------------------------------------------------------------


def test_payload_omits_tenant_fields_when_none_resolvable():
    c = _build_client()
    try:
        payload = c._build_payload(action_name="x")
        assert "tenant_id" not in payload
        assert "tenant_source" not in payload
    finally:
        c.close()


def test_payload_stamps_explicit_kwarg():
    c = _build_client()
    try:
        payload = c._build_payload(action_name="x", tenant="explicit_t")
        assert payload["tenant_id"] == "explicit_t"
        assert payload["tenant_source"] == "explicit_kwarg"
    finally:
        c.close()


def test_payload_stamps_from_context_manager():
    c = _build_client()
    try:
        with vera.tenant("ctx_t"):
            payload = c._build_payload(action_name="x")
            assert payload["tenant_id"] == "ctx_t"
            assert payload["tenant_source"] == "context_manager"
    finally:
        c.close()


def test_payload_stamps_from_middleware_source():
    c = _build_client()
    try:
        token = vera.set_tenant("mw_t", source="middleware")
        try:
            payload = c._build_payload(action_name="x")
            assert payload["tenant_id"] == "mw_t"
            assert payload["tenant_source"] == "middleware"
        finally:
            vera.reset_tenant(token)
    finally:
        c.close()


def test_payload_stamps_from_default():
    c = _build_client()
    try:
        set_default_tenant("default_t")
        payload = c._build_payload(action_name="x")
        assert payload["tenant_id"] == "default_t"
        assert payload["tenant_source"] == "default"
    finally:
        c.close()


def test_payload_explicit_kwarg_beats_ctx_mgr_and_middleware():
    c = _build_client()
    try:
        token = vera.set_tenant("mw_t", source="middleware")
        try:
            with vera.tenant("ctx_t"):
                payload = c._build_payload(action_name="x", tenant="explicit_t")
                assert payload["tenant_id"] == "explicit_t"
                assert payload["tenant_source"] == "explicit_kwarg"
        finally:
            vera.reset_tenant(token)
    finally:
        c.close()


def test_payload_ctx_mgr_beats_middleware_and_default():
    c = _build_client()
    try:
        set_default_tenant("default_t")
        token = vera.set_tenant("mw_t", source="middleware")
        try:
            with vera.tenant("ctx_t"):
                payload = c._build_payload(action_name="x")
                # Context manager pushed onto the same ContextVar shadows
                # the middleware binding.
                assert payload["tenant_id"] == "ctx_t"
                assert payload["tenant_source"] == "context_manager"
        finally:
            vera.reset_tenant(token)
    finally:
        c.close()


def test_payload_malformed_explicit_kwarg_raises():
    """Explicit ``tenant=`` with a bad value MUST raise, not silently drop."""
    c = _build_client()
    try:
        with pytest.raises(TenantMissingOrInvalid) as excinfo:
            c._build_payload(action_name="x", tenant="has spaces")
        assert excinfo.value.reason == "malformed"
    finally:
        c.close()


# ---------------------------------------------------------------------------
# enqueue_action — same semantics via the background path.
# ---------------------------------------------------------------------------


def test_enqueue_action_stamps_tenant_from_context():
    c = _build_client()
    try:
        with vera.tenant("ctx_t"):
            c.enqueue_action(action_name="x")
        # Peek into the in-memory queue — it should contain a payload with
        # tenant_id stamped.
        items = list(c._queue.queue)
        assert len(items) == 1
        item = items[0]
        assert item["tenant_id"] == "ctx_t"
        assert item["tenant_source"] == "context_manager"
    finally:
        c.close()


def test_enqueue_action_stamps_explicit_kwarg():
    c = _build_client()
    try:
        c.enqueue_action(action_name="x", tenant="explicit_t")
        items = list(c._queue.queue)
        assert items[0]["tenant_id"] == "explicit_t"
        assert items[0]["tenant_source"] == "explicit_kwarg"
        # ``tenant`` was popped — must NOT appear as a raw key on the payload.
        assert "tenant" not in items[0]
    finally:
        c.close()


def test_enqueue_action_no_tenant_when_unresolvable():
    c = _build_client()
    try:
        c.enqueue_action(action_name="x")
        items = list(c._queue.queue)
        assert "tenant_id" not in items[0]
        assert "tenant_source" not in items[0]
    finally:
        c.close()


def test_enqueue_action_malformed_explicit_kwarg_raises():
    c = _build_client()
    try:
        with pytest.raises(TenantMissingOrInvalid):
            c.enqueue_action(action_name="x", tenant="bad value")
    finally:
        c.close()


# ---------------------------------------------------------------------------
# vera.init(default_tenant=) — backward-compat + registration.
# ---------------------------------------------------------------------------


def test_init_without_default_tenant_still_works():
    """No regression for callers that don't pass default_tenant."""
    client = vera.init(api_key="al_test_xxx", api_url="http://x.test")
    assert isinstance(client, VeraClient)
    # No default set.
    assert vera.get_default_tenant() is None


def test_init_with_default_tenant_registers_it():
    vera.init(
        api_key="al_test_xxx",
        api_url="http://x.test",
        default_tenant="default_tenant_id",
    )
    assert vera.get_default_tenant() == "default_tenant_id"
    # Resolver picks it up.
    assert vera.resolve_tenant() == ("default_tenant_id", "default")


def test_init_with_malformed_default_tenant_raises():
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        vera.init(
            api_key="al_test_xxx",
            api_url="http://x.test",
            default_tenant="has spaces",
        )
    assert excinfo.value.reason == "malformed"
    # No client should be initialised because the bad default was caught
    # BEFORE the client constructor ran.
    assert vera._initialized_client is None
