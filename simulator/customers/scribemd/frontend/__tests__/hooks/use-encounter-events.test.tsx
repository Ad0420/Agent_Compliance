/**
 * Tests for `useEncounterEvents` — drives the SSE consumer via the
 * `MockEventSource` installed in vitest.setup.ts.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useEncounterEvents } from "@/hooks/use-encounter-events";
import { MockEventSource } from "../../vitest.setup";

describe("useEncounterEvents", () => {
  it("stays idle and creates no EventSource when encounterId is null", async () => {
    const { result } = renderHook(() => useEncounterEvents(null));

    expect(result.current.status).toBe("idle");
    expect(result.current.events).toEqual([]);
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it("transitions connecting -> open and accumulates events", async () => {
    const { result } = renderHook(() => useEncounterEvents("enc_1"));

    // Effect creates the EventSource and the hook is in `connecting` state.
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(result.current.status).toBe("connecting");

    const source = MockEventSource.last()!;

    act(() => {
      source.triggerOpen();
    });
    expect(result.current.status).toBe("open");

    // Fire two non-terminal events; both accumulate in `events`.
    act(() => {
      source.triggerEvent("draft_started", { ts: 1 });
    });
    act(() => {
      source.triggerEvent("draft_complete", { ts: 2 });
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events[0]).toEqual({
      event: "draft_started",
      data: { ts: 1 },
    });
    expect(result.current.events[1].event).toBe("draft_complete");
  });

  it("closes cleanly on a chart_committed event", async () => {
    const { result } = renderHook(() => useEncounterEvents("enc_2"));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.last()!;

    act(() => {
      source.triggerOpen();
    });
    act(() => {
      source.triggerEvent("chart_committed", { encounter_id: "enc_2" });
    });

    expect(result.current.status).toBe("closed");
    expect(source.readyState).toBe(MockEventSource.CLOSED);
    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0].event).toBe("chart_committed");
  });

  it("flips to error when the EventSource raises a non-CLOSED error", async () => {
    const { result } = renderHook(() => useEncounterEvents("enc_3"));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.last()!;

    act(() => {
      source.triggerOpen();
    });

    // readyState stays OPEN — onerror should treat as a hard error.
    act(() => {
      source.triggerError();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
