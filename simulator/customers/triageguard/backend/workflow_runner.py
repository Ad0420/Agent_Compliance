"""Wraps the sync `run_session` workflow as a background asyncio task.

Wiring rules (mirrors ScribeMD's verbatim):
  * The workflow is sync (calls real LLMs + Vera HTTP). We run it via
    `asyncio.to_thread(...)` so the event loop stays responsive.
  * Each `on_step(name, payload)` from the workflow has to:
      (a) get fanned out on the in-process pub/sub bus (event-loop-side), and
      (b) get persisted into the session row's `events` column (DB call).
    The workflow runs in a worker thread, so we hop back to the loop
    with `loop.call_soon_threadsafe`. The DB persist itself is scheduled
    via `asyncio.run_coroutine_threadsafe` so we get an awaitable back.
  * The nurse decision is bridged with a `threading.Event` paired with
    a one-shot `dict` for the captured decision. The HTTP route handler
    pokes both via `loop.call_soon_threadsafe(...)`. Picked the simplest
    correct primitive — the worker thread blocks on `Event.wait(timeout=...)`
    and the route handler resolves it. No queues, no extra layers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from simulator.customers.triageguard.agents.red_flag_detector import (
    RedFlagDetectorAgent,
)
from simulator.customers.triageguard.agents.triage_classifier import (
    TriageClassifierAgent,
)
from simulator.customers.triageguard.backend.config import get_settings
from simulator.customers.triageguard.backend.db import _ensure_engine
from simulator.customers.triageguard.backend.events import EventBus, get_bus
from simulator.customers.triageguard.backend.models import TriageSession
from simulator.customers.triageguard.fixtures.sessions import (
    ALL_SESSIONS,
    TriageFixture,
)
from simulator.customers.triageguard.workflows.session import run_session
from simulator.shared.fixtures.patients import make_patient


logger = logging.getLogger(__name__)


# ── Hooks (so tests can swap real Vera/LLM clients for stubs) ───────────────
#
# The smoke test reaches in and replaces these two callables. In Mode A
# they default to the real `simulator.shared` factories.


def _default_get_vera_client(*, agent_name: str, model_id: Optional[str] = None,
                             framework: Optional[str] = None):
    from simulator.shared.vera_setup import get_client

    settings = get_settings()
    try:
        return get_client(
            settings.vera_customer_slug,
            agent_name=agent_name,
            model_id=model_id,
            framework=framework,
        )
    except RuntimeError as exc:
        # Surface a friendly error if the org wasn't bootstrapped.
        raise RuntimeError(
            f"{exc} (Set VERA_API_KEY_TRIAGEGUARD or run "
            "`python -m simulator.scripts.bootstrap_orgs` to bootstrap.)"
        ) from exc


def _default_get_llm_provider(name: str):
    from simulator.shared.llm import get_provider

    return get_provider(name, mode="A")


# Test hooks — monkeypatch these directly.
get_vera_client: Callable[..., Any] = _default_get_vera_client
get_llm_provider: Callable[[str], Any] = _default_get_llm_provider


# ── Pending-decision registry ───────────────────────────────────────────────


@dataclass
class _PendingDecision:
    session_id: str
    approval_id: str
    event: threading.Event
    decision: dict | None = None  # {"decision", "nurse", "note"} once set


# vera_approval_id -> _PendingDecision
_PENDING: dict[str, _PendingDecision] = {}
_PENDING_LOCK = threading.Lock()


def get_pending(approval_id: str) -> Optional[_PendingDecision]:
    with _PENDING_LOCK:
        return _PENDING.get(approval_id)


def _register_pending(approval_id: str, session_id: str) -> _PendingDecision:
    pending = _PendingDecision(
        session_id=session_id,
        approval_id=approval_id,
        event=threading.Event(),
    )
    with _PENDING_LOCK:
        _PENDING[approval_id] = pending
    return pending


def _unregister_pending(approval_id: str) -> None:
    with _PENDING_LOCK:
        _PENDING.pop(approval_id, None)


def resolve_pending(
    approval_id: str, decision: str, nurse: str, note: Optional[str]
) -> bool:
    """Called by the review route handler. Pokes the worker thread.

    Returns True if a pending decision was found and resolved, False
    otherwise.
    """
    pending = get_pending(approval_id)
    if pending is None:
        return False
    pending.decision = {"decision": decision, "nurse": nurse, "note": note}
    pending.event.set()
    return True


def reset_pending_for_tests() -> None:
    with _PENDING_LOCK:
        _PENDING.clear()


# ── DB helpers ──────────────────────────────────────────────────────────────


async def _persist_event(session_db_id: str, event_type: str, payload: dict) -> None:
    """Append `(event_type, payload)` to the session's events column and
    bump `last_event`. Called from the running event loop only.
    """
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(TriageSession, session_db_id)
        if row is None:
            return
        history = list(row.events or [])
        history.append({"event": event_type, "data": payload})
        row.events = history
        row.last_event = event_type
        # Capture vera_approval_id as soon as we see it so the GET
        # endpoint can show it before the workflow finishes.
        if event_type == "nurse_review_requested" and payload.get("approval_id"):
            row.vera_approval_id = payload["approval_id"]
        await session.commit()


async def _set_session_status(
    session_db_id: str,
    status: str,
    *,
    terminal_outcome: dict | None = None,
    record_ids: list[str] | None = None,
) -> None:
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(TriageSession, session_db_id)
        if row is None:
            return
        row.status = status
        if terminal_outcome is not None:
            row.terminal_outcome = terminal_outcome
        if record_ids is not None:
            row.vera_record_ids = list(record_ids)
        await session.commit()


# ── Resolving the session input to a fixture-shaped object ──────────────────


def _resolve_fixture(
    *,
    fixture_key: Optional[str],
    custom: Optional[dict],
    session_db_id: str,
) -> TriageFixture:
    if fixture_key is not None:
        return ALL_SESSIONS[fixture_key]()

    assert custom is not None
    patient = make_patient(seed=hash(session_db_id) % (2**31))
    return TriageFixture(
        session_id=f"ses_custom_{session_db_id[:8]}",
        patient=patient,
        chief_complaint=custom["chief_complaint"],
        symptoms=custom["symptoms"],
        expected_classifier_level="virtual_visit",
        expected_red_flag=False,
        expected_recommended_override=None,
    )


def patient_safe_summary(fixture: TriageFixture) -> dict:
    return {
        **fixture.patient.safe_summary(),
        "chief_complaint": fixture.chief_complaint,
    }


# ── Public: kick off a workflow ─────────────────────────────────────────────


def new_session_id() -> str:
    return uuid.uuid4().hex


async def start_workflow(
    *,
    session_db_id: str,
    fixture_key: Optional[str],
    custom: Optional[dict],
    bus: EventBus | None = None,
) -> asyncio.Task:
    """Spawn the background task that runs the workflow end-to-end.

    Returns the task; callers can keep it for cancellation if needed.
    """
    bus = bus or get_bus()
    loop = asyncio.get_running_loop()

    fixture = _resolve_fixture(
        fixture_key=fixture_key, custom=custom, session_db_id=session_db_id
    )

    # Eagerly seed the session row's patient_summary so a refresh while
    # running shows the patient even before the first event lands.
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(TriageSession, session_db_id)
        if row is not None and row.patient_summary is None:
            row.patient_summary = patient_safe_summary(fixture)
            await session.commit()

    task = asyncio.create_task(
        _run_workflow(
            session_db_id=session_db_id,
            fixture=fixture,
            bus=bus,
            loop=loop,
        )
    )
    return task


async def _run_workflow(
    *,
    session_db_id: str,
    fixture: TriageFixture,
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Build agents/clients on the loop side, then drop into a thread to
    actually run the sync workflow. Errors flip the session to `error`
    and emit an `error` event so the SSE client sees the failure."""

    record_ids_collected: list[str] = []

    # ── Build providers + clients ──
    try:
        classifier_provider = get_llm_provider("openai")
        detector_provider = get_llm_provider("anthropic")
        classifier_vera = get_vera_client(
            agent_name=TriageClassifierAgent.AGENT_NAME,
            model_id=classifier_provider.model,
            framework=TriageClassifierAgent.FRAMEWORK,
        )
        detector_vera = get_vera_client(
            agent_name=RedFlagDetectorAgent.AGENT_NAME,
            model_id=detector_provider.model,
            framework=RedFlagDetectorAgent.FRAMEWORK,
        )
        routing_vera = get_vera_client(
            agent_name="triageguard-routing-committer",
            framework="triageguard-pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        await _emit_error(bus, session_db_id, "setup_failed", str(exc))
        await _set_session_status(
            session_db_id, "error",
            terminal_outcome={"error": str(exc), "phase": "setup"},
        )
        bus.close(session_db_id)
        return

    classifier = TriageClassifierAgent(llm=classifier_provider, vera=classifier_vera)
    detector = RedFlagDetectorAgent(llm=detector_provider, vera=detector_vera)

    # ── Build the on_step callback (worker-thread side) ──
    #
    # Calls into the loop must use call_soon_threadsafe (sync) or
    # run_coroutine_threadsafe (async). Persistence is a coroutine, so
    # we schedule it back on the loop.

    def on_step(name: str, payload: dict) -> None:
        # Capture record IDs as we go so we can persist them as
        # terminal state even if the workflow fails late.
        if isinstance(payload, dict):
            rid = payload.get("record_id")
            if rid:
                record_ids_collected.append(rid)

        loop.call_soon_threadsafe(bus.publish, session_db_id, name, payload)
        # Persist the event. Concurrent commits on a single row are fine
        # here because events arrive sequentially from one worker.
        future = asyncio.run_coroutine_threadsafe(
            _persist_event(session_db_id, name, payload), loop
        )
        try:
            future.result(timeout=10)
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist event %s for %s", name, session_db_id)

        # When nurse_review_requested fires, flip status.
        if name == "nurse_review_requested":
            asyncio.run_coroutine_threadsafe(
                _set_session_status(session_db_id, "awaiting_review"),
                loop,
            ).result(timeout=10)

    # ── Build the nurse callback (worker-thread side) ──
    settings = get_settings()

    def nurse_callback(approval: dict) -> tuple[str, str, Optional[str]]:
        approval_id = approval["id"]
        pending = _register_pending(approval_id, session_db_id)
        try:
            got_decision = pending.event.wait(
                timeout=settings.review_timeout_seconds
            )
            if not got_decision or pending.decision is None:
                # Treat a timeout as an escalate so the workflow finishes
                # cleanly and the patient gets routed to a higher acuity
                # rather than left hanging on a low-acuity AI call. Safer
                # than auto-confirming a possibly-wrong AI level.
                return (
                    "escalate",
                    "system",
                    "Nurse review timed out — auto-escalating per policy.",
                )
            d = pending.decision
            return (d["decision"], d["nurse"], d.get("note"))
        finally:
            _unregister_pending(approval_id)

    # ── Run the workflow in a thread ──
    try:
        result = await asyncio.to_thread(
            run_session,
            fixture=fixture,
            classifier=classifier,
            detector=detector,
            routing_vera=routing_vera,
            nurse_callback=nurse_callback,
            review_timeout_seconds=settings.review_timeout_seconds,
            on_step=on_step,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("workflow failed for %s", session_db_id)
        await _emit_error(bus, session_db_id, "workflow_failed", str(exc))
        await _set_session_status(
            session_db_id, "error",
            terminal_outcome={"error": str(exc), "phase": "workflow"},
            record_ids=record_ids_collected,
        )
        bus.close(session_db_id)
        for client in (classifier_vera, detector_vera, routing_vera):
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        return

    # ── Final state ──
    if result.routing_committed:
        terminal_status = "routed"
    else:
        terminal_status = "routing_blocked"

    terminal_outcome = {
        "session_id": result.session_id,
        "initial_level": result.initial_level,
        "final_level": result.final_level,
        "classifier_reasoning": result.classifier_reasoning,
        "red_flag_fired": result.red_flag_fired,
        "red_flag_terms": result.red_flag_terms,
        "recommended_override": result.recommended_override,
        "risk_tier": result.risk_tier,
        "approval_id": result.approval_id,
        "nurse_status": result.nurse_status,
        "routing_committed": result.routing_committed,
    }
    await _set_session_status(
        session_db_id,
        terminal_status,
        terminal_outcome=terminal_outcome,
        record_ids=result.record_ids,
    )

    for client in (classifier_vera, detector_vera, routing_vera):
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    bus.close(session_db_id)


async def _emit_error(
    bus: EventBus, session_db_id: str, code: str, message: str
) -> None:
    payload = {"code": code, "message": message, "ts": int(time.time())}
    bus.publish(session_db_id, "error", payload)
    await _persist_event(session_db_id, "error", payload)


# ── Test helpers ────────────────────────────────────────────────────────────


def install_test_factories(
    *,
    vera_factory: Callable[..., Any],
    llm_factory: Callable[[str], Any],
) -> None:
    """Replace the module-level factories. Smoke test calls this in setup."""
    global get_vera_client, get_llm_provider
    get_vera_client = vera_factory
    get_llm_provider = llm_factory


def restore_default_factories() -> None:
    global get_vera_client, get_llm_provider
    get_vera_client = _default_get_vera_client
    get_llm_provider = _default_get_llm_provider
