"use client";

/**
 * `useEncounter(id)` — one-shot fetch that auto-polls every 1s while the
 * encounter is non-terminal, then stops.
 *
 * `useStartEncounter()` — exposes a `start(input)` function for the view
 * layer's "begin encounter" affordance.
 *
 * The polling cadence is deliberately blunt: the SSE stream is the
 * recommended live channel; this hook exists for pages where SSE is not
 * appropriate (history pages, refresh-after-decision flows, etc.). The two
 * are kept in sync server-side, so consumers can mix them freely.
 */

import * as React from "react";

import { createEncounter, getEncounter } from "@/lib/api/encounters";
import {
  isTerminalStatus,
  type EncounterSnapshot,
  type StartEncounterInput,
} from "@/lib/api/types";

const POLL_INTERVAL_MS = 1000;

interface UseEncounterResult {
  data: EncounterSnapshot | null;
  isLoading: boolean;
  error: Error | null;
  refetch(): Promise<void>;
}

interface EncounterState {
  id: string | null;
  data: EncounterSnapshot | null;
  isLoading: boolean;
  error: Error | null;
}

const EMPTY_STATE: EncounterState = {
  id: null,
  data: null,
  isLoading: false,
  error: null,
};

export function useEncounter(id: string | null): UseEncounterResult {
  // Keep state grouped by the id it belongs to. When the caller passes a
  // new id, we derive a fresh slice on the next render rather than
  // imperatively clearing inside an effect.
  const [state, setState] = React.useState<EncounterState>(() =>
    id ? { id, data: null, isLoading: true, error: null } : EMPTY_STATE,
  );

  // If the caller's id no longer matches the state's id, reset during
  // render — this is the React 19 idiomatic pattern (see
  // https://react.dev/reference/react/useState#storing-information-from-previous-renders).
  if (state.id !== id) {
    setState(
      id ? { id, data: null, isLoading: true, error: null } : EMPTY_STATE,
    );
  }

  React.useEffect(() => {
    if (!id) return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const fetchOnce = async (): Promise<EncounterSnapshot | null> => {
      try {
        const snap = await getEncounter(id);
        if (controller.signal.aborted) return null;
        setState((prev) =>
          prev.id === id
            ? { id, data: snap, isLoading: false, error: null }
            : prev,
        );
        return snap;
      } catch (err) {
        if (controller.signal.aborted) return null;
        const e = err instanceof Error ? err : new Error(String(err));
        setState((prev) =>
          prev.id === id
            ? { ...prev, isLoading: false, error: e }
            : prev,
        );
        return null;
      }
    };

    const tick = async () => {
      if (stopped) return;
      const snap = await fetchOnce();
      if (stopped) return;
      // setTimeout (not setInterval) so the wall-clock gap between polls
      // is always at least POLL_INTERVAL_MS, even when a request takes
      // longer than the interval.
      if (snap && isTerminalStatus(snap.status)) return;
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    void tick();

    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  const refetch = React.useCallback(async () => {
    if (!id) return;
    try {
      const snap = await getEncounter(id);
      setState((prev) =>
        prev.id === id
          ? { id, data: snap, isLoading: false, error: null }
          : prev,
      );
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setState((prev) =>
        prev.id === id ? { ...prev, isLoading: false, error: e } : prev,
      );
    }
  }, [id]);

  return {
    data: state.data,
    isLoading: state.isLoading,
    error: state.error,
    refetch,
  };
}

interface UseStartEncounterResult {
  start(input: StartEncounterInput): Promise<{ id: string }>;
  isStarting: boolean;
  error: Error | null;
}

export function useStartEncounter(): UseStartEncounterResult {
  const [isStarting, setIsStarting] = React.useState<boolean>(false);
  const [error, setError] = React.useState<Error | null>(null);

  const start = React.useCallback(
    async (input: StartEncounterInput): Promise<{ id: string }> => {
      setIsStarting(true);
      setError(null);
      try {
        const res = await createEncounter(input);
        return { id: res.id };
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setIsStarting(false);
      }
    },
    [],
  );

  return { start, isStarting, error };
}
