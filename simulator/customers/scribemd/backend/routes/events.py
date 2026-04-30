"""SSE event-stream route for an encounter."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from simulator.customers.scribemd.backend.auth import require_session
from simulator.customers.scribemd.backend.db import get_session
from simulator.customers.scribemd.backend.events import get_bus
from simulator.customers.scribemd.backend.models import Encounter


router = APIRouter(prefix="/api/events", tags=["events"])


# Final event types — once we emit one of these to a fresh subscriber there
# is nothing else coming.
_TERMINAL = {"chart_committed", "chart_blocked", "error"}


@router.get("/{encounter_id}")
async def stream_events(
    encounter_id: str,
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
):
    row = await session.get(Encounter, encounter_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Encounter not found.")

    history = list(row.events or [])
    bus = get_bus()
    bus_closed = bus.is_closed(encounter_id)

    async def event_source() -> AsyncIterator[dict]:
        # 1. Replay everything we've persisted so far.
        for evt in history:
            yield {
                "event": evt["event"],
                "data": json.dumps(evt["data"]),
            }

        # 2. If the workflow finished before this client connected, history
        #    above is the whole story — exit cleanly.
        if bus_closed:
            return

        # 3. Tail the live bus.
        try:
            async for event_type, payload in bus.subscribe(encounter_id):
                yield {
                    "event": event_type,
                    "data": json.dumps(payload),
                }
                if event_type in _TERMINAL:
                    # The workflow runner will close() the bus too, but
                    # exiting here means a fresh subscriber won't accidentally
                    # block waiting for a sentinel that already passed.
                    return
        except asyncio.CancelledError:
            # Client disconnected. sse-starlette will surface this; just exit.
            return

    return EventSourceResponse(event_source())
