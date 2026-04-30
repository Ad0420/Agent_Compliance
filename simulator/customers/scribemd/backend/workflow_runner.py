"""Wraps the sync `run_encounter` workflow as a background asyncio task.

Wiring rules:
  * The workflow is sync (calls real LLMs + Vera HTTP). We run it via
    `asyncio.to_thread(...)` so the event loop stays responsive.
  * Each `on_step(name, payload)` from the workflow has to:
      (a) get fanned out on the in-process pub/sub bus (event-loop-side), and
      (b) get persisted into the encounter row's `events` column (DB call).
    The workflow runs in a worker thread, so we hop back to the loop with
    `loop.call_soon_threadsafe`. The DB persist itself is scheduled via
    `asyncio.run_coroutine_threadsafe` so we get an awaitable back.
  * The physician decision is bridged with a `threading.Event` paired with
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

from sqlalchemy.ext.asyncio import AsyncSession

from simulator.customers.scribemd.agents.note_drafter import NoteDrafterAgent
from simulator.customers.scribemd.agents.orders_extractor import OrdersExtractorAgent
from simulator.customers.scribemd.backend.config import get_settings
from simulator.customers.scribemd.backend.db import _ensure_engine
from simulator.customers.scribemd.backend.events import EventBus, get_bus
from simulator.customers.scribemd.backend.models import Encounter
from simulator.customers.scribemd.fixtures.encounters import (
    ALL_ENCOUNTERS,
    Encounter as FixtureEncounter,
)
from simulator.customers.scribemd.workflows.encounter import run_encounter
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
            f"{exc} (Set VERA_API_KEY_SCRIBEMD or run "
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
    encounter_id: str
    approval_id: str
    event: threading.Event
    decision: dict | None = None  # {"decision", "approver", "note"} once set


# vera_approval_id -> _PendingDecision
_PENDING: dict[str, _PendingDecision] = {}
_PENDING_LOCK = threading.Lock()


def get_pending(approval_id: str) -> Optional[_PendingDecision]:
    with _PENDING_LOCK:
        return _PENDING.get(approval_id)


def _register_pending(approval_id: str, encounter_id: str) -> _PendingDecision:
    pending = _PendingDecision(
        encounter_id=encounter_id,
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
    approval_id: str, decision: str, approver: str, note: Optional[str]
) -> bool:
    """Called by the approval route handler. Pokes the worker thread.

    Returns True if a pending decision was found and resolved, False otherwise.
    """
    pending = get_pending(approval_id)
    if pending is None:
        return False
    pending.decision = {"decision": decision, "approver": approver, "note": note}
    pending.event.set()
    return True


def reset_pending_for_tests() -> None:
    with _PENDING_LOCK:
        _PENDING.clear()


# ── DB helpers ──────────────────────────────────────────────────────────────


async def _persist_event(encounter_id: str, event_type: str, payload: dict) -> None:
    """Append `(event_type, payload)` to the encounter's events column and
    bump `last_event`. Called from the running event loop only.
    """
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(Encounter, encounter_id)
        if row is None:
            return
        history = list(row.events or [])
        history.append({"event": event_type, "data": payload})
        row.events = history
        row.last_event = event_type
        # Capture vera_approval_id as soon as we see it so the GET endpoint
        # can show it before the workflow finishes.
        if event_type == "approval_requested" and payload.get("approval_id"):
            row.vera_approval_id = payload["approval_id"]
        await session.commit()


async def _set_encounter_status(
    encounter_id: str,
    status: str,
    *,
    terminal_outcome: dict | None = None,
    record_ids: list[str] | None = None,
) -> None:
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(Encounter, encounter_id)
        if row is None:
            return
        row.status = status
        if terminal_outcome is not None:
            row.terminal_outcome = terminal_outcome
        if record_ids is not None:
            row.vera_record_ids = list(record_ids)
        await session.commit()


# ── Resolving the encounter input to a fixture-shaped object ────────────────


def _resolve_fixture_encounter(
    *,
    fixture_key: Optional[str],
    custom: Optional[dict],
    encounter_db_id: str,
) -> FixtureEncounter:
    if fixture_key is not None:
        return ALL_ENCOUNTERS[fixture_key]()

    assert custom is not None
    patient = make_patient(seed=hash(encounter_db_id) % (2**31))
    return FixtureEncounter(
        encounter_id=f"enc_custom_{encounter_db_id[:8]}",
        patient=patient,
        visit_type=custom.get("visit_type", "office"),
        chief_complaint=custom["chief_complaint"],
        transcript=custom["transcript"],
        expected_risk=custom.get("expected_risk", "medium"),
    )


def patient_safe_summary(fix_enc: FixtureEncounter) -> dict:
    return {
        **fix_enc.patient.safe_summary(),
        "chief_complaint": fix_enc.chief_complaint,
        "visit_type": fix_enc.visit_type,
        "expected_risk": fix_enc.expected_risk,
    }


# ── Public: kick off a workflow ─────────────────────────────────────────────


def new_encounter_id() -> str:
    return uuid.uuid4().hex


async def start_workflow(
    *,
    encounter_db_id: str,
    fixture_key: Optional[str],
    custom: Optional[dict],
    bus: EventBus | None = None,
) -> asyncio.Task:
    """Spawn the background task that runs the workflow end-to-end.

    Returns the task; callers can keep it for cancellation if needed.
    """
    bus = bus or get_bus()
    loop = asyncio.get_running_loop()

    fix_enc = _resolve_fixture_encounter(
        fixture_key=fixture_key, custom=custom, encounter_db_id=encounter_db_id
    )

    # Eagerly seed the encounter row's patient_summary so a refresh while
    # running shows the patient even before the first event lands.
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        row = await session.get(Encounter, encounter_db_id)
        if row is not None and row.patient_summary is None:
            row.patient_summary = patient_safe_summary(fix_enc)
            await session.commit()

    task = asyncio.create_task(
        _run_workflow(
            encounter_db_id=encounter_db_id,
            fix_enc=fix_enc,
            bus=bus,
            loop=loop,
        )
    )
    return task


async def _run_workflow(
    *,
    encounter_db_id: str,
    fix_enc: FixtureEncounter,
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Build agents/clients on the loop side, then drop into a thread to
    actually run the sync workflow. Errors flip the encounter to `error`
    and emit an `error` event so the SSE client sees the failure."""

    record_ids_collected: list[str] = []
    terminal_outcome: dict | None = None

    # ── Build providers + clients ──
    try:
        note_provider = get_llm_provider("openai")
        orders_provider = get_llm_provider("anthropic")
        note_vera = get_vera_client(
            agent_name=NoteDrafterAgent.AGENT_NAME,
            model_id=note_provider.model,
            framework=NoteDrafterAgent.FRAMEWORK,
        )
        orders_vera = get_vera_client(
            agent_name=OrdersExtractorAgent.AGENT_NAME,
            model_id=orders_provider.model,
            framework=OrdersExtractorAgent.FRAMEWORK,
        )
        chart_vera = get_vera_client(
            agent_name="scribemd-chart-committer",
            framework="scribemd-pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        await _emit_error(bus, encounter_db_id, "setup_failed", str(exc))
        await _set_encounter_status(
            encounter_db_id, "error",
            terminal_outcome={"error": str(exc), "phase": "setup"},
        )
        bus.close(encounter_db_id)
        return

    drafter = NoteDrafterAgent(llm=note_provider, vera=note_vera)
    extractor = OrdersExtractorAgent(llm=orders_provider, vera=orders_vera)

    # ── Build the on_step callback (worker-thread side) ──
    #
    # Calls into the loop must use call_soon_threadsafe (sync) or
    # run_coroutine_threadsafe (async). Persistence is a coroutine, so we
    # schedule it back on the loop.

    def on_step(name: str, payload: dict) -> None:
        # Capture record IDs as we go so we can persist them as terminal state
        # even if the workflow fails late.
        for key in ("record_id",):
            if isinstance(payload, dict) and key in payload and payload[key]:
                record_ids_collected.append(payload[key])

        loop.call_soon_threadsafe(bus.publish, encounter_db_id, name, payload)
        # Persist the event. fire-and-forget — concurrent commits on a single
        # row are fine here because events arrive sequentially from one worker.
        future = asyncio.run_coroutine_threadsafe(
            _persist_event(encounter_db_id, name, payload), loop
        )
        try:
            future.result(timeout=10)
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist event %s for %s", name, encounter_db_id)

        # When approval_requested fires, flip status. (Same pattern.)
        if name == "approval_requested":
            asyncio.run_coroutine_threadsafe(
                _set_encounter_status(encounter_db_id, "awaiting_approval"),
                loop,
            ).result(timeout=10)

    # ── Build the physician callback (worker-thread side) ──
    settings = get_settings()

    def physician_callback(approval: dict) -> tuple[str, str, Optional[str]]:
        approval_id = approval["id"]
        pending = _register_pending(approval_id, encounter_db_id)
        try:
            got_decision = pending.event.wait(timeout=settings.approval_timeout_seconds)
            if not got_decision or pending.decision is None:
                # Treat a timeout as a rejection so the workflow finishes
                # cleanly rather than blocking forever.
                return ("reject", "system", "Approval timed out waiting for physician.")
            d = pending.decision
            return (d["decision"], d["approver"], d.get("note"))
        finally:
            _unregister_pending(approval_id)

    # ── Run the workflow in a thread ──
    try:
        result = await asyncio.to_thread(
            run_encounter,
            encounter=fix_enc,
            drafter=drafter,
            extractor=extractor,
            chart_vera=chart_vera,
            physician_callback=physician_callback,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            on_step=on_step,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("workflow failed for %s", encounter_db_id)
        await _emit_error(bus, encounter_db_id, "workflow_failed", str(exc))
        await _set_encounter_status(
            encounter_db_id, "error",
            terminal_outcome={"error": str(exc), "phase": "workflow"},
            record_ids=record_ids_collected,
        )
        bus.close(encounter_db_id)
        for client in (note_vera, orders_vera, chart_vera):
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        return

    # ── Final state ──
    if result.chart_committed:
        terminal_status = "committed"
    elif result.approval_status == "auto_committed":
        terminal_status = "auto_committed"
    else:
        terminal_status = "blocked"

    terminal_outcome = {
        "encounter_id": result.encounter_id,
        "approval_status": result.approval_status,
        "chart_committed": result.chart_committed,
        "risk_tier": result.risk_tier,
        "diagnoses": result.diagnoses,
        "medication_orders": result.medication_orders,
        "lab_or_imaging_orders": result.lab_or_imaging_orders,
        "note": result.note,
    }
    await _set_encounter_status(
        encounter_db_id,
        terminal_status,
        terminal_outcome=terminal_outcome,
        record_ids=result.record_ids,
    )

    for client in (note_vera, orders_vera, chart_vera):
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    bus.close(encounter_db_id)


async def _emit_error(bus: EventBus, encounter_id: str, code: str, message: str) -> None:
    payload = {"code": code, "message": message, "ts": int(time.time())}
    bus.publish(encounter_id, "error", payload)
    await _persist_event(encounter_id, "error", payload)


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
