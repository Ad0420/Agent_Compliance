"""Tests for the tenant resolver (Phase 1 PR 7 / Stream D3).

Covers the resolver primitives in :mod:`vera._context`:

* Precedence: explicit kwarg > context manager > middleware > default > raise.
* Format validation against ``^[a-zA-Z0-9_-]{1,64}$``.
* ContextVar isolation across :func:`asyncio.create_task`.
* Thread-pool propagation requires explicit :func:`copy_context_to_thread`
  (Codex F4).
"""

from __future__ import annotations

import asyncio
import contextvars

import pytest

import vera
from vera._context import (
    _current_tenant,
    copy_context_to_thread,
    get_tenant,
    reset_tenant,
    resolve_tenant,
    set_default_tenant,
    set_tenant,
    tenant,
)
from vera.errors import TenantMissingOrInvalid


@pytest.fixture(autouse=True)
def _reset_tenant_state():
    """Clear the ContextVar + process-level default between tests."""
    set_default_tenant(None)
    # Reset the ContextVar by setting + resetting via a sentinel — the
    # cleanest way to clear the value without losing the ContextVar
    # identity (which would break references held by middleware).
    token = _current_tenant.set(None)
    try:
        yield
    finally:
        _current_tenant.reset(token)
        set_default_tenant(None)


# ---------------------------------------------------------------------------
# Precedence — explicit kwarg > context manager > middleware > default.
# ---------------------------------------------------------------------------


def test_explicit_kwarg_wins_over_middleware():
    """Middleware sets A; explicit kwarg B wins."""
    token = set_tenant("A", source="middleware")
    try:
        tid, src = resolve_tenant(explicit="B")
        assert tid == "B"
        assert src == "explicit_kwarg"
    finally:
        reset_tenant(token)


def test_middleware_wins_when_no_explicit():
    """Middleware sets A; no kwarg → A with source middleware."""
    token = set_tenant("A", source="middleware")
    try:
        tid, src = resolve_tenant()
        assert tid == "A"
        assert src == "middleware"
    finally:
        reset_tenant(token)


def test_explicit_kwarg_wins_over_context_manager():
    """Context manager sets C; explicit B wins."""
    with tenant("C"):
        tid, src = resolve_tenant(explicit="B")
        assert tid == "B"
        assert src == "explicit_kwarg"


def test_context_manager_wins_when_no_explicit():
    """Context manager sets C; resolve returns C with source context_manager."""
    with tenant("C"):
        tid, src = resolve_tenant()
        assert tid == "C"
        assert src == "context_manager"


def test_default_used_when_nothing_else():
    """Process-level default set; no context → returns default."""
    set_default_tenant("D")
    tid, src = resolve_tenant()
    assert tid == "D"
    assert src == "default"


def test_context_overrides_default():
    """Process default set, but a context-bound tenant takes precedence."""
    set_default_tenant("D")
    with tenant("C"):
        tid, src = resolve_tenant()
        assert tid == "C"
        assert src == "context_manager"


def test_raises_when_no_tenant_resolvable():
    """No context, no default → TenantMissingOrInvalid(reason='missing')."""
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        resolve_tenant()
    assert excinfo.value.reason == "missing"


def test_nested_context_managers_shadow_correctly():
    """Inner ``with`` shadows outer; outer restored on exit."""
    with tenant("outer"):
        assert resolve_tenant() == ("outer", "context_manager")
        with tenant("inner"):
            assert resolve_tenant() == ("inner", "context_manager")
        # Inner exited — outer restored.
        assert resolve_tenant() == ("outer", "context_manager")


# ---------------------------------------------------------------------------
# Validation — ^[a-zA-Z0-9_-]{1,64}$.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "good",
    [
        "valid_id_42",
        "cleveland_clinic",
        "a",
        "A-B-C",
        "x" * 64,
        "_leading-underscore",
        "123",
    ],
)
def test_valid_tenant_ids_accepted(good):
    token = set_tenant(good)
    try:
        assert get_tenant() == (good, "middleware")
    finally:
        reset_tenant(token)


@pytest.mark.parametrize(
    "bad",
    [
        "Has Spaces",
        "x" * 65,
        "",
        "contains/slash",
        "with.dot",
        "tab\there",
        "newline\nhere",
        "unicode-ñ",
    ],
)
def test_malformed_tenant_ids_rejected_at_set_tenant(bad):
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        set_tenant(bad)
    assert excinfo.value.reason == "malformed"


@pytest.mark.parametrize("bad", ["Has Spaces", "x" * 65, "", "with/slash"])
def test_malformed_rejected_in_context_manager(bad):
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        with tenant(bad):  # noqa: SIM117 — test of the failure path
            pass
    assert excinfo.value.reason == "malformed"


@pytest.mark.parametrize("bad", ["Has Spaces", "x" * 65, "", "with/slash"])
def test_malformed_rejected_in_set_default_tenant(bad):
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        set_default_tenant(bad)
    assert excinfo.value.reason == "malformed"


@pytest.mark.parametrize("bad", ["Has Spaces", "x" * 65, "", "with/slash"])
def test_malformed_rejected_in_resolve_tenant_explicit(bad):
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        resolve_tenant(explicit=bad)
    assert excinfo.value.reason == "malformed"


def test_non_string_tenant_id_rejected():
    """Non-str values raise malformed (no implicit stringification)."""
    with pytest.raises(TenantMissingOrInvalid) as excinfo:
        set_tenant(12345)  # type: ignore[arg-type]
    assert excinfo.value.reason == "malformed"


def test_set_default_tenant_none_clears_default():
    set_default_tenant("D")
    assert get_tenant() == ("D", "default")
    set_default_tenant(None)
    assert get_tenant() is None


# ---------------------------------------------------------------------------
# ContextVar isolation across asyncio tasks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contextvar_propagates_to_create_task():
    """Tenant set in parent task is visible in child task (snapshot)."""
    token = set_tenant("parent_tenant")
    try:
        result: list = []

        async def child():
            result.append(get_tenant())

        await asyncio.create_task(child())
        assert result == [("parent_tenant", "middleware")]
    finally:
        reset_tenant(token)


@pytest.mark.asyncio
async def test_child_task_set_does_not_leak_to_parent():
    """Setting in a child task must NOT mutate the parent's context."""
    token = set_tenant("parent_tenant")
    try:

        async def child():
            # Each task gets its own ContextVar binding stack; setting
            # here should not affect the parent.
            set_tenant("child_tenant")
            assert get_tenant() == ("child_tenant", "middleware")

        await asyncio.create_task(child())
        # Parent's view is unchanged.
        assert get_tenant() == ("parent_tenant", "middleware")
    finally:
        reset_tenant(token)


# ---------------------------------------------------------------------------
# Codex F4 — thread-pool propagation requires explicit helper.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_executor_does_NOT_propagate_by_default():
    """Confirms the gotcha: ``loop.run_in_executor`` sees a fresh context.

    Note: ``asyncio.to_thread`` (added in Python 3.9) internally calls
    ``contextvars.copy_context()`` and DOES propagate. The raw
    ``loop.run_in_executor`` path does not, and neither does FastAPI
    ``BackgroundTasks`` when the task body is a sync function — those
    are the two real-world cases the helper exists to bridge.
    """
    loop = asyncio.get_event_loop()
    token = set_tenant("main_tenant")
    try:
        result = await loop.run_in_executor(None, get_tenant)
        assert result is None  # gotcha confirmed
    finally:
        reset_tenant(token)


@pytest.mark.asyncio
async def test_copy_context_to_thread_bridges_run_in_executor():
    """``copy_context_to_thread`` makes run_in_executor see the parent context."""
    loop = asyncio.get_event_loop()
    token = set_tenant("main_tenant")
    try:
        result = await loop.run_in_executor(
            None, copy_context_to_thread(get_tenant)
        )
        assert result == ("main_tenant", "middleware")
    finally:
        reset_tenant(token)


@pytest.mark.asyncio
async def test_copy_context_to_thread_passes_args_and_kwargs():
    """Helper forwards args/kwargs to the wrapped callable."""

    def add(a, b, *, scale=1):
        # Read a ContextVar to also prove the snapshot landed.
        tid_pair = get_tenant()
        return (a + b) * scale, tid_pair

    loop = asyncio.get_event_loop()
    token = set_tenant("ctx")
    try:
        runner = copy_context_to_thread(add, 2, 3, scale=10)
        val, ctx = await loop.run_in_executor(None, runner)
        assert val == 50
        assert ctx == ("ctx", "middleware")
    finally:
        reset_tenant(token)


def test_copy_context_to_thread_snapshots_at_call_site_not_runtime():
    """Snapshot captures the context at the moment the closure is built."""
    token = set_tenant("at_snapshot_time")
    try:
        runner = copy_context_to_thread(get_tenant)
    finally:
        reset_tenant(token)

    # Parent's tenant has been reset, but the snapshot inside the
    # closure still carries the value.
    assert get_tenant() is None
    assert runner() == ("at_snapshot_time", "middleware")


def test_copy_context_to_thread_with_threadpoolexecutor():
    """Concrete demo: concurrent.futures.ThreadPoolExecutor needs the bridge."""
    from concurrent.futures import ThreadPoolExecutor

    token = set_tenant("submitter_tenant")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            # Without the helper, the worker sees None.
            unwrapped = pool.submit(get_tenant).result()
            assert unwrapped is None
            # With the helper, the snapshot is replayed in the worker.
            wrapped = pool.submit(copy_context_to_thread(get_tenant)).result()
            assert wrapped == ("submitter_tenant", "middleware")
    finally:
        reset_tenant(token)


# ---------------------------------------------------------------------------
# Public re-exports — make sure ``vera.tenant`` / ``vera.set_tenant`` etc.
# are importable from the top-level package.
# ---------------------------------------------------------------------------


def test_top_level_exports():
    assert vera.tenant is tenant
    assert vera.set_tenant is set_tenant
    assert vera.reset_tenant is reset_tenant
    assert vera.get_tenant is get_tenant
    assert vera.set_default_tenant is set_default_tenant
    assert vera.resolve_tenant is resolve_tenant
    assert vera.copy_context_to_thread is copy_context_to_thread
