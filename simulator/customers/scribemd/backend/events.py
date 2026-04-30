"""In-memory pub/sub bus for SSE event fan-out.

Each encounter has its own queue per subscriber. The workflow runner
publishes; the SSE route subscribes and forwards. Events are also
persisted to the encounter row so reconnecting clients can replay history
before the live tail.

Single-process only. Fine for the demo bench. A real deployment would
back this with redis pub/sub or postgres LISTEN/NOTIFY.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator


# An "event" on the bus is just `(event_type: str, payload: dict)`.
Event = tuple[str, dict]


class EventBus:
    """One bus per process; one set of subscriber queues per encounter."""

    def __init__(self) -> None:
        # encounter_id -> list of asyncio.Queue, one per live subscriber
        self._subscribers: dict[str, list[asyncio.Queue[Event | None]]] = defaultdict(list)
        # Encounters that have closed their stream (terminal event published).
        self._closed: set[str] = set()

    def publish(self, encounter_id: str, event_type: str, payload: dict) -> None:
        """Fan an event out to every live subscriber. Safe to call from the
        running event loop (route handlers, lifespan tasks).

        Note: this is the *event-loop-side* publish. Workers running in a
        thread must hop back via `loop.call_soon_threadsafe(bus.publish, ...)`.
        """
        for q in list(self._subscribers.get(encounter_id, [])):
            # `put_nowait` is safe — queues are unbounded.
            q.put_nowait((event_type, payload))

    def close(self, encounter_id: str) -> None:
        """Signal no further events will arrive. Each subscriber gets a
        `None` sentinel so its iterator can finish cleanly. Subsequent
        subscribers replay from history then immediately see the close."""
        self._closed.add(encounter_id)
        for q in list(self._subscribers.get(encounter_id, [])):
            q.put_nowait(None)

    def is_closed(self, encounter_id: str) -> bool:
        return encounter_id in self._closed

    async def subscribe(self, encounter_id: str) -> AsyncIterator[Event]:
        """Yield events for `encounter_id` until the stream is closed."""
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subscribers[encounter_id].append(q)
        try:
            # If the workflow already finished before this subscriber arrived,
            # don't block forever — let the caller replay history and exit.
            if encounter_id in self._closed:
                return
            while True:
                item = await q.get()
                if item is None:
                    return
                yield item
        finally:
            try:
                self._subscribers[encounter_id].remove(q)
            except ValueError:
                pass


# Module-level bus instance — single process, single bus.
_BUS = EventBus()


def get_bus() -> EventBus:
    return _BUS


def reset_bus_for_tests() -> None:
    """Replace the module-level bus with a fresh one. Tests call this between
    cases so subscribers from one test don't leak into another."""
    global _BUS
    _BUS = EventBus()
