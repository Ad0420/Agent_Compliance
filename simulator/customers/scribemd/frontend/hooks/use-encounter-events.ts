"use client";

/**
 * `useEncounterEvents(encounterId)` — subscribes to the SSE stream at
 * `GET /api/events/{id}` and returns a live, ordered array of events plus
 * a connection status.
 *
 * Behaviour:
 * - Opens an `EventSource` with `withCredentials: true` so the session
 *   cookie travels cross-origin.
 * - Listens for the named events from `contract.md` (`draft_started`,
 *   `draft_complete`, `orders_extracted`, `approval_requested`,
 *   `approval_decided`, `chart_committed`, `chart_blocked`, `error`).
 * - Closes cleanly on any terminal event (`chart_committed`,
 *   `chart_blocked`, `error`).
 * - On a network-level `onerror`, transitions to `status: "error"` and
 *   closes — there is no auto-reconnect. Drift is corrected by the
 *   `useEncounter` polling consumer; the SSE channel exists for fidelity,
 *   not durability.
 */

import * as React from "react";

import { apiUrl } from "@/lib/api/client";
import {
  isTerminalEvent,
  type EncounterEvent,
  type EncounterEventType,
} from "@/lib/api/types";

const EVENT_NAMES: EncounterEventType[] = [
  "draft_started",
  "draft_complete",
  "orders_extracted",
  "approval_requested",
  "approval_decided",
  "chart_committed",
  "chart_blocked",
  "error",
];

export type EncounterEventsStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "error";

interface UseEncounterEventsResult {
  events: EncounterEvent[];
  status: EncounterEventsStatus;
  error: Error | null;
}

interface EventsState {
  encounterId: string | null;
  events: EncounterEvent[];
  status: EncounterEventsStatus;
  error: Error | null;
}

const EMPTY_EVENTS_STATE: EventsState = {
  encounterId: null,
  events: [],
  status: "idle",
  error: null,
};

function initialEventsState(encounterId: string | null): EventsState {
  if (!encounterId) return EMPTY_EVENTS_STATE;
  return {
    encounterId,
    events: [],
    status: "connecting",
    error: null,
  };
}

function safeParse(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return { value: parsed };
  } catch {
    return { raw };
  }
}

export function useEncounterEvents(
  encounterId: string | null,
): UseEncounterEventsResult {
  const [state, setState] = React.useState<EventsState>(() =>
    initialEventsState(encounterId),
  );

  // Reset state during render when the caller switches encounter ids.
  if (state.encounterId !== encounterId) {
    setState(initialEventsState(encounterId));
  }

  React.useEffect(() => {
    if (!encounterId) return;

    // Guard against running in a non-DOM environment (SSR, tests).
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      // Defer the state transition so we don't trigger a synchronous
      // cascading render from inside the effect body.
      const handle = queueMicrotask(() => {
        setState((prev) =>
          prev.encounterId === encounterId
            ? {
                ...prev,
                status: "error",
                error: new Error(
                  "EventSource is not available in this environment.",
                ),
              }
            : prev,
        );
      });
      return () => {
        // queueMicrotask returns void, so there's nothing to cancel —
        // the closure simply checks `prev.encounterId` on flush.
        void handle;
      };
    }

    const url = apiUrl(`/api/events/${encodeURIComponent(encounterId)}`);
    const source = new EventSource(url, { withCredentials: true });
    let closed = false;

    const setStatusFor = (
      next: EncounterEventsStatus,
      err: Error | null = null,
    ) => {
      setState((prev) => {
        if (prev.encounterId !== encounterId) return prev;
        return {
          ...prev,
          status: next,
          error: err ?? prev.error,
        };
      });
    };

    const closeStream = (next: EncounterEventsStatus, err: Error | null = null) => {
      if (closed) return;
      closed = true;
      try {
        source.close();
      } catch {
        // EventSource.close() never throws in spec, but be defensive.
      }
      setStatusFor(next, err);
    };

    source.onopen = () => {
      if (closed) return;
      setStatusFor("open");
    };

    source.onerror = () => {
      if (closed) return;
      // EventSource.onerror fires on transient network blips and on the
      // final close after a clean stream end. We don't auto-reconnect —
      // the snapshot poll will fill any gap. Distinguish the "stream
      // already done" case from a true error by checking readyState.
      if (source.readyState === EventSource.CLOSED) {
        // Treat post-terminal close as graceful.
        closeStream("closed");
      } else {
        closeStream("error", new Error("Event stream connection failed."));
      }
    };

    const handleNamed = (name: EncounterEventType) => (raw: MessageEvent) => {
      if (closed) return;
      const payload = safeParse(typeof raw.data === "string" ? raw.data : "");
      setState((prev) => {
        if (prev.encounterId !== encounterId) return prev;
        return { ...prev, events: [...prev.events, { event: name, data: payload }] };
      });
      if (isTerminalEvent(name)) {
        closeStream("closed");
      }
    };

    const listeners: Array<[EncounterEventType, (e: MessageEvent) => void]> = [];
    for (const name of EVENT_NAMES) {
      const fn = handleNamed(name);
      listeners.push([name, fn]);
      source.addEventListener(name, fn as EventListener);
    }

    return () => {
      for (const [name, fn] of listeners) {
        source.removeEventListener(name, fn as EventListener);
      }
      closed = true;
      try {
        source.close();
      } catch {
        // ignore
      }
    };
  }, [encounterId]);

  return { events: state.events, status: state.status, error: state.error };
}
